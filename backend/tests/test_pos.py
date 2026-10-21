import uuid
from decimal import Decimal
from django.test import override_settings

from rest_framework.test import APITestCase

from apps.customers.models import CustomerLedger
from apps.inventory.models import ShopProduct, StockMovement
from apps.sales.models import Payment, Sale

from .helpers import API, EAN_ATTA, EAN_BAD, add_listing, checkout, client_for, make_master, make_vendor


class CheckoutTests(APITestCase):
    def setUp(self):
        self.user, self.shop = make_vendor("owner1", "Kirana One")
        self.c = client_for(self.user, self.shop)
        self.master = make_master(tax="5.00")
        self.listing = add_listing(self.c, self.master, price="105.00", cost="60.00", stock="10")
        self.sp_id = self.listing["id"]

    def stock(self):
        return ShopProduct.objects.get(pk=self.sp_id).stock_qty

    def test_sale_updates_everything_consistently(self):
        r = checkout(self.c, self.sp_id, qty="2", payments=[{"method": "cash", "amount": "100.00"}, {"method": "upi", "amount": "110.00"}])
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["invoice_number"], "INV-000001")
        self.assertEqual(Decimal(r.data["total"]), Decimal("210.00"))
        self.assertEqual(Decimal(r.data["tax_total"]), Decimal("10.00"))  # tax-inclusive: 210*5/105
        self.assertEqual(Decimal(r.data["amount_due"]), Decimal("0"))
        self.assertEqual(self.stock(), Decimal("8"))
        self.assertEqual(StockMovement.objects.filter(movement_type="sale").count(), 1)
        self.assertEqual(Payment.objects.filter(kind="sale").count(), 2)

    def test_checkout_is_idempotent(self):
        txn = uuid.uuid4()
        pay = [{"method": "cash", "amount": "105.00"}]
        r1 = checkout(self.c, self.sp_id, qty="1", payments=pay, txn=txn)
        r2 = checkout(self.c, self.sp_id, qty="1", payments=pay, txn=txn)
        self.assertEqual((r1.status_code, r2.status_code), (201, 200))
        self.assertEqual(r1.data["id"], r2.data["id"])
        self.assertEqual(Sale.objects.count(), 1)
        self.assertEqual(self.stock(), Decimal("9"))
        self.assertEqual(Payment.objects.count(), 1)

    def test_insufficient_stock_rolls_back_everything(self):
        r = checkout(self.c, self.sp_id, qty="11", payments=[{"method": "cash", "amount": "1155.00"}])
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.data["code"], "insufficient_stock")
        self.assertEqual(Sale.objects.count(), 0)
        self.assertEqual(Payment.objects.count(), 0)
        self.assertEqual(self.stock(), Decimal("10"))
        self.shop.refresh_from_db()
        self.assertEqual(self.shop.invoice_counter, 0)

    def test_overpayment_and_bad_discount_are_rejected(self):
        self.assertEqual(checkout(self.c, self.sp_id, qty="1", payments=[{"method": "cash", "amount": "500"}]).data["code"], "overpayment")
        self.assertEqual(checkout(self.c, self.sp_id, qty="1", discount="999", payments=[]).data["code"], "invalid_discount")

    def test_pieces_must_be_whole(self):
        self.assertEqual(checkout(self.c, self.sp_id, qty="1.5", payments=[{"method": "cash", "amount": "50"}]).data["code"], "invalid_quantity")

    def test_credit_sale_needs_customer_and_posts_ledger(self):
        r = checkout(self.c, self.sp_id, qty="1", payments=[{"method": "cash", "amount": "5.00"}])
        self.assertEqual(r.data["code"], "customer_required")
        cust = self.c.post(f"{API}/shop/customers/", {"name": "Sunita", "phone": "9000000001"}, format="json").data
        r = checkout(self.c, self.sp_id, qty="1", payments=[{"method": "cash", "amount": "5.00"}], customer=cust["id"])
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(Decimal(r.data["amount_due"]), Decimal("100.00"))
        self.assertEqual(Decimal(self.c.get(f"{API}/shop/customers/{cust['id']}/").data["balance"]), Decimal("100.00"))
        pay = self.c.post(f"{API}/shop/customers/{cust['id']}/receive-payment/", {"amount": "40", "method": "upi"}, format="json")
        self.assertEqual(Decimal(pay.data["balance"]), Decimal("60.00"))
        over = self.c.post(f"{API}/shop/customers/{cust['id']}/receive-payment/", {"amount": "500", "method": "cash"}, format="json")
        self.assertEqual(over.status_code, 400)
        kinds = list(CustomerLedger.objects.order_by("id").values_list("entry_type", flat=True))
        self.assertEqual(kinds, ["credit_sale", "payment"])

    def test_old_invoice_is_unchanged_after_catalogue_and_price_changes(self):
        sale = checkout(self.c, self.sp_id, qty="1", payments=[{"method": "cash", "amount": "105.00"}]).data
        before = self.c.get(f"{API}/shop/sales/{sale['id']}/").data
        self.master.name = "Renamed Atta"
        self.master.tax_rate = Decimal("18.00")
        self.master.save()
        self.c.patch(f"{API}/shop/products/{self.sp_id}/", {"selling_price": "999.00"}, format="json")
        after = self.c.get(f"{API}/shop/sales/{sale['id']}/").data
        self.assertEqual(before["items"], after["items"])
        self.assertEqual(before["total"], after["total"])
        self.assertIn("Atta", after["items"][0]["product_name"])
        self.assertNotIn("Renamed", after["items"][0]["product_name"])

    def test_return_restocks_and_refunds(self):
        sale = checkout(self.c, self.sp_id, qty="2", payments=[{"method": "cash", "amount": "210.00"}]).data
        item_id = sale["items"][0]["id"]
        r = self.c.post(f"{API}/shop/sales/{sale['id']}/return/", {"items": [{"sale_item": item_id, "quantity": "1"}]}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "partially_returned")
        self.assertEqual(self.stock(), Decimal("9"))
        self.assertEqual(Payment.objects.get(kind="refund").amount, Decimal("-105.00"))
        too_many = self.c.post(f"{API}/shop/sales/{sale['id']}/return/", {"items": [{"sale_item": item_id, "quantity": "2"}]}, format="json")
        self.assertEqual(too_many.status_code, 400)

    def test_receipt_and_daily_summary(self):
        sale = checkout(self.c, self.sp_id, qty="1", payments=[{"method": "cash", "amount": "105.00"}]).data
        rec = self.c.get(f"{API}/shop/sales/{sale['id']}/receipt/").data
        self.assertIn("Kirana One", rec["text"])
        self.assertTrue(rec["whatsapp_url"].startswith("https://wa.me/"))
        s = self.c.get(f"{API}/shop/reports/daily-summary/").data
        self.assertEqual(s["bills"], 1)
        self.assertEqual(Decimal(s["sales_total"]), Decimal("105.00"))
        self.assertEqual(Decimal(s["gross_profit_estimate"]), Decimal("40.00"))  # (105-5 tax) - 60 cost

    def test_bills_can_be_listed_per_customer(self):
        cust = self.c.post(f"{API}/shop/customers/", {"name": "Sunita", "phone": "9000000011"}, format="json").data["id"]
        checkout(self.c, self.sp_id, qty="1", payments=[{"method": "cash", "amount": "105.00"}], customer=cust)
        checkout(self.c, self.sp_id, qty="1", payments=[{"method": "cash", "amount": "105.00"}])  # walk-in bill
        self.assertEqual(self.c.get(f"{API}/shop/sales/?customer={cust}").data["count"], 1)
        other, shop_b = make_vendor("other_v", "Other Shop")
        self.assertEqual(client_for(other, shop_b).get(f"{API}/shop/sales/?customer={cust}").data["count"], 0)

