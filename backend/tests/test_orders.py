import uuid
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient, APITestCase

from apps.customers.models import Customer
from apps.inventory.models import ShopProduct
from apps.orders.models import Order
from apps.sales.models import Sale
from apps.subscriptions.models import ShopSubscription

from .helpers import API, add_listing, client_for, make_master, make_vendor


def register_shopper(name="Anita", phone="9876543210", password="secret123"):
    c = APIClient()
    r = c.post(f"{API}/store/auth/register/", {"name": name, "phone": phone, "password": password}, format="json")
    assert r.status_code == 201, r.data
    c.credentials(HTTP_AUTHORIZATION="Shopper " + r.data["token"])
    return c


class OrderFlowTests(APITestCase):
    def setUp(self):
        self.owner, self.shop = make_vendor("ord_owner", "Order Shop")
        self.v = client_for(self.owner, self.shop)
        self.sp = add_listing(self.v, make_master("Soap", barcode=None, pack="1"), price="30.00", cost="20.00", stock="10")["id"]
        r = self.v.patch(f"{API}/shop/store-settings/", {
            "store_enabled": True, "accepts_delivery": True, "accepts_pickup": True,
            "delivery_fee": "20.00", "free_delivery_above": "200.00", "min_order": "50.00"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.code = r.data["store_code"]
        self.s = register_shopper()

    def place(self, qty="2", fulfilment="delivery", txn=None, client=None, **extra):
        body = {"shop": self.shop.id, "client_txn_id": str(txn or uuid.uuid4()), "fulfilment": fulfilment,
                "address": "12 Gandhi Road, Etawah", "payment_method": "cash",
                "items": [{"shop_product": self.sp, "quantity": qty}]}
        body.update(extra)
        return (client or self.s).post(f"{API}/store/orders/", body, format="json")

    def vendor(self, order_id, action, **body):
        return self.v.post(f"{API}/shop/orders/{order_id}/{action}/", body, format="json")

    # ----- identity and separation -----
    def test_store_and_shop_tokens_are_separate(self):
        self.assertEqual(self.s.get(f"{API}/shop/products/").status_code, 401)   # a customer cannot open shop screens
        tok = Token.objects.create(user=self.owner)
        staff = APIClient()
        staff.credentials(HTTP_AUTHORIZATION="Token " + tok.key)
        self.assertEqual(staff.get(f"{API}/store/orders/").status_code, 401)     # a shop login is not a customer
        me = self.s.get(f"{API}/store/auth/me/")
        self.assertEqual(me.data["phone"], "9876543210")
        again = APIClient().post(f"{API}/store/auth/login/", {"phone": "+91 98765 43210", "password": "secret123"}, format="json")
        self.assertEqual(again.status_code, 200)
        self.assertEqual(APIClient().post(f"{API}/store/auth/login/", {"phone": "9876543210", "password": "nope"}, format="json").status_code, 400)

    def test_shop_is_found_by_code_and_only_when_the_store_is_on(self):
        found = self.s.get(f"{API}/store/shops/?code={self.code.lower()}").data
        self.assertEqual([x["name"] for x in found], ["Order Shop"])
        self.assertNotIn("store_code", found[0])
        self.v.patch(f"{API}/shop/store-settings/", {"store_enabled": False}, format="json")
        self.assertEqual(self.s.get(f"{API}/store/shops/?code={self.code}").data, [])
        self.assertEqual(self.place().status_code, 400)

    def test_customer_sees_prices_but_never_costs_or_exact_stock(self):
        row = self.s.get(f"{API}/store/shops/{self.shop.id}/products/").data["results"][0]
        self.assertEqual(row["selling_price"], "30.00")
        self.assertTrue(row["in_stock"])
        for secret in ("purchase_cost", "stock_qty"):
            self.assertNotIn(secret, row)

    # ----- placing -----
    def test_totals_fees_and_rules(self):
        r = self.place(qty="2")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual((Decimal(r.data["subtotal"]), Decimal(r.data["delivery_fee"]), Decimal(r.data["total"])),
                         (Decimal("60.00"), Decimal("20.00"), Decimal("80.00")))
        self.assertEqual(r.data["number"], 1)
        self.assertEqual(Decimal(self.place(qty="8").data["delivery_fee"]), Decimal("0.00"))        # free above Rs 200
        self.assertEqual(Decimal(self.place(qty="2", fulfilment="pickup").data["delivery_fee"]), Decimal("0.00"))
        self.assertEqual(self.place(qty="1").data["code"], "below_minimum")
        self.assertEqual(self.place(address="x").data["code"], "address_required")
        self.assertEqual(self.place(qty="11").data["code"], "out_of_stock")

    def test_double_tap_does_not_create_two_orders(self):
        txn = uuid.uuid4()
        a, b = self.place(txn=txn), self.place(txn=txn)
        self.assertEqual((a.status_code, b.status_code), (201, 200))
        self.assertEqual(Order.objects.count(), 1)

    def test_no_vendor_customer_is_created_from_an_order(self):
        self.place()
        self.assertEqual(Customer.objects.count(), 0)

    def test_shop_with_expired_subscription_takes_no_orders(self):
        sub = ShopSubscription.objects.get(shop=self.shop)
        sub.expires_on = timezone.localdate() - timedelta(days=30)
        sub.save()
        self.assertEqual(self.place().data["code"], "shop_closed")

    # ----- the shop's steps -----
    def test_full_delivery_flow_creates_a_normal_bill(self):
        oid = self.place(qty="3").data["id"]
        self.assertEqual(self.v.get(f"{API}/shop/orders/summary/").data["new"], 1)
        self.assertEqual(self.vendor(oid, "pack").data["code"], "wrong_status")       # accept first
        self.assertEqual(self.vendor(oid, "accept").data["status"], "accepted")
        self.assertEqual(self.vendor(oid, "complete").data["code"], "wrong_status")   # not out yet
        self.assertEqual(self.vendor(oid, "pack").data["status"], "packed")
        self.assertEqual(self.vendor(oid, "ready").data["status"], "out_for_delivery")
        done = self.vendor(oid, "complete", payment_method="upi")
        self.assertEqual(done.data["status"], "completed", done.data)
        order = Order.objects.get(pk=oid)
        self.assertIsNotNone(order.sale)
        self.assertEqual(order.sale.total, Decimal("90.00"))
        self.assertEqual(ShopProduct.objects.get(pk=self.sp).stock_qty, Decimal("7"))
        self.assertEqual(Sale.objects.count(), 1)
        self.assertEqual([e["status"] for e in self.s.get(f"{API}/store/orders/{oid}/").data["events"]],
                         ["placed", "accepted", "packed", "out_for_delivery", "completed"])
        self.assertEqual(self.vendor(oid, "complete").data["code"], "wrong_status")  # cannot bill twice
        self.assertEqual(Sale.objects.count(), 1)

    def test_pickup_flow(self):
        oid = self.place(qty="2", fulfilment="pickup").data["id"]
        self.vendor(oid, "accept")
        self.vendor(oid, "pack")
        self.assertEqual(self.vendor(oid, "ready").data["status"], "ready_for_pickup")
        self.assertEqual(self.vendor(oid, "complete", payment_method="cash").data["status"], "completed")

    def test_shop_can_lower_or_remove_items_when_accepting(self):
        data = self.place(qty="3").data
        item = data["items"][0]["id"]
        r = self.vendor(data["id"], "accept", items=[{"item": item, "quantity": "1"}])
        self.assertEqual((Decimal(r.data["subtotal"]), Decimal(r.data["total"])), (Decimal("30.00"), Decimal("50.00")))
        self.assertEqual(Decimal(r.data["items"][0]["ordered_quantity"]), Decimal("3"))
        more = self.place(qty="3").data
        up = self.vendor(more["id"], "accept", items=[{"item": more["items"][0]["id"], "quantity": "5"}])
        self.assertEqual(up.data["code"], "invalid_quantity")
        gone = self.vendor(more["id"], "accept", items=[{"item": more["items"][0]["id"], "quantity": "0"}])
        self.assertEqual(gone.data["status"], "rejected")

    def test_reject_needs_a_reason_and_customer_cancel_only_before_accept(self):
        a = self.place().data["id"]
        self.assertEqual(self.vendor(a, "reject").data["code"], "reason_required")
        self.assertEqual(self.vendor(a, "reject", reason="Closed today").data["status"], "rejected")
        self.assertEqual(self.s.get(f"{API}/store/orders/{a}/").data["reason"], "Closed today")
        b = self.place().data["id"]
        self.assertEqual(self.s.post(f"{API}/store/orders/{b}/cancel/").data["status"], "cancelled")
        c = self.place().data["id"]
        self.vendor(c, "accept")
        self.assertEqual(self.s.post(f"{API}/store/orders/{c}/cancel/").data["code"], "too_late")

    # ----- privacy -----
    def test_orders_are_private_to_the_customer_and_the_shop(self):
        oid = self.place().data["id"]
        other = register_shopper("Raju", "9123456780")
        self.assertEqual(other.get(f"{API}/store/orders/{oid}/").status_code, 404)
        self.assertEqual(other.get(f"{API}/store/orders/").data["count"], 0)
        other_owner, other_shop = make_vendor("ord_other", "Other Shop")
        self.assertEqual(client_for(other_owner, other_shop).get(f"{API}/shop/orders/{oid}/").status_code, 404)
        inv, _ = make_vendor("ord_inv", role="inventory", shop=self.shop)
        self.assertEqual(client_for(inv, self.shop).get(f"{API}/shop/orders/").status_code, 403)
        cashier, _ = make_vendor("ord_cashier", role="cashier", shop=self.shop)
        self.assertEqual(client_for(cashier, self.shop).get(f"{API}/shop/orders/").status_code, 200)