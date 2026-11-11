import uuid
from unittest import mock

from asgiref.sync import sync_to_async
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.test import TransactionTestCase
from rest_framework.test import APITestCase

from apps.orders.models import Order, SavedAddress, Shopper, ShopperToken
from apps.orders.routing import websocket_urlpatterns
from services import tracking_service

from .helpers import API, add_listing, client_for, make_master, make_vendor
from .test_orders import register_shopper

SHOP = (26.7855, 79.0215)
NEAR = (26.7945, 79.0215)    # about 1 km north of the shop
OTHER = (26.7900, 79.0300)   # a bit to the east


class Fixture:
    """A shop with one rider and one customer."""

    def build(self):
        self.owner, self.shop = make_vendor("ng_owner", "No Google Shop")
        self.v = client_for(self.owner, self.shop)
        self.sp = add_listing(self.v, make_master("Soap", barcode=None, pack="1"), price="100.00", cost="60.00", stock="50")["id"]
        self.v.patch(f"{API}/shop/store-settings/", {
            "store_enabled": True, "accepts_delivery": True, "accepts_pickup": True, "delivery_fee": "20.00", "min_order": "0",
            "latitude": str(SHOP[0]), "longitude": str(SHOP[1]), "delivery_radius_km": "5"}, format="json")
        self.rider_user, _ = make_vendor("ng_rider", role="delivery", shop=self.shop)
        self.r = client_for(self.rider_user, self.shop)
        self.s = register_shopper("Link Cust", "9866677788")

    def save_address(self, point=NEAR, text="12 Gandhi Road, Etawah", client=None):
        r = (client or self.s).post(f"{API}/store/addresses/", {"label": "Home", "address": text, "lat": point[0], "lng": point[1]}, format="json")
        assert r.status_code == 201, r.data
        return r.data["id"]

    def place(self, point=None, address_id=None, client=None):
        body = {"shop": self.shop.id, "client_txn_id": str(uuid.uuid4()), "fulfilment": "delivery", "address": "12 Gandhi Road, Etawah",
                "payment_method": "cash", "items": [{"shop_product": self.sp, "quantity": "1"}]}
        if point:
            body.update(delivery_lat=point[0], delivery_lng=point[1])
        if address_id:
            body["address_id"] = address_id
        r = (client or self.s).post(f"{API}/store/orders/", body, format="json")
        assert r.status_code == 201, r.data
        return r.data["id"]

    def step(self, oid, action, **body):
        return self.v.post(f"{API}/shop/orders/{oid}/{action}/", body, format="json")

    def send_out(self, oid):
        self.step(oid, "accept")
        self.step(oid, "pack")
        assert self.step(oid, "ready", rider=self.rider_user.id).status_code == 200
        return oid

    def rider_order(self, oid):
        return self.r.get(f"{API}/delivery/orders/{oid}/").data


class SavedAddressTests(Fixture, APITestCase):
    def setUp(self):
        self.build()
        self.url = f"{API}/store/addresses/"

    def test_an_address_needs_its_map_position_to_be_saved(self):
        no_pin = self.s.post(self.url, {"label": "Home", "address": "12 Gandhi Road, Etawah"}, format="json")
        self.assertEqual((no_pin.status_code, no_pin.data["code"]), (400, "pin_required"))
        self.assertEqual(self.s.post(self.url, {"label": "Home", "address": "short"}, format="json").status_code, 400)
        a = self.save_address()
        row = self.s.get(self.url).data["results"][0]
        self.assertEqual((row["id"], row["lat"], row["lng"]), (a, NEAR[0], NEAR[1]))

    def test_addresses_are_private_and_limited_to_ten(self):
        a = self.save_address()
        other = register_shopper("Other", "9877788899")
        self.assertEqual(other.get(self.url).data["results"], [])
        self.assertEqual(other.delete(f"{self.url}{a}/").status_code, 404)
        self.assertEqual(other.patch(f"{self.url}{a}/", {"lat": 1, "lng": 1}, format="json").status_code, 404)
        for n in range(9):
            self.save_address(text=f"{n + 20} Station Road, Etawah")
        r = self.s.post(self.url, {"label": "x", "address": "99 Last Road, Etawah", "lat": 26.7, "lng": 79.0}, format="json")
        self.assertEqual(r.data["code"], "too_many_addresses")


