"""A customer finds every active, approved shop by name, town or mobile, and keeps as many shops as they like.
Shops that do not take online orders yet can be added, but ordering, products and credit stay closed for them."""
import uuid

from rest_framework.test import APITestCase

from apps.orders.models import ShopperShop

from .helpers import API, client_for, make_vendor
from .test_orders import register_shopper


class CustomerManyShopsTests(APITestCase):
    def setUp(self):
        self.o1, self.online = make_vendor("own1", "Test1")
        client_for(self.o1, self.online).patch(f"{API}/shop/store-settings/", {
            "store_enabled": True, "accepts_delivery": True, "accepts_pickup": True, "min_order": "0"}, format="json")
        _, self.offline = make_vendor("own2", "Test2")
        _, self.twin = make_vendor("own3", "Test2")                     # same name, different shop and mobile
        self.offline.phone, self.twin.phone = "9811111111", "9822222222"
        self.offline.city = "Delhi"
        self.offline.save(); self.twin.save()
        _, self.hidden = make_vendor("own4", "Test2 closed")
        self.hidden.is_active = False
        self.hidden.save()
        self.s = register_shopper()

    def find(self, term):
        return self.s.get(f"{API}/store/shops/", {"search": term}).data

    def test_shops_without_online_orders_are_searchable(self):
        rows = self.find("test2")
        self.assertEqual(sorted(r["id"] for r in rows), sorted([self.offline.id, self.twin.id]))   # inactive one hidden
        self.assertTrue(all(r["online_orders"] is False for r in rows))
        self.assertEqual([r["id"] for r in self.find("Delhi")], [self.offline.id])
        self.assertEqual([r["id"] for r in self.find("+91 98222 22222")], [self.twin.id])       # by shop mobile
        first = self.find("test")
        self.assertEqual(first[0]["id"], self.online.id)                 # shops taking orders come first
        self.assertTrue(first[0]["online_orders"])
        for secret in ("store_code", "gstin", "payment_code"):
            self.assertNotIn(secret, first[0])

    def test_customer_adds_several_shops_and_removes_one(self):
        for shop in (self.online, self.offline, self.twin):
            self.assertEqual(self.s.post(f"{API}/store/my-shops/", {"shop": shop.id}, format="json").status_code, 201)
        self.s.post(f"{API}/store/my-shops/", {"shop": self.online.id}, format="json")              # twice: no duplicate
        mine = self.s.get(f"{API}/store/my-shops/").data
        self.assertEqual([r["id"] for r in mine], [self.online.id, self.offline.id, self.twin.id])
        self.assertEqual(ShopperShop.objects.count(), 3)
        self.assertEqual(self.s.post(f"{API}/store/my-shops/", {"shop": self.hidden.id}, format="json").status_code, 404)
        self.s.delete(f"{API}/store/my-shops/", {"shop": self.twin.id}, format="json")
        self.assertEqual([r["id"] for r in self.s.get(f"{API}/store/my-shops/").data], [self.online.id, self.offline.id])

    def test_offline_shop_still_cannot_take_orders_or_credit(self):
        self.s.post(f"{API}/store/my-shops/", {"shop": self.offline.id}, format="json")
        self.assertEqual(self.s.get(f"{API}/store/shops/{self.offline.id}/").status_code, 404)
        self.assertEqual(self.s.get(f"{API}/store/shops/{self.offline.id}/products/").status_code, 404)
        self.assertEqual(self.s.get(f"{API}/store/shops/", {"code": ""}).status_code, 200)
        r = self.s.post(f"{API}/store/orders/", {"shop": self.offline.id, "client_txn_id": str(uuid.uuid4()),
                                                 "fulfilment": "pickup", "payment_method": "cash", "items": []}, format="json")
        self.assertIn(r.status_code, (400, 404))
        self.assertIn(self.s.post(f"{API}/store/credit/request/", {"shop": self.offline.id}, format="json").status_code,
                      (400, 404))
