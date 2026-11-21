"""Customer app: sign in with mobile number, username or email (one box)."""
from django.core.cache import cache
from rest_framework.test import APIClient, APITestCase

from apps.orders.models import Shopper
from services import shopper_login_service

from .helpers import API

LOGIN = f"{API}/store/auth/login/"
REGISTER = f"{API}/store/auth/register/"
PROFILE = f"{API}/store/auth/profile/"


class ShopperLoginOptionsTests(APITestCase):
    def setUp(self):
        cache.clear()   # login try limits
        r = APIClient().post(REGISTER, {"name": "Anita", "phone": "9876543210", "email": "Anita@Example.com",
                                        "username": "Anita_22", "password": "secret123"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["shopper"]["username"], "Anita_22")
        self.token = r.data["token"]

    def login(self, who, password="secret123", field="login"):
        return APIClient().post(LOGIN, {field: who, "password": password}, format="json")

    def me(self):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION="Shopper " + self.token)
        return c

    def test_mobile_username_and_email_all_work(self):
        for who in ("9876543210", "+91 98765 43210", "anita_22", "ANITA_22", " Anita_22 ", "anita@example.com"):
            r = self.login(who)
            self.assertEqual(r.status_code, 200, (who, r.data))
            self.assertEqual(r.data["shopper"]["phone"], "9876543210")

    def test_old_app_versions_still_send_phone(self):
        self.assertEqual(self.login("9876543210", field="phone").status_code, 200)
        self.assertEqual(self.login("anita_22", field="phone").status_code, 200)

    def test_wrong_password_or_unknown_gives_the_same_message(self):
        a, b = self.login("anita_22", "nope"), self.login("nobody_here")
        self.assertEqual((a.status_code, b.status_code), (400, 400))
        self.assertEqual(a.data["detail"], b.data["detail"])
        self.assertEqual(self.login("").status_code, 400)
        Shopper.objects.update(is_active=False)
        self.assertEqual(self.login("anita_22").status_code, 400)

    def test_username_rules_and_uniqueness(self):
        base = {"name": "B", "password": "secret123"}
        taken = APIClient().post(REGISTER, {**base, "phone": "9876500001", "username": "ANITA_22"}, format="json")
        self.assertEqual(taken.status_code, 400)
        self.assertIn("username", taken.data)
        for bad in ("98765", "ab", "a b", "a@b", "_anita", "x" * 31):
            r = APIClient().post(REGISTER, {**base, "phone": "9876500002", "username": bad}, format="json")
            self.assertEqual(r.status_code, 400, bad)
        none = APIClient().post(REGISTER, {**base, "phone": "9876500003"}, format="json")
        self.assertEqual((none.status_code, none.data["shopper"]["username"]), (201, ""))   # still optional
        other = APIClient().post(REGISTER, {**base, "phone": "9876500004", "username": "ravi.k"}, format="json")
        self.assertEqual(other.status_code, 201)

    def test_set_change_and_remove_username_in_profile(self):
        c = self.me()
        self.assertEqual(c.patch(PROFILE, {"username": "anita.s"}, format="json").data["username"], "anita.s")
        self.assertEqual(self.login("anita.s").status_code, 200)
        self.assertEqual(self.login("anita_22").status_code, 400)          # the old one is gone
        APIClient().post(REGISTER, {"name": "R", "phone": "9876500005", "username": "ravi", "password": "secret123"}, format="json")
        self.assertEqual(c.patch(PROFILE, {"username": "RAVI"}, format="json").status_code, 400)
        self.assertEqual(c.patch(PROFILE, {"username": ""}, format="json").data["username"], "")
        self.assertEqual(self.login("9876543210").status_code, 200)        # mobile always works

    def test_try_limit_counts_one_account_however_it_is_typed(self):
        # (try limits are switched off while testing, so the key they use is checked directly)
        key = shopper_login_service.throttle_key
        self.assertEqual({key("anita_22"), key("ANITA_22"), key(" Anita_22 ")}, {"username:anita_22"})
        self.assertEqual({key("9876543210"), key("+91 98765 43210"), key("098765-43210")}, {"phone:9876543210"})
        self.assertEqual(key("Anita@Example.com"), "email:anita@example.com")
        self.assertEqual(key("  "), "")