class LinkFollowsTheSavedAddressTests(Fixture, APITestCase):
    def setUp(self):
        self.build()

    def test_moving_the_pin_on_the_address_changes_what_the_rider_gets(self):
        a = self.save_address(NEAR)
        oid = self.send_out(self.place(address_id=a))
        self.assertEqual((self.rider_order(oid)["delivery_lat"], self.rider_order(oid)["delivery_lng"]), NEAR)
        self.s.patch(f"{API}/store/addresses/{a}/", {"lat": OTHER[0], "lng": OTHER[1]}, format="json")
        moved = self.rider_order(oid)
        self.assertEqual((moved["delivery_lat"], moved["delivery_lng"]), OTHER)       # nothing was stored as a link
        self.assertEqual(self.s.get(f"{API}/store/orders/{oid}/track/").data["destination"]["lat"], OTHER[0])

    def test_deleting_the_address_keeps_the_position_that_was_ordered(self):
        a = self.save_address(NEAR)
        oid = self.send_out(self.place(address_id=a))
        self.s.delete(f"{API}/store/addresses/{a}/")
        gone = self.rider_order(oid)
        self.assertEqual((gone["delivery_lat"], gone["has_position"]), (NEAR[0], True))

    def test_a_pin_without_a_saved_address_is_kept_on_the_order(self):
        oid = self.send_out(self.place(point=NEAR))
        self.assertEqual(self.rider_order(oid)["delivery_lat"], NEAR[0])

    def test_you_cannot_order_to_somebody_elses_saved_address(self):
        other = register_shopper("Other", "9888899900")
        theirs = self.save_address(NEAR, client=other)
        r = self.s.post(f"{API}/store/orders/", {
            "shop": self.shop.id, "client_txn_id": str(uuid.uuid4()), "fulfilment": "delivery", "address": "12 Gandhi Road, Etawah",
            "payment_method": "cash", "address_id": theirs, "items": [{"shop_product": self.sp, "quantity": "1"}]}, format="json")
        self.assertEqual(r.data["code"], "address_not_found")

    def test_the_customer_can_move_the_pin_of_an_order_in_progress(self):
        a = self.save_address(NEAR)
        oid = self.send_out(self.place(address_id=a))
        moved = self.s.patch(f"{API}/store/orders/{oid}/location/", {"lat": OTHER[0], "lng": OTHER[1]}, format="json")
        self.assertEqual(moved.status_code, 200, moved.data)
        self.assertEqual(self.rider_order(oid)["delivery_lat"], OTHER[0])
        self.assertAlmostEqual(float(SavedAddress.objects.get(pk=a).lat), OTHER[0], places=5)   # the saved address moved too
        far = self.s.patch(f"{API}/store/orders/{oid}/location/", {"lat": 27.2, "lng": 79.0}, format="json")
        self.assertEqual(far.data["code"], "outside_area")
        stranger = register_shopper("Stranger", "9899900011")
        self.assertEqual(stranger.patch(f"{API}/store/orders/{oid}/location/", {"lat": OTHER[0], "lng": OTHER[1]}, format="json").status_code, 404)
        self.r.post(f"{API}/delivery/orders/{oid}/start/", {}, format="json")
        self.step(oid, "complete", payment_method="cash")
        late = self.s.patch(f"{API}/store/orders/{oid}/location/", {"lat": NEAR[0], "lng": NEAR[1]}, format="json")
        self.assertEqual(late.data["code"], "too_late")


class RiderFirstDeliveryTests(Fixture, APITestCase):
    def setUp(self):
        self.build()

    def save_at_door(self, oid, point=NEAR, client=None):
        return (client or self.r).post(f"{API}/delivery/orders/{oid}/save-location/", {"lat": point[0], "lng": point[1]}, format="json")

    def test_the_rider_saves_the_position_once_and_it_is_kept_for_next_time(self):
        oid = self.send_out(self.place())                                   # the customer gave no pin
        self.assertFalse(self.rider_order(oid)["has_position"])
        done = self.save_at_door(oid)
        self.assertEqual(done.status_code, 200, done.data)
        self.assertEqual((done.data["has_position"], done.data["delivery_lat"]), (True, NEAR[0]))
        saved = SavedAddress.objects.get(shopper__phone="9866677788")
        self.assertEqual((saved.address, float(saved.lat)), ("12 Gandhi Road, Etawah", NEAR[0]))
        self.assertEqual(self.save_at_door(oid, OTHER).data["code"], "has_position")      # a position is never overwritten
        again = self.send_out(self.place(address_id=saved.id))
        self.assertTrue(self.rider_order(again)["has_position"])                           # the next order already has it

    def test_a_saved_address_without_a_pin_is_filled_in(self):
        saved = SavedAddress.objects.create(shopper=Shopper.objects.get(phone="9866677788"), label="Old", address="12 Gandhi Road, Etawah")
        oid = self.send_out(self.place(address_id=saved.id))
        self.assertFalse(self.rider_order(oid)["has_position"])
        self.save_at_door(oid)
        saved.refresh_from_db()
        self.assertAlmostEqual(float(saved.lat), NEAR[0], places=5)
        self.assertEqual(SavedAddress.objects.count(), 1)

    def test_only_the_assigned_rider_and_only_real_places(self):
        oid = self.send_out(self.place())
        other, _ = make_vendor("ng_rider2", role="delivery", shop=self.shop)
        self.assertEqual(self.save_at_door(oid, client=client_for(other, self.shop)).status_code, 404)
        self.assertEqual(self.save_at_door(oid, point=(0, 0)).data["code"], "invalid_location")


