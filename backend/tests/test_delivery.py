import uuid
from decimal import Decimal

from rest_framework.test import APITestCase

from apps.customers.models import Customer
from apps.inventory.models import ShopProduct
from apps.orders.models import DeliveryTrack, Order
from apps.sales.models import Sale
from services import tracking_service

from .helpers import API, add_listing, client_for, make_master, make_vendor
from .test_orders import register_shopper

NEAR = (26.7945, 79.0215)   # about 1 km from the shop
FAR = (27.2000, 79.0000)    # about 45 km away


class DeliveryTrackingTests(APITestCase):
    def setUp(self):
        self.owner, self.shop = make_vendor("dl_owner", "Delivery Shop")
        self.v = client_for(self.owner, self.shop)
        self.sp = add_listing(self.v, make_master("Soap", barcode=None, pack="1"), price="100.00", cost="60.00", stock="50")["id"]
        r = self.v.patch(f"{API}/shop/store-settings/", {
            "store_enabled": True, "accepts_delivery": True, "accepts_pickup": True, "delivery_fee": "20.00", "min_order": "0",
            "latitude": "26.785500", "longitude": "79.021500", "delivery_radius_km": "5"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.rider_user, _ = make_vendor("dl_rider", role="delivery", shop=self.shop)
        self.r = client_for(self.rider_user, self.shop)
        self.s = register_shopper("Track Cust", "9811122233")

    # ----- helpers -----
    def place(self, point=NEAR, qty="1", payment="cash", fulfilment="delivery", client=None, **extra):
        body = {"shop": self.shop.id, "client_txn_id": str(uuid.uuid4()), "fulfilment": fulfilment,
                "address": "12 Gandhi Road, Etawah", "payment_method": payment,
                "items": [{"shop_product": self.sp, "quantity": qty}]}
        if point:
            body.update(delivery_lat=point[0], delivery_lng=point[1])
        body.update(extra)
        return (client or self.s).post(f"{API}/store/orders/", body, format="json")

    def step(self, order_id, action, **body):
        return self.v.post(f"{API}/shop/orders/{order_id}/{action}/", body, format="json")

    def send_out(self, order_id, rider=True):
        self.step(order_id, "accept")
        self.step(order_id, "pack")
        return self.step(order_id, "ready", rider=self.rider_user.id if rider else None)

    def out_for_delivery(self, **kw):
        oid = self.place(**kw).data["id"]
        self.assertEqual(self.send_out(oid).data["status"], "out_for_delivery")
        return oid

    def rider_post(self, oid, action, **body):
        return self.r.post(f"{API}/delivery/orders/{oid}/{action}/", body, format="json")

    def pin(self, oid):
        return Order.objects.get(pk=oid).delivery_pin

    # ----- the PIN and the location -----
    def test_only_the_customer_ever_sees_the_pin(self):
        oid = self.place().data["id"]
        self.assertEqual(len(self.pin(oid)), 4)
        self.assertIsNone(self.s.get(f"{API}/store/orders/{oid}/").data["delivery_pin"])   # not until it is out
        self.send_out(oid)
        self.assertEqual(self.s.get(f"{API}/store/orders/{oid}/").data["delivery_pin"], self.pin(oid))
        self.assertNotIn("delivery_pin", self.v.get(f"{API}/shop/orders/{oid}/").data)
        rider_view = self.r.get(f"{API}/delivery/orders/{oid}/").data
        self.assertNotIn("delivery_pin", rider_view)
        self.assertNotIn(self.pin(oid), str(rider_view))
        self.assertEqual(self.v.get(f"{API}/shop/orders/{oid}/").data["rider_name"], self.rider_user.first_name or "dl_rider")

    def test_locations_outside_the_area_or_invalid_are_refused(self):
        self.assertEqual(self.place(point=FAR).data["code"], "outside_area")
        self.assertEqual(self.place(point=(0, 0)).data["code"], "invalid_location")
        self.assertEqual(self.place(point=None, delivery_lat=26.79).status_code, 400)   # latitude without longitude
        self.assertEqual(self.place(point=None).status_code, 201)                      # a pin is optional
        self.assertEqual(self.place(point=FAR, fulfilment="pickup").status_code, 201)  # pickup ignores the location

    # ----- who may deliver -----
    def test_only_the_assigned_rider_works_the_delivery(self):
        oid = self.out_for_delivery()
        mine = self.r.get(f"{API}/delivery/orders/").data["results"]
        self.assertEqual([o["id"] for o in mine], [oid])
        other, _ = make_vendor("dl_rider2", role="delivery", shop=self.shop)
        oc = client_for(other, self.shop)
        self.assertEqual(oc.get(f"{API}/delivery/orders/").data["results"], [])
        self.assertEqual(oc.post(f"{API}/delivery/orders/{oid}/start/", {}, format="json").status_code, 404)
        cashier, _ = make_vendor("dl_cashier", role="cashier", shop=self.shop)
        self.assertEqual(client_for(cashier, self.shop).get(f"{API}/delivery/orders/").status_code, 403)
        again = self.place().data["id"]
        self.step(again, "accept")
        self.step(again, "pack")
        self.assertEqual(self.step(again, "ready", rider=self.owner.id).data["code"], "rider_not_found")
        self.assertEqual(self.step(again, "ready", rider=999999).data["code"], "rider_not_found")
        listed = self.v.get(f"{API}/shop/riders/").data
        self.assertEqual({r["id"] for r in listed}, {self.rider_user.id, other.id})

    # ----- live tracking -----
    def test_the_customer_follows_the_rider(self):
        oid = self.out_for_delivery()
        before = self.s.get(f"{API}/store/orders/{oid}/track/").data
        self.assertIsNone(before["rider"]["lat"])                                     # rider has not set off yet
        self.assertEqual(self.rider_post(oid, "location", lat=26.7860, lng=79.0216).data["code"], "trip_not_started")
        self.assertEqual(self.rider_post(oid, "start").status_code, 200)
        self.assertEqual(self.rider_post(oid, "location", lat=95, lng=79).status_code, 400)
        self.assertEqual(self.rider_post(oid, "location", lat=26.7900, lng=79.0215, heading=12.5, speed=5.0, accuracy=8).status_code, 200)
        t = self.s.get(f"{API}/store/orders/{oid}/track/").data
        self.assertEqual((t["rider"]["lat"], t["rider"]["lng"]), (26.79, 79.0215))
        self.assertEqual(t["pin"], self.pin(oid))
        self.assertGreaterEqual(t["eta_minutes"], 1)
        self.assertLess(t["distance_km"], 1.0)
        self.assertEqual(t["destination"]["lat"], NEAR[0])
        self.assertEqual(t["shop"]["lat"], 26.7855)
        self.assertFalse(t["rider"]["arrived"])
        self.rider_post(oid, "arrived")
        self.assertTrue(self.s.get(f"{API}/store/orders/{oid}/track/").data["rider"]["arrived"])
        stranger = register_shopper("Stranger", "9012345670")
        self.assertEqual(stranger.get(f"{API}/store/orders/{oid}/track/").status_code, 404)

    # ----- handing over -----
    def test_the_order_is_completed_only_with_the_customers_pin(self):
        oid = self.out_for_delivery(qty="2")
        self.rider_post(oid, "start")
        self.rider_post(oid, "location", lat=26.7900, lng=79.0215)
        wrong = "0000" if self.pin(oid) != "0000" else "1111"
        self.assertEqual(self.rider_post(oid, "deliver", pin=wrong).data["code"], "wrong_pin")
        for _ in range(4):
            self.rider_post(oid, "deliver", pin=wrong)
        locked = self.rider_post(oid, "deliver", pin=self.pin(oid))               # five wrong tries lock the rider out
        self.assertEqual(locked.data["code"], "pin_locked")
        self.assertTrue(self.r.get(f"{API}/delivery/orders/{oid}/").data["pin_locked"])
        self.assertEqual(self.step(oid, "complete", payment_method="cash").data["status"], "completed")  # the shop can still finish it

    def test_delivery_with_the_right_pin_makes_the_bill_and_forgets_the_location(self):
        oid = self.out_for_delivery(qty="2")
        self.rider_post(oid, "start")
        self.rider_post(oid, "location", lat=26.7900, lng=79.0215)
        done = self.rider_post(oid, "deliver", pin=self.pin(oid), payment_method="upi")
        self.assertEqual(done.status_code, 200, done.data)
        self.assertEqual(done.data["status"], "completed")
        order = Order.objects.get(pk=oid)
        self.assertEqual(order.sale.total, Decimal("200.00"))
        self.assertEqual(Sale.objects.count(), 1)
        self.assertEqual(ShopProduct.objects.get(pk=self.sp).stock_qty, Decimal("48"))
        track = DeliveryTrack.objects.get(order=order)
        self.assertIsNone(track.rider_lat)
        self.assertIsNone(self.s.get(f"{API}/store/orders/{oid}/track/").data["rider"])
        self.assertEqual(len(self.r.get(f"{API}/delivery/orders/?scope=today").data["results"]), 1)
        self.assertEqual(self.r.get(f"{API}/delivery/orders/").data["results"], [])

    def test_a_credit_order_delivered_by_a_rider_goes_on_the_account(self):
        self.s.post(f"{API}/store/credit/request/", {"shop": self.shop.id}, format="json")
        row = self.v.get(f"{API}/shop/credit-requests/?status=requested").data["results"][0]
        self.v.post(f"{API}/shop/credit-requests/{row['id']}/approve/", {"limit": "500"}, format="json")
        oid = self.out_for_delivery(payment="credit", qty="1")
        info = self.r.get(f"{API}/delivery/orders/{oid}/").data
        self.assertEqual((info["on_credit"], info["collect_amount"]), (True, "20.00"))   # only the delivery fee at the door
        self.rider_post(oid, "start")
        self.assertEqual(self.rider_post(oid, "deliver", pin=self.pin(oid)).status_code, 200)
        self.assertEqual(Customer.objects.get(phone="9811122233").balance, Decimal("100"))

    # ----- helpers that need no network -----
    def test_distances_need_no_outside_service(self):
        km = tracking_service.haversine_km(26.7855, 79.0215, *NEAR)
        self.assertAlmostEqual(km, 1.0, delta=0.1)
        self.assertFalse(tracking_service.valid_point(0, 0))