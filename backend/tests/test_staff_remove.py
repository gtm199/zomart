"""Removing a staff member: they lose access and are signed out, their mobile number can be used again, and the shop's
history (who made each bill) is kept. Owner only; never the owner; never a rider who is out on a delivery."""
import uuid

from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient, APITestCase

from apps.accounts.models import User
from apps.orders.models import Order, Shopper
from apps.sales.models import Sale
from apps.shops.models import ShopMembership

from .helpers import API, add_listing, checkout, client_for, make_master, make_vendor
from .test_orders import register_shopper
from .test_retention import make_row

MEMBERS = f"{API}/shop/members/"


class RemoveStaffTests(APITestCase):
    def setUp(self):
        self.owner, self.shop = make_vendor("rs_owner", "Staff Shop")
        self.c = client_for(self.owner, self.shop)
        r = self.c.post(MEMBERS, {"username": "9000000071", "password": "Cashier#1234", "full_name": "Ravi",
                                  "phone": "9000000071", "role": "cashier"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.member_id = r.data["id"]
        self.cashier = User.objects.get(username="9000000071")

    def token_client(self, user, shop):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION="Token " + Token.objects.create(user=user).key, HTTP_X_SHOP_ID=str(shop.id))
        return c

    def test_owner_removes_staff_and_they_lose_access_everywhere(self):
        phone = self.token_client(self.cashier, self.shop)
        self.assertEqual(phone.get(f"{API}/shop/").status_code, 200)
        r = self.c.delete(f"{MEMBERS}{self.member_id}/")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual((r.data["removed"], r.data["name"], r.data["account_locked"]), (True, "Ravi", True))
        self.assertFalse(ShopMembership.objects.filter(pk=self.member_id).exists())
        self.assertNotIn(self.member_id, [m["id"] for m in self.c.get(MEMBERS).data["results"]])
        self.assertEqual(phone.get(f"{API}/shop/").status_code, 401)            # signed out on their phone
        login = APIClient().post(f"{API}/auth/login/", {"username": "9000000071", "password": "Cashier#1234"}, format="json")
        self.assertEqual(login.status_code, 400)                                 # cannot sign in again
        self.cashier.refresh_from_db()
        self.assertFalse(self.cashier.is_active)
        self.assertTrue(self.cashier.username.startswith("removed-"))

    def test_bills_keep_who_made_them(self):
        sp = add_listing(self.c, make_master(), price="50.00", stock="5")["id"]
        sale_id = checkout(client_for(self.cashier, self.shop), sp, qty="1",
                           payments=[{"method": "cash", "amount": "50.00"}]).data["id"]
        self.c.delete(f"{MEMBERS}{self.member_id}/")
        sale = Sale.objects.select_related("cashier").get(pk=sale_id)
        self.assertEqual((sale.cashier_id, sale.cashier.first_name), (self.cashier.pk, "Ravi"))

    def test_the_same_mobile_number_can_be_added_again(self):
        self.c.delete(f"{MEMBERS}{self.member_id}/")
        again = self.c.post(MEMBERS, {"username": "9000000071", "password": "Cashier#5678", "full_name": "Ravi",
                                      "phone": "9000000071", "role": "cashier"}, format="json")
        self.assertEqual(again.status_code, 201, again.data)
        ok = APIClient().post(f"{API}/auth/login/", {"username": "9000000071", "password": "Cashier#5678"}, format="json")
        self.assertEqual(ok.status_code, 200)

    def test_owner_and_self_cannot_be_removed(self):
        owner_member = ShopMembership.objects.get(shop=self.shop, role="owner")
        r = self.c.delete(f"{MEMBERS}{owner_member.id}/")
        self.assertEqual((r.status_code, r.data["code"]), (403, "owner_cannot_be_removed"))
        self.assertTrue(User.objects.get(pk=self.owner.pk).is_active)

    def test_only_the_owner_may_remove_and_only_in_their_own_shop(self):
        manager, _ = make_vendor("rs_mgr", role="manager", shop=self.shop)
        self.assertEqual(client_for(manager, self.shop).delete(f"{MEMBERS}{self.member_id}/").status_code, 403)
        other, other_shop = make_vendor("rs_other", "Other")
        r = client_for(other, other_shop).delete(f"{MEMBERS}{self.member_id}/")
        self.assertEqual(r.status_code, 404)
        self.assertTrue(ShopMembership.objects.filter(pk=self.member_id).exists())

    def test_someone_working_in_two_shops_keeps_the_other_shop(self):
        _, shop_b = make_vendor("rs_owner_b", "Second Shop")
        ShopMembership.objects.create(user=self.cashier, shop=shop_b, role="cashier")
        r = self.c.delete(f"{MEMBERS}{self.member_id}/")
        self.assertFalse(r.data["account_locked"])
        self.cashier.refresh_from_db()
        self.assertTrue(self.cashier.is_active)
        self.assertEqual(self.cashier.username, "9000000071")
        self.assertEqual(client_for(self.cashier, shop_b).get(f"{API}/shop/").status_code, 200)
        self.assertEqual(client_for(self.cashier, self.shop).get(f"{API}/shop/").status_code, 403)

    def test_rider_out_on_a_delivery_cannot_be_removed_yet(self):
        rider, _ = make_vendor("rs_rider", role="delivery", shop=self.shop)
        register_shopper()
        order = make_row(Order, shop=self.shop, shopper=Shopper.objects.first(), rider=rider, client_txn_id=uuid.uuid4(),
                         status=Order.Status.OUT_FOR_DELIVERY)
        member = ShopMembership.objects.get(shop=self.shop, user=rider)
        r = self.c.delete(f"{MEMBERS}{member.id}/")
        self.assertEqual((r.status_code, r.data["code"]), (409, "rider_has_active_deliveries"))
        Order.objects.filter(pk=order.pk).update(status=Order.Status.COMPLETED)
        self.assertEqual(self.c.delete(f"{MEMBERS}{member.id}/").status_code, 200)