class NoGoogleTests(Fixture, APITestCase):
    def setUp(self):
        self.build()

    def test_the_whole_delivery_makes_no_outgoing_request(self):
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("no outside call is allowed")):
            a = self.save_address(NEAR)
            oid = self.send_out(self.place(address_id=a))
            self.r.post(f"{API}/delivery/orders/{oid}/start/", {}, format="json")
            self.assertEqual(self.r.post(f"{API}/delivery/orders/{oid}/location/", {"lat": SHOP[0] + 0.004, "lng": SHOP[1]}, format="json").status_code, 200)
            track = self.s.get(f"{API}/store/orders/{oid}/track/").data
            self.assertNotIn("route", track)
            pin = Order.objects.get(pk=oid).delivery_pin
            done = self.r.post(f"{API}/delivery/orders/{oid}/deliver/", {"pin": pin, "payment_method": "cash"}, format="json")
            self.assertEqual(done.data["status"], "completed")

    def test_time_left_is_a_straight_line_made_a_little_longer_for_the_roads(self):
        oid = self.send_out(self.place(point=NEAR))
        self.r.post(f"{API}/delivery/orders/{oid}/start/", {}, format="json")
        self.r.post(f"{API}/delivery/orders/{oid}/location/", {"lat": SHOP[0], "lng": SHOP[1]}, format="json")
        t = self.s.get(f"{API}/store/orders/{oid}/track/").data
        straight = tracking_service.haversine_km(*SHOP, *NEAR)
        self.assertAlmostEqual(t["distance_km"], round(straight * tracking_service.ROAD_FACTOR, 1), places=1)
        self.assertGreaterEqual(t["eta_minutes"], 2)


class TrackSocketTests(Fixture, TransactionTestCase):
    """The customer's screen receives the rider's moves as they happen, and nobody else can listen in."""

    def setUp(self):
        self.build()
        self.oid = self.send_out(self.place(point=NEAR))
        self.r.post(f"{API}/delivery/orders/{self.oid}/start/", {}, format="json")
        self.token = ShopperToken.objects.get(shopper__phone="9866677788").key

    def socket(self):
        return WebsocketCommunicator(URLRouter(websocket_urlpatterns), f"/ws/track/{self.oid}/")

    def rider_moves(self, lat, lng):
        return self.r.post(f"{API}/delivery/orders/{self.oid}/location/", {"lat": lat, "lng": lng, "heading": 90.0}, format="json")

    async def test_the_customer_is_sent_every_move(self):
        comm = self.socket()
        connected, _ = await comm.connect()
        self.assertTrue(connected)
        await comm.send_json_to({"type": "auth", "token": self.token})
        self.assertEqual((await comm.receive_json_from(timeout=3))["type"], "ready")
        await sync_to_async(self.rider_moves)(26.7900, 79.0215)
        msg = await comm.receive_json_from(timeout=3)
        self.assertEqual((msg["type"], msg["lat"], msg["lng"], msg["heading"]), ("position", 26.79, 79.0215, 90.0))
        self.assertGreaterEqual(msg["eta_minutes"], 1)
        await sync_to_async(self.r.post)(f"{API}/delivery/orders/{self.oid}/arrived/", {}, format="json")
        self.assertEqual((await comm.receive_json_from(timeout=3))["type"], "refresh")
        await comm.send_json_to({"type": "ping"})
        self.assertEqual((await comm.receive_json_from(timeout=3))["type"], "pong")
        await comm.disconnect()

    async def test_a_wrong_token_or_somebody_elses_order_is_refused(self):
        other_token = await sync_to_async(self._other_token)()
        for token in ("not-a-token", other_token):
            comm = self.socket()
            await comm.connect()
            await comm.send_json_to({"type": "auth", "token": token})
            out = await comm.receive_output(timeout=3)
            self.assertEqual(out["type"], "websocket.close")
            await comm.wait()

    def _other_token(self):
        register_shopper("Nosy", "9855566679")
        return ShopperToken.objects.get(shopper__phone="9855566679").key