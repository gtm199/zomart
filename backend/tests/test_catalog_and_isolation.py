from decimal import Decimal

from rest_framework.test import APITestCase

from apps.catalog.models import MasterProduct, ProductChangeLog, ProductSuggestion
from apps.accounts.models import User
from apps.inventory.models import ShopProduct

from .helpers import API, EAN_ATTA, add_listing, checkout, client_for, make_master, make_vendor


class SharedCatalogueTests(APITestCase):
    def setUp(self):
        self.ua, self.shop_a = make_vendor("vendor_a", "Shop A")
        self.ub, self.shop_b = make_vendor("vendor_b", "Shop B")
        self.a, self.b = client_for(self.ua, self.shop_a), client_for(self.ub, self.shop_b)
        self.master = make_master()

    def test_both_vendors_see_same_master_but_keep_independent_listings(self):
        for c in (self.a, self.b):
            r = c.get(f"{API}/catalog/products/")
            self.assertEqual([p["id"] for p in r.data["results"]], [self.master.id])
        la = add_listing(self.a, self.master, price="250.00", cost="225.00", stock="20")
        lb = add_listing(self.b, self.master, price="245.00", cost="220.00", stock="12")
        self.assertNotEqual(la["id"], lb["id"])
        self.assertEqual(MasterProduct.objects.count(), 1)
        self.assertEqual(ShopProduct.objects.count(), 2)
        self.assertEqual(Decimal(self.a.get(f"{API}/shop/products/{la['id']}/").data["stock_qty"]), Decimal("20"))
        self.assertEqual(Decimal(self.b.get(f"{API}/shop/products/{lb['id']}/").data["selling_price"]), Decimal("245"))
        # catalogue shows each vendor their own listing id
        self.assertEqual(self.a.get(f"{API}/catalog/products/").data["results"][0]["my_listing_id"], la["id"])
        self.assertEqual(self.b.get(f"{API}/catalog/products/").data["results"][0]["my_listing_id"], lb["id"])

    def test_master_update_does_not_touch_vendor_price_or_stock(self):
        la = add_listing(self.a, self.master, price="250.00", stock="20")
        admin = User.objects.create_user("platform_admin", password="x", is_staff=True)
        r = client_for(admin).patch(f"{API}/platform/catalog/products/{self.master.id}/",
                                    {"description": "New text", "mrp": "260.00"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        after = self.a.get(f"{API}/shop/products/{la['id']}/").data
        self.assertEqual(Decimal(after["selling_price"]), Decimal("250"))
        self.assertEqual(Decimal(after["stock_qty"]), Decimal("20"))
        self.assertEqual(after["master_product"]["description"], "New text")
        self.assertTrue(ProductChangeLog.objects.filter(product=self.master, field="mrp").exists())

    def test_product_cannot_be_listed_twice_by_same_shop(self):
        add_listing(self.a, self.master)
        r = self.a.post(f"{API}/shop/products/", {"master_product": self.master.id, "selling_price": "1"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_inactive_master_blocks_new_listing_and_new_sales_but_keeps_history(self):
        la = add_listing(self.a, self.master, price="100.00", stock="10")
        sale = checkout(self.a, la["id"], qty="1", payments=[{"method": "cash", "amount": "100.00"}])
        self.assertEqual(sale.status_code, 201)
        self.master.status = MasterProduct.Status.INACTIVE
        self.master.save()
        r = checkout(self.a, la["id"], qty="1", payments=[{"method": "cash", "amount": "100.00"}])
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["code"], "product_unavailable")
        self.assertEqual(self.a.get(f"{API}/shop/sales/{sale.data['id']}/").status_code, 200)
        r = self.b.post(f"{API}/shop/products/", {"master_product": self.master.id, "selling_price": "1"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_suggestions_are_reviewed_and_never_auto_trusted(self):
        r = self.a.post(f"{API}/shop/product-suggestions/", {"name": "Mystery Dal", "brand_name": "Local",
                        "barcode": "", "pack_size": "1", "unit": "kg"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        sid = ProductSuggestion.objects.get().id
        admin = client_for(User.objects.create_user("adm", password="x", is_staff=True))
        self.assertEqual(admin.post(f"{API}/platform/catalog/suggestions/{sid}/approve/").status_code, 200)
        created = MasterProduct.objects.get(name="Mystery Dal")
        self.assertEqual(created.status, MasterProduct.Status.DRAFT)
        names = [p["name"] for p in self.b.get(f"{API}/catalog/products/").data["results"]]
        self.assertNotIn("Mystery Dal", names)

    def test_vendors_cannot_use_admin_endpoints(self):
        self.assertEqual(self.a.get(f"{API}/platform/catalog/products/").status_code, 403)
        self.assertEqual(self.a.patch(f"{API}/platform/catalog/products/{self.master.id}/", {"name": "x"}, format="json").status_code, 403)


class TenantIsolationTests(APITestCase):
    def setUp(self):
        self.ua, self.shop_a = make_vendor("vendor_a", "Shop A")
        self.ub, self.shop_b = make_vendor("vendor_b", "Shop B")
        self.a, self.b = client_for(self.ua, self.shop_a), client_for(self.ub, self.shop_b)
        self.master = make_master()
        self.la = add_listing(self.a, self.master, price="100.00", cost="60.00", stock="10")
        self.sale = checkout(self.a, self.la["id"], qty="1", payments=[{"method": "cash", "amount": "100.00"}]).data

    def test_cannot_use_another_shops_id_header(self):
        c = client_for(self.ub, self.shop_a)
        self.assertEqual(c.get(f"{API}/shop/products/").status_code, 403)
        self.assertEqual(c.get(f"{API}/shop/sales/").status_code, 403)

    def test_missing_shop_header_and_anonymous_are_rejected(self):
        self.assertEqual(client_for(self.ua).get(f"{API}/shop/products/").status_code, 403)
        from rest_framework.test import APIClient
        self.assertEqual(APIClient().get(f"{API}/shop/products/").status_code, 401)

    def test_vendor_b_cannot_read_vendor_a_records(self):
        self.assertEqual(self.b.get(f"{API}/shop/products/").data["count"], 0)
        self.assertEqual(self.b.get(f"{API}/shop/products/{self.la['id']}/").status_code, 404)
        self.assertEqual(self.b.get(f"{API}/shop/sales/").data["count"], 0)
        self.assertEqual(self.b.get(f"{API}/shop/sales/{self.sale['id']}/").status_code, 404)
        self.assertEqual(self.b.get(f"{API}/shop/sales/{self.sale['id']}/receipt/").status_code, 404)
        self.assertEqual(self.b.patch(f"{API}/shop/products/{self.la['id']}/", {"selling_price": "1"}, format="json").status_code, 404)

    def test_vendor_b_cannot_sell_vendor_a_listing(self):
        r = checkout(self.b, self.la["id"], qty="1", payments=[{"method": "cash", "amount": "100.00"}])
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["code"], "product_not_found")

    def test_same_phone_customer_is_independent_per_vendor(self):
        ra = self.a.post(f"{API}/shop/customers/", {"name": "Rahul", "phone": "9876543210"}, format="json")
        rb = self.b.post(f"{API}/shop/customers/", {"name": "Rahul", "phone": "9876543210"}, format="json")
        self.assertEqual((ra.status_code, rb.status_code), (201, 201))
        self.assertNotEqual(ra.data["id"], rb.data["id"])
        self.assertEqual(self.a.get(f"{API}/shop/customers/{rb.data['id']}/").status_code, 404)
        # duplicate inside one shop is refused
        dup = self.a.post(f"{API}/shop/customers/", {"name": "Rahul 2", "phone": "+91 98765 43210"}, format="json")
        self.assertEqual(dup.status_code, 400)

    def test_cashier_cannot_see_costs_or_do_privileged_actions(self):
        uc, _ = make_vendor("cashier1", role="cashier", shop=self.shop_a)
        c = client_for(uc, self.shop_a)
        data = c.get(f"{API}/shop/products/{self.la['id']}/").data
        self.assertNotIn("purchase_cost", data)
        self.assertEqual(c.post(f"{API}/shop/products/{self.la['id']}/adjust-stock/",
                                {"quantity_delta": "5", "movement_type": "purchase"}, format="json").status_code, 403)
        self.assertEqual(c.get(f"{API}/shop/reports/daily-summary/").status_code, 403)
        self.assertEqual(c.post(f"{API}/shop/sales/{self.sale['id']}/return/",
                                {"items": [{"sale_item": 1, "quantity": "1"}]}, format="json").status_code, 403)
        self.assertIn("purchase_cost", self.a.get(f"{API}/shop/products/{self.la['id']}/").data)
