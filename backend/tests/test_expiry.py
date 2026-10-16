import uuid
from datetime import timedelta

from django.utils import timezone
from rest_framework.test import APITestCase

from .helpers import API, add_listing, client_for, make_master, make_vendor


class ExpiryTests(APITestCase):
    def setUp(self):
        self.user, self.shop = make_vendor("exp_owner", "Expiry Shop")
        self.c = client_for(self.user, self.shop)
        self.sp = add_listing(self.c, make_master(), stock="5")["id"]
        self.today = timezone.localdate()

    def set_expiry(self, days):
        return self.c.patch(f"{API}/shop/products/{self.sp}/", {"expiry_date": str(self.today + timedelta(days=days))}, format="json")

    def test_status_and_alerts(self):
        self.set_expiry(10)
        p = self.c.get(f"{API}/shop/products/{self.sp}/").data
        self.assertEqual((p["expiry_status"], p["days_to_expiry"]), ("expiring_soon", 10))
        a = self.c.get(f"{API}/shop/products/expiry-alerts/").data
        self.assertEqual((a["expired_count"], a["expiring_soon_count"]), (0, 1))
        self.set_expiry(-1)
        self.assertEqual(self.c.get(f"{API}/shop/products/{self.sp}/").data["expiry_status"], "expired")
        self.assertEqual(self.c.get(f"{API}/shop/products/expiry-alerts/").data["expired_count"], 1)
        self.set_expiry(60)
        self.assertEqual(self.c.get(f"{API}/shop/products/{self.sp}/").data["expiry_status"], "ok")
        self.assertEqual(self.c.get(f"{API}/shop/products/?expiring=true").data["count"], 0)

    def test_out_of_stock_products_do_not_alert(self):
        self.set_expiry(5)
        self.c.post(f"{API}/shop/products/{self.sp}/adjust-stock/", {"quantity_delta": "-5", "movement_type": "adjustment"}, format="json")
        self.assertEqual(self.c.get(f"{API}/shop/products/expiry-alerts/").data["expiring_soon_count"], 0)

    def test_expiry_can_be_cleared(self):
        self.set_expiry(5)
        self.c.patch(f"{API}/shop/products/{self.sp}/", {"expiry_date": None}, format="json")
        self.assertIsNone(self.c.get(f"{API}/shop/products/{self.sp}/").data["expiry_date"])

    def test_purchase_sets_or_keeps_expiry(self):
        sup = self.c.post(f"{API}/shop/suppliers/", {"name": "Exp Supplier"}, format="json").data["id"]

        def buy(sp, date):
            return self.c.post(f"{API}/shop/purchases/", {
                "client_txn_id": str(uuid.uuid4()), "supplier": sup, "payments": [],
                "items": [{"shop_product": sp, "quantity": "10", "unit_cost": "50", "expiry_date": str(date)}]}, format="json")

        self.set_expiry(20)  # 5 pieces already on the shelf, expiring in 20 days
        buy(self.sp, self.today + timedelta(days=90))  # newer lot arrives
        self.assertEqual(self.c.get(f"{API}/shop/products/{self.sp}/").data["expiry_date"], str(self.today + timedelta(days=20)))
        empty = add_listing(self.c, make_master("Fresh Dal", barcode=None), stock="0")["id"]
        buy(empty, self.today + timedelta(days=45))  # no old stock, so the new date is used
        self.assertEqual(self.c.get(f"{API}/shop/products/{empty}/").data["expiry_date"], str(self.today + timedelta(days=45)))

    def test_other_shop_sees_no_alerts(self):
        self.set_expiry(5)
        other, shop_b = make_vendor("exp_other", "Other Shop")
        a = client_for(other, shop_b).get(f"{API}/shop/products/expiry-alerts/").data
        self.assertEqual((a["expired_count"], a["expiring_soon_count"]), (0, 0))