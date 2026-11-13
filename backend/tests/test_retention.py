import gzip
import hashlib
import io
import zipfile
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.core import mail
from django.db.models import Sum
from django.db.models.deletion import ProtectedError
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.customers.models import Customer, CustomerLedger
from apps.inventory.models import ShopProduct, StockMovement
from apps.retention.models import ArchivedBill, BillArchive, RetentionLog, RetentionNotice
from apps.sales.models import Payment, Sale, SaleItem
from services import retention_service

from .helpers import API, add_listing, checkout, client_for, make_master, make_vendor

POLICY = f"{API}/shop/retention/policy/"


class Base(APITestCase):
    def setUp(self):
        self.now = timezone.now()
        self.owner, self.shop = make_vendor("rt_owner", "Retention Shop")
        self.owner.email = "owner@example.com"
        self.owner.save()
        self.c = client_for(self.owner, self.shop)
        self.sp = add_listing(self.c, make_master("Soap", barcode=None, pack="1"), price="100.00", cost="60.00", stock="500")["id"]

    def bill(self, age_days, qty="2", paid=True, customer=None, c=None, sp=None, when=None):
        """A bill that looks age_days old. Price is 100 a piece."""
        payments = [{"method": "cash", "amount": str(100 * int(qty))}] if paid else []
        kwargs = {"customer": customer} if customer else {}
        r = checkout(c or self.c, sp or self.sp, qty=qty, payments=payments, **kwargs)
        assert r.status_code in (200, 201), r.data
        Sale.objects.filter(pk=r.data["id"]).update(created_at=(when or self.now) - timedelta(days=age_days))
        return r.data["id"]

    def enable(self, c=None, months=12, days=14):
        r = (c or self.c).patch(POLICY, {"enabled": True, "keep_months": months, "notify_days": days}, format="json")
        assert r.status_code == 200, r.data
        return r

    # NOTE: this used to be called `run`, which overrides unittest.TestCase.run()
    # (the method the test runner itself calls), so it must not be named `run`.
    def run_cleanup(self, days=0, shop=None, **kw):
        return retention_service.run_for_shop(shop or self.shop, now=self.now + timedelta(days=days), **kw)

    def items(self, sale_id):
        return SaleItem.objects.filter(sale_id=sale_id).count()

    def snapshot(self):
        return {
            "sales": Sale.objects.count(), "payments": Payment.objects.count(), "customers": Customer.objects.count(),
            "ledger": CustomerLedger.objects.count(), "products": ShopProduct.objects.count(), "movements": StockMovement.objects.count(),
            "total": Sale.objects.aggregate(t=Sum("total"))["t"], "paid": Payment.objects.aggregate(t=Sum("amount"))["t"],
            "stock": list(ShopProduct.objects.order_by("id").values_list("stock_qty", flat=True)),
            "balances": list(Customer.objects.order_by("id").values_list("balance", flat=True)),
        }


class PolicyTests(Base):
    def test_it_is_off_until_the_owner_switches_it_on(self):
        old = self.bill(400)
        self.assertEqual(self.run_cleanup()["outcome"], "off")
        self.assertEqual(self.run_cleanup(days=30)["outcome"], "off")
        self.assertEqual((self.items(old), RetentionLog.objects.count(), RetentionNotice.objects.count()), (1, 0, 0))

    def test_limits_and_who_may_change_it(self):
        self.assertEqual(self.c.patch(POLICY, {"keep_months": 6}, format="json").status_code, 400)     # never below 12 months
        self.assertEqual(self.c.patch(POLICY, {"notify_days": 3}, format="json").status_code, 400)     # at least a week of warning
        manager, _ = make_vendor("rt_mgr", role="manager", shop=self.shop)
        cashier, _ = make_vendor("rt_cash", role="cashier", shop=self.shop)
        self.assertEqual(client_for(manager, self.shop).get(POLICY).status_code, 200)
        self.assertEqual(client_for(manager, self.shop).patch(POLICY, {"enabled": True}, format="json").status_code, 403)
        self.assertEqual(client_for(cashier, self.shop).get(POLICY).status_code, 403)

    def test_the_preview_shows_what_the_next_cleanup_would_cover(self):
        self.bill(400)
        self.bill(10)
        data = self.c.get(POLICY).data
        self.assertEqual((data["preview"]["bills"], data["preview"]["items"], data["minimum_months"]), (1, 1, 12))