class StockAndBarcodeTests(APITestCase):
    def setUp(self):
        self.user, self.shop = make_vendor("owner2", "Kirana Two")
        self.c = client_for(self.user, self.shop)
        self.master = make_master()

    def test_barcode_validation(self):
        from services import barcode_service
        self.assertEqual(barcode_service.validate_barcode(EAN_ATTA), (EAN_ATTA, "EAN13"))
        with self.assertRaises(ValueError):
            barcode_service.validate_barcode(EAN_BAD)
        self.assertIn("0" + "123456789012", barcode_service.lookup_candidates("123456789012"))

    def test_scan_flow_unlisted_listed_and_unknown(self):
        r = self.c.get(f"{API}/shop/products/by-barcode/{EAN_ATTA}/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["master_product"]["id"], self.master.id)
        self.assertIsNone(r.data["shop_product"])
        add_listing(self.c, self.master, price="250.00", stock="5")
        r = self.c.get(f"{API}/shop/products/by-barcode/{EAN_ATTA}/")
        self.assertEqual(Decimal(r.data["shop_product"]["selling_price"]), Decimal("250"))
        self.assertEqual(self.c.get(f"{API}/shop/products/by-barcode/4006381333931/").status_code, 404)

    def test_stock_adjustments_are_ledgered_and_validated(self):
        sp = add_listing(self.c, self.master, stock="10")
        url = f"{API}/shop/products/{sp['id']}/adjust-stock/"
        ok = self.c.post(url, {"quantity_delta": "-3", "movement_type": "damage", "note": "wet"}, format="json")
        self.assertEqual(Decimal(ok.data["stock_qty"]), Decimal("7"))
        self.assertEqual(self.c.post(url, {"quantity_delta": "3", "movement_type": "damage"}, format="json").status_code, 400)
        self.assertEqual(self.c.post(url, {"quantity_delta": "-50", "movement_type": "adjustment"}, format="json").status_code, 409)
        buy = self.c.post(url, {"quantity_delta": "10", "movement_type": "purchase", "purchase_cost": "58.00"}, format="json")
        self.assertEqual(Decimal(buy.data["purchase_cost"]), Decimal("58.00"))
        moves = self.c.get(f"{API}/shop/products/{sp['id']}/movements/").data
        self.assertEqual([m["movement_type"] for m in moves], ["purchase", "damage", "opening"])

    def test_low_stock_filter(self):
        sp = add_listing(self.c, self.master, stock="3")
        self.c.patch(f"{API}/shop/products/{sp['id']}/", {"low_stock_threshold": "5"}, format="json")
        self.assertEqual(self.c.get(f"{API}/shop/products/?low_stock=true").data["count"], 1)


@override_settings(NEW_SHOPS_NEED_APPROVAL=False)
class AccountAndSubscriptionTests(APITestCase):
    def test_vendor_registration_and_login(self):
        from rest_framework.test import APIClient
        from apps.shops.models import ShopMembership
        c = APIClient()
        r = c.post(f"{API}/auth/register-vendor/", {"username": "newvendor", "password": "Str0ngPass!42",
                   "shop_name": "Gupta General Store", "phone": "9876500000"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["shops"][0]["role"], "owner")
        self.assertTrue(ShopMembership.objects.filter(user__username="newvendor", role="owner").exists())
        login = c.post(f"{API}/auth/login/", {"username": "newvendor", "password": "Str0ngPass!42"}, format="json")
        self.assertEqual(login.status_code, 200)
        bad = c.post(f"{API}/auth/login/", {"username": "newvendor", "password": "wrong"}, format="json")
        self.assertEqual(bad.status_code, 400)
        auth = APIClient()
        auth.credentials(HTTP_AUTHORIZATION="Token " + login.data["token"], HTTP_X_SHOP_ID=str(login.data["shops"][0]["id"]))
        self.assertEqual(auth.get(f"{API}/shop/subscription/").data["plan"], "Starter")

    def test_expired_subscription_is_read_only_after_grace(self):
        from datetime import timedelta
        from django.utils import timezone
        from apps.subscriptions.models import ShopSubscription
        user, shop = make_vendor("owner3", "Kirana Three")
        c = client_for(user, shop)
        master = make_master()
        listing = add_listing(c, master, stock="5")
        sub = ShopSubscription.objects.get(shop=shop)
        sub.expires_on = timezone.localdate() - timedelta(days=3)  # inside 7-day grace
        sub.save()
        self.assertEqual(c.patch(f"{API}/shop/products/{listing['id']}/", {"selling_price": "9"}, format="json").status_code, 200)
        sub.expires_on = timezone.localdate() - timedelta(days=30)
        sub.save()
        self.assertEqual(c.patch(f"{API}/shop/products/{listing['id']}/", {"selling_price": "8"}, format="json").status_code, 403)
        self.assertEqual(c.get(f"{API}/shop/products/").status_code, 200)   # data is never hidden or deleted
        self.assertEqual(c.get(f"{API}/shop/subscription/").data["write_allowed"], False)

    def test_product_limit_follows_plan(self):
        from apps.subscriptions.models import ShopSubscription
        user, shop = make_vendor("owner4", "Kirana Four")
        plan = ShopSubscription.objects.get(shop=shop).plan
        plan.max_products = 1
        plan.save()
        c = client_for(user, shop)
        add_listing(c, make_master("A", barcode=EAN_ATTA), stock="1")
        r = c.post(f"{API}/shop/products/", {"master_product": make_master("B", barcode=None).id, "selling_price": "5"}, format="json")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.data["code"], "subscription_limit")

    def test_owner_can_add_employee_cashier_cannot(self):
        user, shop = make_vendor("owner5", "Kirana Five")
        c = client_for(user, shop)
        r = c.post(f"{API}/shop/members/", {"username": "emp1", "password": "Emp0yeePass!7", "role": "cashier"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        from apps.accounts.models import User
        emp = client_for(User.objects.get(username="emp1"), shop)
        self.assertEqual(emp.get(f"{API}/shop/members/").status_code, 403)
