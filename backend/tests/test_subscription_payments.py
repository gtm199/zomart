from datetime import timedelta
from decimal import Decimal

from django.test import override_settings
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient, APITestCase

from apps.accounts.models import User
from apps.shops.models import Shop
from apps.subscriptions.models import BankCredit, ShopSubscription, SubscriptionPlan
from services import payment_service as pay
from services import subscription_service as subs
from services.exceptions import BusinessRuleError

from .helpers import API, client_for, make_vendor

HEADER = ["Date", "Narration", "Chq./Ref.No.", "Value Dt", "Withdrawal Amt.", "Deposit Amt.", "Closing Balance"]


def statement(*credits):
    """credits: (date, narration, reference, amount). Includes the account details banks put above the header."""
    rows = [["Account Statement"], ["Customer: TEST"], [], HEADER]
    for d, narration, ref, amount in credits:
        rows.append([d, narration, ref, d, "", f"{amount}", "1,000.00"])
    rows.append(["02/10/2026", "ATM WITHDRAWAL", "999", "02/10/2026", "500.00", "", "500.00"])
    return rows


def run(rows, user=None, apply=True):
    header = pay.find_header(rows)
    credits = pay.parse_credits(rows, header, pay.guess_columns(rows[header]))
    return pay.process(credits, user, apply=apply)


class StatementMatchingTests(APITestCase):
    def setUp(self):
        subs.seed_default_plans()
        self.standard = SubscriptionPlan.objects.get(code="standard")      # 499 per month
        self.premium = SubscriptionPlan.objects.get(code="premium")        # 999 per month
        self.user, self.shop = make_vendor("payer", "Pay Shop")
        subs.ensure_payment_identity(self.shop)
        self.shop.refresh_from_db()
        self.sub = ShopSubscription.objects.get(shop=self.shop)
        self.exact = subs.amount_for(self.standard, 1, self.shop)

    def test_columns_are_found_even_with_account_details_above_the_header(self):
        rows = statement(("01/10/2026", "UPI", "123456789012", "499.07"))
        header = pay.find_header(rows)
        self.assertEqual(header, 3)
        cols = pay.guess_columns(rows[header])
        self.assertEqual((cols["date"], cols["narration"], cols["reference"], cols["credit"]), (0, 1, 2, 5))
        credits = pay.parse_credits(rows, header, cols)
        self.assertEqual(len(credits), 1)  # the withdrawal row is skipped
        self.assertEqual(credits[0]["amount"], Decimal("499.07"))

    def test_payment_with_shop_code_and_exact_amount_renews(self):
        before = self.sub.expires_on
        rows = statement(("01/10/2026", f"UPI-RAJU-{self.shop.payment_code}-PAYMENT", "123456789012", self.exact))
        out = run(rows)
        self.assertEqual(out[0]["outcome"], "renew")
        current = subs.current_subscription(self.shop)
        self.assertEqual(current.expires_on, max(timezone.localdate(), before) + timedelta(days=30))
        self.assertEqual((current.plan, current.status), (self.standard, "active"))
        credit = BankCredit.objects.get()
        self.assertEqual((credit.status, credit.matched_by, credit.months), ("renewed", "code", 1))

    def test_unique_amount_alone_identifies_the_shop(self):
        out = run(statement(("01/10/2026", "UPI-SOMEONE-no note", "223456789012", self.exact)))
        self.assertEqual((out[0]["outcome"], out[0]["how"]), ("renew", "amount"))

    def test_wrong_amount_with_code_goes_to_review_and_nothing_renews(self):
        before = ShopSubscription.objects.get(shop=self.shop).expires_on
        out = run(statement(("01/10/2026", f"UPI-{self.shop.payment_code}", "323456789012", "499.00")))
        self.assertEqual(out[0]["outcome"], "review")
        self.assertEqual(ShopSubscription.objects.get(shop=self.shop).expires_on, before)
        credit = BankCredit.objects.get()
        self.assertEqual((credit.status, credit.shop_id), ("needs_review", self.shop.id))

    def test_unknown_payment_goes_to_review(self):
        out = run(statement(("01/10/2026", "SALARY CREDIT", "423456789012", "25000.00")))
        self.assertEqual(out[0]["outcome"], "review")
        self.assertIsNone(BankCredit.objects.get().shop)

    def test_same_reference_can_never_renew_twice(self):
        rows = statement(("01/10/2026", f"UPI-{self.shop.payment_code}", "523456789012", self.exact))
        run(rows)
        expiry = subs.current_subscription(self.shop).expires_on
        again = run(rows)
        self.assertEqual(again[0]["outcome"], "seen")
        self.assertEqual(subs.current_subscription(self.shop).expires_on, expiry)
        self.assertEqual(BankCredit.objects.count(), 1)

    def test_preview_changes_nothing(self):
        out = run(statement(("01/10/2026", f"UPI-{self.shop.payment_code}", "623456789012", self.exact)), apply=False)
        self.assertEqual(out[0]["outcome"], "renew")
        self.assertEqual(BankCredit.objects.count(), 0)

    def test_three_months_and_plan_change_by_amount(self):
        three = subs.amount_for(self.standard, 3, self.shop)
        out = run(statement(("01/10/2026", f"{self.shop.payment_code}", "723456789012", three)))
        self.assertEqual(out[0]["months"], 3)
        premium = subs.amount_for(self.premium, 1, self.shop)
        run(statement(("02/10/2026", f"{self.shop.payment_code}", "823456789012", premium)))
        current = subs.current_subscription(self.shop)
        self.assertEqual((current.plan, current.status), (self.premium, "active"))
        self.assertTrue(ShopSubscription.objects.filter(shop=self.shop, status="cancelled").exists())

    def test_manual_confirmation(self):
        run(statement(("01/10/2026", "SOME ONE", "923456789012", "499.00")))
        credit = BankCredit.objects.get()
        with self.assertRaises(BusinessRuleError):
            pay.confirm_manually(credit, self.user)  # no shop chosen yet
        credit.shop, credit.months = self.shop, 2
        credit.save()
        pay.confirm_manually(credit, self.user)
        credit.refresh_from_db()
        self.assertEqual((credit.status, credit.matched_by), ("renewed", "manual"))
        with self.assertRaises(BusinessRuleError):
            pay.confirm_manually(credit, self.user)  # already handled

    def test_each_shop_gets_its_own_code_and_paise(self):
        other = Shop.objects.create(name="Second")
        subs.ensure_payment_identity(other)
        self.assertNotEqual(other.payment_code, self.shop.payment_code)
        self.assertNotEqual(other.pay_paise, self.shop.pay_paise)