class CleanupTests(Base):
    def test_warn_first_then_archive_after_the_notice_period(self):
        old, recent = self.bill(400), self.bill(10)
        self.enable()
        first = self.run_cleanup()
        self.assertEqual((first["outcome"], first["announced_bills"], first["bills_archived"]), ("announced", 1, 0))
        notice = RetentionNotice.objects.get()
        self.assertEqual((notice.bills_count, notice.items_count, notice.status), (1, 1, "announced"))
        self.assertEqual(notice.delete_after, timezone.localdate(self.now) + timedelta(days=14))
        self.assertEqual((len(mail.outbox), mail.outbox[0].to), (1, ["owner@example.com"]))
        self.assertIn("1 bills", mail.outbox[0].body)
        self.assertEqual(self.items(old), 1)                                           # nothing removed yet
        self.assertEqual(self.run_cleanup()["outcome"], "already_ran_today")           # once a day
        self.assertEqual(RetentionLog.objects.count(), 1)
        self.assertEqual(self.run_cleanup(days=13)["outcome"], "nothing")              # the notice period is not over
        self.assertEqual(self.items(old), 1)
        done = self.run_cleanup(days=14)
        self.assertEqual((done["outcome"], done["bills_archived"], done["items_deleted"]), ("archived", 1, 1))
        self.assertEqual((self.items(old), self.items(recent)), (0, 1))
        self.assertEqual(RetentionNotice.objects.get().status, "done")
        log = RetentionLog.objects.filter(outcome="archived").get()
        self.assertEqual((log.bills_archived, log.items_deleted), (1, 1))

    def test_accounting_credit_customers_and_stock_are_not_touched(self):
        cust = self.c.post(f"{API}/shop/customers/", {"name": "Geeta", "phone": "9000000055"}, format="json").data["id"]
        paid_old = self.bill(400)
        credit_old = self.bill(400, qty="1", paid=False, customer=cust)             # still owes money
        self.assertGreater(Customer.objects.get(pk=cust).balance, 0)
        before = self.snapshot()
        credit_items = self.items(credit_old)
        self.enable()
        self.run_cleanup()
        self.run_cleanup(days=14)
        after = self.snapshot()
        self.assertEqual(before, after)                                               # every number is the same
        self.assertEqual((self.items(paid_old), self.items(credit_old)), (0, credit_items))   # the unpaid bill keeps its details
        sale = Sale.objects.get(pk=paid_old)                                          # the bill itself is still there
        self.assertEqual((sale.total, Payment.objects.filter(sale=sale).count()), (Decimal("200.00"), 1))

    def test_the_archive_is_complete_checked_and_protects_the_bill(self):
        old = self.bill(400, qty="3")
        self.enable()
        self.run_cleanup()
        self.run_cleanup(days=14)
        archive = BillArchive.objects.get()
        self.assertEqual((archive.bills_count, archive.items_count), (1, 1))
        self.assertEqual(hashlib.sha256(bytes(archive.data)).hexdigest(), archive.sha256)
        lines = gzip.decompress(bytes(archive.data)).decode().splitlines()
        self.assertEqual(len(lines), 1)
        text = lines[0]
        self.assertIn(Sale.objects.get(pk=old).invoice_number, text)
        self.assertIn('"payments"', text)
        self.assertTrue(ArchivedBill.objects.filter(sale_id=old).exists())
        with self.assertRaises(ProtectedError):
            Sale.objects.get(pk=old).delete()                                         # an archived bill can not be deleted by accident

    def test_if_anything_else_would_be_deleted_everything_is_cancelled(self):
        old = self.bill(400)
        self.enable()
        self.run_cleanup()
        fake = mock.MagicMock()
        fake.return_value.data = {SaleItem: [], Customer: []}                         # pretend a cascade would reach customers
        fake.return_value.fast_deletes = []
        fake.return_value.field_updates = {}
        with mock.patch("services.retention_service.Collector", fake):
            result = self.run_cleanup(days=14)
        self.assertEqual(result["outcome"], "blocked")
        self.assertEqual((self.items(old), BillArchive.objects.count(), ArchivedBill.objects.count()), (1, 0, 0))
        self.assertEqual(RetentionNotice.objects.get().status, "announced")
        self.assertIn("Customer", RetentionLog.objects.get(outcome="blocked").message)

    def test_each_shop_follows_its_own_settings(self):
        b_owner, b_shop = make_vendor("rt_b", "Shop B")
        b = client_for(b_owner, b_shop)
        b_sp = add_listing(b, make_master("Soap B", barcode=None, pack="1"), price="100.00", cost="60.00", stock="500")["id"]
        c_owner, c_shop = make_vendor("rt_c", "Shop C")
        cc = client_for(c_owner, c_shop)
        c_sp = add_listing(cc, make_master("Soap C", barcode=None, pack="1"), price="100.00", cost="60.00", stock="500")["id"]
        a_old = self.bill(400)
        b_old = self.bill(400, c=b, sp=b_sp)
        c_old = self.bill(400, c=cc, sp=c_sp)
        self.enable(months=12)                          # shop A: 12 months
        self.enable(c=cc, months=60)                    # shop C: 5 years. Shop B never switched it on.
        retention_service.run_all(now=self.now)
        retention_service.run_all(now=self.now + timedelta(days=14))
        self.assertEqual((self.items(a_old), self.items(b_old), self.items(c_old)), (0, 1, 1))
        self.assertEqual(set(RetentionLog.objects.values_list("shop_id", flat=True)), {self.shop.id, c_shop.id})

    def test_bills_that_become_old_during_the_warning_get_a_warning_of_their_own(self):
        a, b = self.bill(400), self.bill(360)           # B is not old enough yet
        self.enable()
        self.run_cleanup()
        self.assertEqual(RetentionNotice.objects.get().bills_count, 1)
        self.run_cleanup(days=14)                       # A is archived. B is old by now, but was never warned about
        self.assertEqual((self.items(a), self.items(b)), (0, 1))
        notices = list(RetentionNotice.objects.order_by("id"))
        self.assertEqual([(n.status, n.bills_count) for n in notices], [("done", 1), ("announced", 1)])
        self.run_cleanup(days=28)
        self.assertEqual(self.items(b), 0)

    def test_postponing_and_switching_off(self):
        old = self.bill(400)
        self.enable()
        self.run_cleanup()
        nid = RetentionNotice.objects.get().id
        first = self.c.post(f"{API}/shop/retention/notices/{nid}/postpone/", {}, format="json")
        self.assertEqual((first.status_code, first.data["status"], first.data["postponed_count"]), (200, "postponed", 1))
        self.assertEqual(self.run_cleanup(days=14)["outcome"], "nothing")              # the new date has not come
        self.assertEqual(self.items(old), 1)
        for _ in range(2):
            self.c.post(f"{API}/shop/retention/notices/{nid}/postpone/", {}, format="json")
        self.assertEqual(self.c.post(f"{API}/shop/retention/notices/{nid}/postpone/", {}, format="json").data["code"], "too_many_postponements")
        self.c.patch(POLICY, {"enabled": False}, format="json")                        # switching off cancels the warning
        self.assertEqual(RetentionNotice.objects.get().status, "cancelled")
        self.assertEqual(self.run_cleanup(days=200)["outcome"], "off")
        self.assertEqual(self.items(old), 1)

    def test_a_shop_that_now_keeps_bills_longer_is_respected(self):
        old = self.bill(400)
        self.enable(months=12)
        self.run_cleanup()
        self.enable(months=60)                          # the owner changes their mind during the warning
        self.run_cleanup(days=14)
        self.assertEqual(self.items(old), 1)


