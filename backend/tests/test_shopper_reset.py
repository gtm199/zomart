import re

from django.core import mail
from rest_framework.test import APIClient, APITestCase

from apps.orders.models import ShopperPasswordResetCode

from .helpers import API


class ShopperPasswordResetTests(APITestCase):
    def setUp(self):
        r = APIClient().post(f"{API}/store/auth/register/", {"name": "Asha", "phone": "9876500001",
                             "password": "secret123", "email": "Asha@Example.com"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.token = r.data["token"]

    def authed(self):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION="Shopper " + self.token)
        return c

    def code(self):
        return re.search(r"\b(\d{6})\b", mail.outbox[-1].body).group(1)

    def test_full_reset_flow_signs_out_everywhere(self):
        c = APIClient()
        self.assertEqual(c.post(f"{API}/store/auth/forgot-password/", {"email": "asha@EXAMPLE.com"}, format="json").status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        r = c.post(f"{API}/store/auth/reset-password/",
                   {"email": "asha@example.com", "code": self.code(), "new_password": "newpass99"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(c.post(f"{API}/store/auth/login/", {"phone": "9876500001", "password": "newpass99"}, format="json").status_code, 200)
        self.assertEqual(self.authed().get(f"{API}/store/auth/me/").status_code, 401)

    def test_unknown_email_sends_nothing_and_wrong_code_is_refused(self):
        c = APIClient()
        self.assertEqual(c.post(f"{API}/store/auth/forgot-password/", {"email": "nobody@x.com"}, format="json").status_code, 200)
        self.assertEqual(len(mail.outbox), 0)
        c.post(f"{API}/store/auth/forgot-password/", {"email": "asha@example.com"}, format="json")
        wrong = "000000" if self.code() != "000000" else "111111"
        r = c.post(f"{API}/store/auth/reset-password/", {"email": "asha@example.com", "code": wrong, "new_password": "newpass99"}, format="json")
        self.assertEqual(r.data["code"], "invalid_code")
        self.assertEqual(ShopperPasswordResetCode.objects.get().attempts, 1)

    def test_profile_email_change_needs_current_password(self):
        c = self.authed()
        self.assertEqual(c.patch(f"{API}/store/auth/profile/", {"email": "new@x.com"}, format="json").status_code, 400)
        r = c.patch(f"{API}/store/auth/profile/", {"email": "New@X.com", "current_password": "secret123"}, format="json")
        self.assertEqual(r.data["email"], "new@x.com")
