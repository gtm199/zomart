import uuid
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone
from rest_framework.test import APITestCase

from apps.inventory.models import ShopProduct
from apps.sales.models import Sale

from .helpers import API, add_listing, client_for, make_master, make_vendor


def offline_sale(client, sp_id, qty="1", price=None, when=None, paid="105.00", txn=None):
    item = {"shop_product": sp_id, "quantity": qty}
    if price is not None:
        item["unit_price"] = price
    body = {"client_txn_id": str(txn or uuid.uuid4()), "offline": True, "items": [item],
            "payments": [{"method": "cash", "amount": paid}]}
    if when:
        body["client_created_at"] = when.isoformat()
    return client.post(f"{API}/shop/sales/", body, format="json")


class OfflineSaleTests(APITestCase):
    def setUp(self):
        self.user, self.shop = make_vendor("off_owner", "Offline Shop")
        self.c = client_for(self.user, self.shop)
        self.sp = add_listing(self.c, make_master(), price="105.00", cost="60.00", stock="2")["id"]

    def test_offline_sale_is_accepted_even_when_stock_runs_out_and_is_flagged(self):
        r = offline_sale(self.c, self.sp, qty="3", paid="315.00")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(r.data["is_offline"] and r.data["needs_review"])
        self.assertIn("stock went below zero", r.data["review_note"])
        self.assertEqual(ShopProduct.objects.get(pk=self.sp).stock_qty, Decimal("-1"))
        self.assertEqual(self.c.get(f"{API}/shop/sales/?needs_review=true").data["count"], 1)

    def test_online_sales_still_refuse_missing_stock(self):
        body = {"client_txn_id": str(uuid.uuid4()), "items": [{"shop_product": self.sp, "quantity": "3"}],
                "payments": [{"method": "cash", "amount": "315.00"}]}
        self.assertEqual(self.c.post(f"{API}/shop/sales/", body, format="json").status_code, 409)

    def test_price_the_cashier_charged_is_kept_and_flagged(self):
        r = offline_sale(self.c, self.sp, price="90.00", paid="90.00")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(Decimal(r.data["items"][0]["unit_price"]), Decimal("90.00"))
        self.assertEqual(Decimal(r.data["total"]), Decimal("90.00"))
        self.assertIn("charged 90.00", r.data["review_note"])

    def test_normal_offline_sale_is_not_flagged(self):
        r = offline_sale(self.c, self.sp, price="105.00")
        self.assertFalse(r.data["needs_review"])

    def test_upload_is_idempotent(self):
        txn = uuid.uuid4()
        r1, r2 = offline_sale(self.c, self.sp, txn=txn), offline_sale(self.c, self.sp, txn=txn)
        self.assertEqual((r1.status_code, r2.status_code), (201, 200))
        self.assertEqual(Sale.objects.count(), 1)
        self.assertEqual(ShopProduct.objects.get(pk=self.sp).stock_qty, Decimal("1"))

    def test_bill_time_from_the_phone_is_used_but_never_the_future(self):
        past = timezone.now() - timedelta(days=2)
        r = offline_sale(self.c, self.sp, when=past)
        self.assertEqual(Sale.objects.get(pk=r.data["id"]).created_at.date(), past.date())
        future = offline_sale(self.c, self.sp, when=timezone.now() + timedelta(days=5), paid="105.00")
        self.assertLessEqual(Sale.objects.get(pk=future.data["id"]).created_at, timezone.now())
        old = offline_sale(self.c, self.sp, when=timezone.now() - timedelta(days=60))
        self.assertTrue(old.data["needs_review"])

    def test_credit_sale_from_phone_posts_to_the_customer(self):
        cust = self.c.post(f"{API}/shop/customers/", {"name": "Geeta", "phone": "9000000044"}, format="json").data["id"]
        body = {"client_txn_id": str(uuid.uuid4()), "offline": True, "customer": cust,
                "items": [{"shop_product": self.sp, "quantity": "1", "unit_price": "105.00"}], "payments": []}
        r = self.c.post(f"{API}/shop/sales/", body, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(Decimal(self.c.get(f"{API}/shop/customers/{cust}/").data["balance"]), Decimal("105.00"))


class SyncEndpointTests(APITestCase):
    def setUp(self):
        self.user, self.shop = make_vendor("sync_owner", "Sync Shop")
        self.c = client_for(self.user, self.shop)
        self.sp = add_listing(self.c, make_master(), price="105.00", cost="60.00", stock="5")["id"]
        self.c.post(f"{API}/shop/customers/", {"name": "Ravi", "phone": "9000000055"}, format="json")

    def test_full_sync_has_products_and_customers_but_no_costs(self):
        r = self.c.get(f"{API}/shop/sync/")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data["full"])
        p = r.data["products"][0]
        self.assertEqual(p["selling_price"], "105.00")
        self.assertNotIn("purchase_cost", p)
        self.assertEqual(len(p["barcodes"]), 1)
        self.assertEqual(r.data["customers"][0]["name"], "Ravi")

    def test_delta_sync_returns_only_changes(self):
        first = self.c.get(f"{API}/shop/sync/").data
        self.c.patch(f"{API}/shop/products/{self.sp}/", {"selling_price": "110.00"}, format="json")
        delta = self.c.get(f"{API}/shop/sync/", {"since": first["server_time"]}).data
        self.assertFalse(delta["full"])
        self.assertEqual(delta["products"][0]["selling_price"], "110.00")
        later = (timezone.now() + timedelta(hours=1)).isoformat()
        nothing = self.c.get(f"{API}/shop/sync/", {"since": later}).data
        self.assertEqual((len(nothing["products"]), len(nothing["customers"])), (0, 0))
        self.assertEqual(self.c.get(f"{API}/shop/sync/", {"since": "garbage"}).status_code, 400)

    def test_sale_and_credit_show_up_in_the_next_delta(self):
        first = self.c.get(f"{API}/shop/sync/").data
        cust = first["customers"][0]["id"]
        body = {"client_txn_id": str(uuid.uuid4()), "offline": True, "customer": cust,
                "items": [{"shop_product": self.sp, "quantity": "2", "unit_price": "105.00"}], "payments": []}
        self.c.post(f"{API}/shop/sales/", body, format="json")
        delta = self.c.get(f"{API}/shop/sync/", {"since": first["server_time"]}).data
        self.assertEqual(delta["products"][0]["stock_qty"], "3.000")
        self.assertEqual(delta["customers"][0]["balance"], "210.00")

    def test_other_shops_data_never_appears_and_inventory_role_is_refused(self):
        other, shop_b = make_vendor("sync_other", "Other")
        data = client_for(other, shop_b).get(f"{API}/shop/sync/").data
        self.assertEqual((len(data["products"]), len(data["customers"])), (0, 0))
        inv, _ = make_vendor("sync_inv", role="inventory", shop=self.shop)
        self.assertEqual(client_for(inv, self.shop).get(f"{API}/shop/sync/").status_code, 403)