class ExportAndReportingTests(Base):
    def test_the_owner_can_email_the_bills_before_and_after_they_are_archived(self):
        old = self.bill(400)
        self.enable()
        self.run_cleanup()
        nid = RetentionNotice.objects.get().id
        mail.outbox.clear()
        sent = self.c.post(f"{API}/shop/retention/notices/{nid}/email-export/", {}, format="json")
        self.assertEqual((sent.status_code, sent.data["bills"], sent.data["to"]), (200, 1, "o***@example.com"))
        attachment = mail.outbox[0].attachments[0]
        csv_text = zipfile.ZipFile(io.BytesIO(attachment[1])).read("bills.csv").decode("utf-8-sig")
        self.assertIn(Sale.objects.get(pk=old).invoice_number, csv_text)
        self.assertIn("item_", csv_text.splitlines()[0])
        self.run_cleanup(days=14)
        archive_id = BillArchive.objects.get().id
        mail.outbox.clear()
        again = self.c.post(f"{API}/shop/retention/archives/{archive_id}/email/", {}, format="json")
        self.assertEqual((again.status_code, again.data["bills"]), (200, 1))
        self.assertEqual(len(mail.outbox[0].attachments), 1)

    def test_no_email_address_means_a_clear_message(self):
        self.bill(400)
        self.enable()
        self.run_cleanup()
        self.owner.email = ""
        self.owner.save()
        nid = RetentionNotice.objects.get().id
        r = self.c.post(f"{API}/shop/retention/notices/{nid}/email-export/", {}, format="json")
        self.assertEqual((r.status_code, r.data["code"]), (400, "no_email"))

    def test_the_log_and_notices_are_private_to_each_shop(self):
        self.bill(400)
        self.enable()
        self.run_cleanup()
        other_owner, other_shop = make_vendor("rt_other", "Other Shop")
        o = client_for(other_owner, other_shop)
        self.assertEqual(o.get(f"{API}/shop/retention/notices/").data["count"], 0)
        self.assertEqual(o.get(f"{API}/shop/retention/log/").data["count"], 0)
        mine = self.c.get(f"{API}/shop/retention/log/").data["results"][0]
        self.assertEqual((mine["outcome"], mine["announced_bills"]), ("announced", 1))

    def test_an_archived_bill_can_not_be_returned(self):
        old = self.bill(400)
        self.enable()
        self.run_cleanup()
        self.run_cleanup(days=14)
        r = self.c.post(f"{API}/shop/sales/{old}/return/", {"items": [{"sale_item": 1, "quantity": "1"}]}, format="json")
        self.assertEqual((r.status_code, r.data.get("code")), (400, "archived_bill"))


class SchedulerTests(Base):
    def test_the_daily_call_needs_the_secret_and_runs_once_a_day(self):
        self.bill(400)
        self.enable()
        url = f"{API}/internal/retention/run/"
        self.assertEqual(APIClient().post(url).status_code, 404)                       # no secret set on the server
        with override_settings(RETENTION_CRON_TOKEN="s3cret"):
            self.assertEqual(APIClient().post(url).status_code, 404)
            self.assertEqual(APIClient().post(url, HTTP_X_CRON_TOKEN="wrong").status_code, 404)
            ok = APIClient().post(url, HTTP_X_CRON_TOKEN="s3cret")
            self.assertEqual((ok.status_code, ok.data["results"][0]["outcome"]), (200, "announced"))
            again = APIClient().post(url, HTTP_X_CRON_TOKEN="s3cret")
            self.assertEqual(again.data["results"][0]["outcome"], "already_ran_today")