class PlanScreenAndApprovalTests(APITestCase):
    def test_subscription_endpoint_shows_what_to_pay(self):
        subs.seed_default_plans()
        user, shop = make_vendor("planuser", "Plan Shop")
        data = client_for(user, shop).get(f"{API}/shop/subscription/").data
        shop.refresh_from_db()
        self.assertEqual(data["payment"]["shop_code"], shop.payment_code)
        standard = next(p for p in data["plans"] if p["name"] == "Standard")
        self.assertEqual(Decimal(standard["options"][0]["amount"]), Decimal("499") + Decimal(shop.pay_paise) / 100)
        self.assertEqual(data["days_left"], 30)
        self.assertEqual(standard["options"][3]["months"], 12)

    @override_settings(NEW_SHOPS_NEED_APPROVAL=True)
    def test_new_shop_waits_for_approval_without_starting_its_trial(self):
        c = APIClient()
        r = c.post(f"{API}/auth/register-vendor/", {"username": "newowner", "password": "Str0ngPass!42",
                   "shop_name": "Waiting Shop"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertFalse(r.data["shops"][0]["approved"])
        shop = Shop.objects.get(name="Waiting Shop")
        self.assertIsNone(subs.current_subscription(shop))
        auth = APIClient()
        auth.credentials(HTTP_AUTHORIZATION="Token " + r.data["token"], HTTP_X_SHOP_ID=str(shop.id))
        self.assertEqual(auth.get(f"{API}/shop/products/").status_code, 403)
        subs.approve_shop(shop)
        self.assertEqual(auth.get(f"{API}/shop/products/").status_code, 200)
        self.assertEqual(subs.days_left(subs.current_subscription(shop)), 30)

    def test_owner_manages_staff_and_can_reset_a_password(self):
        subs.seed_default_plans()
        owner, shop = make_vendor("staff_owner", "Staff Shop")
        c = client_for(owner, shop)
        r = c.post(f"{API}/shop/members/", {"username": "9000000077", "password": "Cashier#1234", "full_name": "Ravi",
                   "phone": "9000000077", "role": "cashier"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        member_id = r.data["id"]
        staff_user = User.objects.get(username="9000000077")
        Token.objects.create(user=staff_user)
        self.assertEqual(c.patch(f"{API}/shop/members/{member_id}/", {"is_active": False}, format="json").status_code, 200)
        self.assertEqual(client_for(staff_user, shop).get(f"{API}/shop/products/").status_code, 403)  # switched off at once
        bad = c.post(f"{API}/shop/members/{member_id}/set-password/", {"password": "123"}, format="json")
        self.assertEqual(bad.status_code, 400)
        ok = c.post(f"{API}/shop/members/{member_id}/set-password/", {"password": "BrandNew#5678"}, format="json")
        self.assertEqual(ok.status_code, 200)
        self.assertFalse(Token.objects.filter(user=staff_user).exists())  # signed out everywhere
        cashier, _ = make_vendor("staff_cashier", role="cashier", shop=shop)
        self.assertEqual(client_for(cashier, shop).get(f"{API}/shop/members/").status_code, 403)  # staff cannot manage staff