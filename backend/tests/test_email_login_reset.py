import re
from datetime import timedelta

from django.core import mail
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient, APITestCase

from apps.accounts.models import PasswordResetCode, User

from .helpers import API


class EmailLoginTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user("owner1", email="Owner@Example.com", password="Old#12345")

    def login(self, who, password="Old#12345"):
        return APIClient().post(f"{API}/auth/login/", {"username": who, "password": password}, format="json")

    def test_username_or_email_in_any_letter_case(self):
        for who in ("owner1", "OWNER1", "owner@example.com", "Owner@EXAMPLE.com"):
            self.assertEqual(self.login(who).status_code, 200, who)

    def test_wrong_password_or_unknown_email_is_refused(self):
        self.assertEqual(self.login("owner@example.com", "wrong").status_code, 400)
        self.assertEqual(self.login("nobody@example.com").status_code, 400)

    def test_registration_with_email_and_duplicates(self):
        body = {"username": "newshop", "password": "Str0ngPass!42", "shop_name": "New Shop", "email": "New@Shop.com"}
        self.assertEqual(APIClient().post(f"{API}/auth/register-vendor/", body, format="json").status_code, 201)
        self.assertEqual(self.login("new@shop.com", "Str0ngPass!42").status_code, 200)
        again = dict(body, username="other", email="NEW@shop.com")
        self.assertEqual(APIClient().post(f"{API}/auth/register-vendor/", again, format="json").status_code, 400)

    def test_profile_email_change_needs_the_current_password(self):
        tok = Token.objects.create(user=self.user)
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION="Token " + tok.key)
        url = f"{API}/auth/profile/"
        self.assertEqual(c.patch(url, {"email": "mine@example.com"}, format="json").status_code, 400)
        self.assertEqual(c.patch(url, {"email": "mine@example.com", "current_password": "wrong"}, format="json").status_code, 400)
        self.assertEqual(c.patch(url, {"email": "mine@example.com", "current_password": "Old#12345"}, format="json").status_code, 200)
        self.assertEqual(self.login("mine@example.com").status_code, 200)
        User.objects.create_user("second", email="taken@example.com", password="x")
        self.assertEqual(c.patch(url, {"email": "TAKEN@example.com", "current_password": "Old#12345"}, format="json").status_code, 400)


class ResetByEmailTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user("owner2", email="owner2@example.com", password="Old#12345")
        self.c = APIClient()

    def ask(self, email="owner2@example.com"):
        return self.c.post(f"{API}/auth/forgot-password/", {"email": email}, format="json")

    def code(self, n=-1):
        return re.search(r"\b(\d{6})\b", mail.outbox[n].body).group(1)

    def reset(self, code, password="Brand#New5678", email="owner2@example.com"):
        return self.c.post(f"{API}/auth/reset-password/", {"email": email, "code": code, "new_password": password}, format="json")

    def test_unknown_email_gets_the_same_answer_and_no_mail(self):
        a, b = self.ask("nobody@example.com"), self.ask()
        self.assertEqual((a.status_code, b.status_code), (200, 200))
        self.assertEqual(a.data, b.data)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["owner2@example.com"])

    def test_good_code_resets_the_password_and_signs_old_phones_out(self):
        tok = Token.objects.create(user=self.user)
        self.ask()
        self.assertEqual(self.reset(self.code()).status_code, 200)
        self.assertFalse(Token.objects.filter(key=tok.key).exists())
        ok = self.c.post(f"{API}/auth/login/", {"username": "owner2@example.com", "password": "Brand#New5678"}, format="json")
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(self.reset(self.code(), "Another#98765").status_code, 400)  # a code works once

    def test_wrong_codes_burn_the_code(self):
        self.ask()
        good = self.code()
        wrong = "000000" if good != "000000" else "111111"
        for _ in range(5):
            self.assertEqual(self.reset(wrong).status_code, 400)
        self.assertEqual(self.reset(good).status_code, 400)

    def test_expired_code_and_weak_password(self):
        self.ask()
        good = self.code()
        weak = self.reset(good, "123")
        self.assertEqual(weak.status_code, 400)
        self.assertEqual(self.reset(good).status_code, 200)  # the code was not used up by the weak password
        self.ask()
        PasswordResetCode.objects.filter(used_at__isnull=True).update(expires_at=timezone.now() - timedelta(minutes=1))
        self.assertEqual(self.reset(self.code(), "Third#Pass4321").status_code, 400)

    def test_only_three_codes_an_hour_and_a_new_code_replaces_the_old(self):
        for _ in range(5):
            self.ask()
        self.assertEqual(len(mail.outbox), 3)
        self.assertEqual(self.reset(self.code(0)).status_code, 400)  # the first code was replaced
        self.assertEqual(self.reset(self.code(2)).status_code, 200)

    def test_reset_clears_the_must_change_flag(self):
        self.user.must_change_password = True
        self.user.save()
        self.ask()
        self.reset(self.code())
        self.user.refresh_from_db()
        self.assertFalse(self.user.must_change_password)