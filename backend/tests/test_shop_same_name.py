"""Two different shops may have the same name. They must always stay two shops - in registration, sign-in, payments
and every admin screen - and be easy to tell apart."""
from decimal import Decimal

from django.test import override_settings
from rest_framework.test import APIClient, APITestCase

from apps.accounts.models import User
from apps.shops.models import Shop, ShopMembership
from apps.subscriptions.models import SubscriptionPlan
from services import payment_service, subscription_service

API = "/api/v1"


def register(username, phone, address):
    r = APIClient().post(f"{API}/auth/register-vendor/", {
        "username": username, "password": "Strong#Pass1", "full_name": username.title(), "phone": phone,
        "shop_name": "Sharma Kirana", "address": address}, format="json")
    assert r.status_code == 201, r.data
    return r.data


@override_settings(NEW_SHOPS_NEED_APPROVAL=False)
class SameNameShopTests(APITestCase):
    def setUp(self):
        self.a = register("ownera", "9000000001", "Karol Bagh")
        self.b = register("ownerb", "9000000002", "Lajpat Nagar")
        self.shop_a = Shop.objects.get(pk=self.a["shops"][0]["id"])
        self.shop_b = Shop.objects.get(pk=self.b["shops"][0]["id"])

    def client_of(self, data, shop_id):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION="Token " + data["token"], HTTP_X_SHOP_ID=str(shop_id))
        return c

    def test_registration_makes_two_separate_shops(self):
        self.assertNotEqual(self.shop_a.pk, self.shop_b.pk)
        self.assertEqual((self.shop_a.name, self.shop_b.name), ("Sharma Kirana", "Sharma Kirana"))
        self.assertEqual((self.shop_a.phone, self.shop_b.phone), ("9000000001", "9000000002"))
        self.assertNotEqual(self.shop_a.payment_code, self.shop_b.payment_code)
        self.assertNotEqual(self.shop_a.pay_paise, self.shop_b.pay_paise)
        self.assertEqual([s["id"] for s in self.a["shops"]], [self.shop_a.pk])     # each owner sees only their shop
        self.assertEqual([s["id"] for s in self.b["shops"]], [self.shop_b.pk])

    def test_each_owner_works_only_in_their_own_shop(self):
        a = self.client_of(self.a, self.shop_a.pk)
        self.assertEqual(a.patch(f"{API}/shop/", {"address": "Karol Bagh, Block 4"}, format="json").status_code, 200)
        self.shop_b.refresh_from_db()
        self.assertEqual(self.shop_b.address, "Lajpat Nagar")
        self.assertEqual(self.client_of(self.a, self.shop_b.pk).get(f"{API}/shop/").status_code, 403)

    def test_every_label_tells_them_apart(self):
        self.assertNotEqual(str(self.shop_a), str(self.shop_b))
        self.assertEqual(str(self.shop_a), f"Sharma Kirana (#{self.shop_a.pk} · 9000000001)")
        member = ShopMembership.objects.get(shop=self.shop_b, role="owner")
        self.assertIn(f"#{self.shop_b.pk}", str(member))

    def test_ambiguous_bank_payment_lists_both_shops(self):
        plan = SubscriptionPlan.objects.create(code="std", name="Standard", price_monthly=Decimal("499"))
        Shop.objects.filter(pk=self.shop_b.pk).update(pay_paise=self.shop_a.pay_paise)   # force the same amount
        shops = list(Shop.objects.filter(pk__in=[self.shop_a.pk, self.shop_b.pk]))
        amount = subscription_service.amount_for(plan, 1, self.shop_a)
        shop, option, _how, note = payment_service.match(amount, "UPI payment", shops, [plan])
        self.assertIsNone(shop)
        self.assertIn(f"#{self.shop_a.pk}", note)
        self.assertIn(f"#{self.shop_b.pk}", note)          # was merged into one "Sharma Kirana" before

    def test_admin_can_find_each_shop_by_owner_mobile_and_spot_shops_without_owner(self):
        admin = User.objects.create_superuser("platform", password="Admin#Pass1")
        orphan = Shop.objects.create(name="Sharma Kirana")
        c = APIClient()
        c.force_login(admin)
        page = c.get("/admin/shops/shop/?q=9000000002").content.decode()
        self.assertIn(f">{self.shop_b.pk}<", page)
        self.assertNotIn(f">{self.shop_a.pk}<", page)
        none = c.get("/admin/shops/shop/?owner=none").content.decode()
        self.assertIn("NO OWNER", none)
        self.assertIn(f">{orphan.pk}<", none)
        self.assertNotIn(f">{self.shop_a.pk}<", none)
