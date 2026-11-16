import gzip
import hashlib
import io
import uuid
import zipfile
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.apps import apps
from django.contrib.admin.models import LogEntry
from django.contrib.contenttypes.models import ContentType
from django.core import mail
from django.db.models import Sum
from django.db.models.deletion import ProtectedError
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.accounts.models import PasswordResetCode
from apps.customers.models import Customer, CustomerLedger
from apps.inventory.models import ShopProduct, StockMovement
from apps.orders.models import Order, OrderEvent, OrderItem
from apps.retention.models import ArchivedBill, BillArchive, DataArchive, RetentionLog, RetentionNotice
from apps.sales.models import Payment, Sale, SaleItem
from services import retention_service

from .helpers import API, add_listing, checkout, client_for, make_master, make_vendor
from .test_orders import register_shopper

POLICY = f"{API}/shop/retention/policy/"


def make_row(model, **known):
    """Creates a row of any model by filling the required columns with simple values (so the tests do not depend on
    the exact columns of notification or audit tables)."""
    data = dict(known)
    for f in model._meta.concrete_fields:
        if (f.primary_key or f.name in data or getattr(f, "auto_now_add", False) or getattr(f, "auto_now", False)
                or f.has_default() or f.null):
            continue
        kind = f.get_internal_type()
        if kind in ("CharField", "TextField", "SlugField"):
            data[f.name] = "test"
        elif kind == "BooleanField":
            data[f.name] = False
        elif "Integer" in kind:
            data[f.name] = 0
        elif kind == "DateTimeField":
            data[f.name] = timezone.now()
        elif kind == "DateField":
            data[f.name] = timezone.localdate()
        elif kind == "JSONField":
            data[f.name] = {}
        elif kind == "DecimalField":
            data[f.name] = Decimal("0")
        else:
            raise AssertionError(f"Fill {model.__name__}.{f.name} in the test helper")
    return model.objects.create(**data)


class Base(APITestCase):
    def setUp(self):
        self.now = timezone.now()
        self.owner, self.shop = make_vendor("rt_owner", "Retention Shop")
        self.owner.email = "owner@example.com"
        self.owner.save()
        self.c = client_for(self.owner, self.shop)
        self.sp = add_listing(self.c, make_master("Soap", barcode=None, pack="1"), price="100.00", cost="60.00", stock="500")["id"]

    def bill(self, age_days, qty="2", paid=True, customer=None, c=None, sp=None):
        """A bill that looks age_days old. Price is 100 a piece."""
        payments = [{"method": "cash", "amount": str(100 * int(qty))}] if paid else []
        kwargs = {"customer": customer} if customer else {}
        r = checkout(c or self.c, sp or self.sp, qty=qty, payments=payments, **kwargs)
        assert r.status_code in (200, 201), r.data
        Sale.objects.filter(pk=r.data["id"]).update(created_at=self.now - timedelta(days=age_days))
        return r.data["id"]

    def enable(self, c=None, months=12, days=14, **more):
        body = {"enabled": True, "keep_months": months, "notify_days": days, **more}
        r = (c or self.c).patch(POLICY, body, format="json")
        assert r.status_code == 200, r.data
        return r

    def cleanup(self, days=0, shop=None, **kw):
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

    def blocked_collector(self, model):
        """A stand-in for the database's delete planner that says a customer record would be deleted too."""
        fake = mock.MagicMock()
        fake.return_value.data = {model: [], Customer: []}
        fake.return_value.fast_deletes = []
        fake.return_value.field_updates = {}
        return fake


# ======================= bill details (unchanged behaviour) =======================
class PolicyTests(Base):
    def test_it_is_off_until_the_owner_switches_it_on(self):
        old = self.bill(400)
        self.assertEqual(self.cleanup()["outcome"], "off")
        self.assertEqual(self.cleanup(days=30)["outcome"], "off")
        self.assertEqual((self.items(old), RetentionLog.objects.count(), RetentionNotice.objects.count()), (1, 0, 0))

    def test_limits_and_who_may_change_it(self):
        self.assertEqual(self.c.patch(POLICY, {"keep_months": 5}, format="json").status_code, 400)           # bills: never below 6 months (shops without GST)
        self.assertEqual(self.c.patch(POLICY, {"keep_months": 6}, format="json").status_code, 200)
        self.assertEqual(self.c.patch(POLICY, {"notify_days": 3}, format="json").status_code, 400)           # at least a week of warning
        self.assertEqual(self.c.patch(POLICY, {"notification_days": 10}, format="json").status_code, 400)    # notifications: at least 30 days
        self.assertEqual(self.c.patch(POLICY, {"audit_months": 6}, format="json").status_code, 400)          # audit: at least 12 months
        self.assertEqual(self.c.patch(POLICY, {"orders_months": 3}, format="json").status_code, 400)         # orders: at least 6 months
        manager, _ = make_vendor("rt_mgr", role="manager", shop=self.shop)
        cashier, _ = make_vendor("rt_cash", role="cashier", shop=self.shop)
        self.assertEqual(client_for(manager, self.shop).get(POLICY).status_code, 200)
        self.assertEqual(client_for(manager, self.shop).patch(POLICY, {"enabled": True}, format="json").status_code, 403)
        self.assertEqual(client_for(cashier, self.shop).get(POLICY).status_code, 403)

    def test_the_preview_shows_what_the_next_cleanup_would_cover(self):
        self.bill(400)
        self.bill(10)
        self.c.patch(POLICY, {"keep_months": 12}, format="json")
        data = self.c.get(POLICY).data
        self.assertEqual((data["preview"]["bills"], data["preview"]["items"], data["minimum_months"]), (1, 1, 6))
        self.assertEqual(data["minimums"], {"bills_months": 6, "audit_months": 12, "orders_months": 6, "notification_days": 30})
        self.assertIn("archive", data["bills_note"])
        self.c.patch(POLICY, {"keep_months": 84}, format="json")
        self.assertEqual(self.c.get(POLICY).data["preview"]["bills"], 0)


class CleanupTests(Base):
    def test_warn_first_then_archive_after_the_notice_period(self):
        old, recent = self.bill(400), self.bill(10)
        self.enable()
        first = self.cleanup()
        self.assertEqual((first["outcome"], first["announced_bills"], first["bills_archived"]), ("announced", 1, 0))
        notice = RetentionNotice.objects.get()
        self.assertEqual((notice.category, notice.bills_count, notice.items_count, notice.status), ("bills", 1, 1, "announced"))
        self.assertEqual(notice.delete_after, timezone.localdate(self.now) + timedelta(days=14))
        self.assertEqual((len(mail.outbox), mail.outbox[0].to), (1, ["owner@example.com"]))
        self.assertIn("1 bills", mail.outbox[0].body)
        self.assertEqual(self.items(old), 1)                                           # nothing removed yet
        self.assertEqual(self.cleanup()["outcome"], "already_ran_today")                  # once a day
        self.assertEqual(RetentionLog.objects.count(), 1)
        self.assertEqual(self.cleanup(days=13)["outcome"], "nothing")                     # the notice period is not over
        self.assertEqual(self.items(old), 1)
        done = self.cleanup(days=14)
        self.assertEqual((done["outcome"], done["bills_archived"], done["items_deleted"]), ("archived", 1, 1))
        self.assertEqual((self.items(old), self.items(recent)), (0, 1))
        self.assertEqual(RetentionNotice.objects.get().status, "done")
        log = RetentionLog.objects.filter(outcome="archived").get()
        self.assertEqual((log.category, log.bills_archived, log.items_deleted), ("bills", 1, 1))

    def test_accounting_credit_customers_and_stock_are_not_touched(self):
        cust = self.c.post(f"{API}/shop/customers/", {"name": "Geeta", "phone": "9000000055"}, format="json").data["id"]
        paid_old = self.bill(400)
        credit_old = self.bill(400, qty="1", paid=False, customer=cust)             # still owes money
        self.assertGreater(Customer.objects.get(pk=cust).balance, 0)
        before = self.snapshot()
        credit_items = self.items(credit_old)
        self.enable()
        self.cleanup()
        self.cleanup(days=14)
        self.assertEqual(before, self.snapshot())                                     # every number is the same
        self.assertEqual((self.items(paid_old), self.items(credit_old)), (0, credit_items))   # the unpaid bill keeps its details
        sale = Sale.objects.get(pk=paid_old)                                          # the bill itself is still there
        self.assertEqual((sale.total, Payment.objects.filter(sale=sale).count()), (Decimal("200.00"), 1))

    def test_the_archive_is_complete_checked_and_protects_the_bill(self):
        old = self.bill(400, qty="3")
        self.enable()
        self.cleanup()
        self.cleanup(days=14)
        archive = BillArchive.objects.get()
        self.assertEqual((archive.bills_count, archive.items_count), (1, 1))
        self.assertEqual(hashlib.sha256(bytes(archive.data)).hexdigest(), archive.sha256)
        lines = gzip.decompress(bytes(archive.data)).decode().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertIn(Sale.objects.get(pk=old).invoice_number, lines[0])
        self.assertIn('"payments"', lines[0])
        self.assertTrue(ArchivedBill.objects.filter(sale_id=old).exists())
        with self.assertRaises(ProtectedError):
            Sale.objects.get(pk=old).delete()                                         # an archived bill can not be deleted by accident

    def test_if_anything_else_would_be_deleted_everything_is_cancelled(self):
        old = self.bill(400)
        self.enable()
        self.cleanup()
        with mock.patch("services.retention_service.Collector", self.blocked_collector(SaleItem)):
            result = self.cleanup(days=14)
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
        self.assertEqual(set(RetentionLog.objects.filter(shop__isnull=False).values_list("shop_id", flat=True)), {self.shop.id, c_shop.id})

    def test_bills_that_become_old_during_the_warning_get_a_warning_of_their_own(self):
        a, b = self.bill(400), self.bill(360)           # B is not old enough yet
        self.enable()
        self.cleanup()
        self.assertEqual(RetentionNotice.objects.get().bills_count, 1)
        self.cleanup(days=14)                               # A is archived. B is old by now, but was never warned about
        self.assertEqual((self.items(a), self.items(b)), (0, 1))
        notices = list(RetentionNotice.objects.order_by("id"))
        self.assertEqual([(n.status, n.bills_count) for n in notices], [("done", 1), ("announced", 1)])
        self.cleanup(days=28)
        self.assertEqual(self.items(b), 0)

    def test_postponing_and_switching_off(self):
        old = self.bill(400)
        self.enable()
        self.cleanup()
        nid = RetentionNotice.objects.get().id
        first = self.c.post(f"{API}/shop/retention/notices/{nid}/postpone/", {}, format="json")
        self.assertEqual((first.status_code, first.data["status"], first.data["postponed_count"]), (200, "postponed", 1))
        self.assertEqual(self.cleanup(days=14)["outcome"], "nothing")                      # the new date has not come
        self.assertEqual(self.items(old), 1)
        for _ in range(2):
            self.c.post(f"{API}/shop/retention/notices/{nid}/postpone/", {}, format="json")
        self.assertEqual(self.c.post(f"{API}/shop/retention/notices/{nid}/postpone/", {}, format="json").data["code"], "too_many_postponements")
        self.c.patch(POLICY, {"enabled": False}, format="json")                        # switching off cancels the warning
        self.assertEqual(RetentionNotice.objects.get().status, "cancelled")
        self.assertEqual(self.cleanup(days=200)["outcome"], "off")
        self.assertEqual(self.items(old), 1)

    def test_a_shop_that_now_keeps_bills_longer_is_respected(self):
        old = self.bill(400)
        self.enable(months=12)
        self.cleanup()
        self.enable(months=60)                          # the owner changes their mind during the warning
        self.cleanup(days=14)
        self.assertEqual(self.items(old), 1)


class ExportAndReportingTests(Base):
    def test_the_owner_can_email_the_bills_before_and_after_they_are_archived(self):
        old = self.bill(400)
        self.enable()
        self.cleanup()
        nid = RetentionNotice.objects.get().id
        mail.outbox.clear()
        sent = self.c.post(f"{API}/shop/retention/notices/{nid}/email-export/", {}, format="json")
        self.assertEqual((sent.status_code, sent.data["bills"], sent.data["to"]), (200, 1, "o***@example.com"))
        csv_text = zipfile.ZipFile(io.BytesIO(mail.outbox[0].attachments[0][1])).read("bills.csv").decode("utf-8-sig")
        self.assertIn(Sale.objects.get(pk=old).invoice_number, csv_text)
        self.assertIn("item_", csv_text.splitlines()[0])
        self.cleanup(days=14)
        archive_id = BillArchive.objects.get().id
        mail.outbox.clear()
        again = self.c.post(f"{API}/shop/retention/archives/{archive_id}/email/", {}, format="json")
        self.assertEqual((again.status_code, again.data["bills"]), (200, 1))
        self.assertEqual(len(mail.outbox[0].attachments), 1)

    def test_no_email_address_means_a_clear_message(self):
        self.bill(400)
        self.enable()
        self.cleanup()
        self.owner.email = ""
        self.owner.save()
        nid = RetentionNotice.objects.get().id
        r = self.c.post(f"{API}/shop/retention/notices/{nid}/email-export/", {}, format="json")
        self.assertEqual((r.status_code, r.data["code"]), (400, "no_email"))

    def test_the_log_and_notices_are_private_to_each_shop(self):
        self.bill(400)
        self.enable()
        self.cleanup()
        other_owner, other_shop = make_vendor("rt_other", "Other Shop")
        o = client_for(other_owner, other_shop)
        self.assertEqual(o.get(f"{API}/shop/retention/notices/").data["count"], 0)
        self.assertEqual(o.get(f"{API}/shop/retention/log/").data["count"], 0)
        mine = self.c.get(f"{API}/shop/retention/log/").data["results"][0]
        self.assertEqual((mine["category"], mine["outcome"], mine["announced_bills"]), ("bills", "announced", 1))

    def test_an_archived_bill_can_not_be_returned(self):
        old = self.bill(400)
        self.enable()
        self.cleanup()
        self.cleanup(days=14)
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
            self.assertEqual((ok.status_code, ok.data["results"][0]["outcome"], ok.data["results"][-1]["category"]), (200, "announced", "logs"))
            again = APIClient().post(url, HTTP_X_CRON_TOKEN="s3cret")
            self.assertEqual([r["outcome"] for r in again.data["results"]], ["already_ran_today", "already_ran_today"])


# ======================= 1. notifications =======================
class NotificationTests(Base):
    def setUp(self):
        super().setUp()
        self.model = apps.get_model("shops", "ShopNotification")
        self.field = retention_service._date_field(self.model, ("created_at", "created", "timestamp", "date"))
        if not self.field:
            self.skipTest("The notification table has no date column")

    def notif(self, age_days, shop=None):
        row = make_row(self.model, shop=shop or self.shop)
        self.model.objects.filter(pk=row.pk).update(**{self.field: self.now - timedelta(days=age_days)})
        return row.pk

    def left(self, shop=None):
        return set(self.model.objects.filter(shop=shop or self.shop).values_list("pk", flat=True))

    def test_old_notifications_are_deleted_with_no_warning_and_no_archive(self):
        old, older, recent = self.notif(100), self.notif(70), self.notif(10)
        self.enable()
        result = self.cleanup()
        self.assertEqual(self.left(), {recent})
        self.assertEqual(result["categories"]["notifications"]["deleted"], 2)
        self.assertEqual((len(mail.outbox), RetentionNotice.objects.count(), DataArchive.objects.count(), BillArchive.objects.count()), (0, 0, 0, 0))
        log = RetentionLog.objects.get(category="notifications")
        self.assertEqual((log.outcome, log.rows_deleted), ("cleaned", 2))

    def test_each_shop_has_its_own_number_of_days(self):
        b_owner, b_shop = make_vendor("rt_nb", "Notification Shop B")
        b = client_for(b_owner, b_shop)
        a_note, b_note = self.notif(45), self.notif(45, shop=b_shop)
        self.enable()                                                  # shop A: the default 60 days
        self.enable(c=b, notification_days=30)                         # shop B: 30 days
        self.cleanup()
        self.cleanup(shop=b_shop)
        self.assertEqual((self.left(), self.left(b_shop)), ({a_note}, set()))

    def test_it_can_be_switched_off_for_notifications_alone(self):
        old = self.notif(100)
        self.enable(clean_notifications=False)
        self.cleanup()
        self.assertEqual(self.left(), {old})

    def test_deleting_happens_in_small_batches(self):
        ids = [self.notif(100) for _ in range(7)]
        self.enable()
        with override_settings(RETENTION_BATCH_ROWS=2, RETENTION_MAX_ROWS_PER_RUN=4):
            self.cleanup()
            self.assertEqual(len(self.left()), 3)                      # only 4 were removed in the first run
            self.cleanup(days=1)
        self.assertEqual(self.left(), set())
        self.assertEqual(sorted(RetentionLog.objects.filter(category="notifications").values_list("rows_deleted", flat=True)), [3, 4])

    def test_if_anything_else_would_be_deleted_nothing_is_deleted(self):
        old = self.notif(100)
        self.enable()
        with mock.patch("services.retention_service.Collector", self.blocked_collector(self.model)):
            self.cleanup()
        self.assertEqual(self.left(), {old})
        self.assertEqual(RetentionLog.objects.get(category="notifications").outcome, "blocked")


# ======================= 2. logs =======================
class PlatformLogTests(Base):
    def test_old_logs_are_deleted_and_recent_ones_kept(self):
        old_code = PasswordResetCode.objects.create(user=self.owner, code_hash="x", expires_at=self.now)
        new_code = PasswordResetCode.objects.create(user=self.owner, code_hash="y", expires_at=self.now)
        PasswordResetCode.objects.filter(pk=old_code.pk).update(created_at=self.now - timedelta(days=40))
        ct = ContentType.objects.get_for_model(type(self.shop))
        for days in (100, 10):
            LogEntry.objects.create(user=self.owner, content_type=ct, object_id=str(self.shop.pk), object_repr="x",
                                    action_flag=1, change_message="", action_time=self.now - timedelta(days=days))
        result = retention_service.run_platform(now=self.now)
        self.assertEqual((result["outcome"], result["rows_deleted"]), ("cleaned", 2))
        self.assertEqual(set(PasswordResetCode.objects.values_list("pk", flat=True)), {new_code.pk})
        self.assertEqual(LogEntry.objects.count(), 1)
        log = RetentionLog.objects.get(shop__isnull=True, category="logs")
        self.assertIn("accounts.PasswordResetCode: 1", log.message)
        self.assertEqual(retention_service.run_platform(now=self.now)["outcome"], "already_ran_today")
        self.assertEqual(self.c.get(f"{API}/shop/retention/log/").data["count"], 0)    # platform rows are not shown to shops

    def test_a_table_that_does_not_exist_is_skipped_quietly(self):
        with override_settings(RETENTION_LOG_RULES=[("nothing.Missing", "created_at", 30)]):
            result = retention_service.run_platform(now=self.now)
        self.assertEqual(result["outcome"], "nothing")
        self.assertIn("skipped", RetentionLog.objects.get(category="logs").message)


# ======================= 3. audit log =======================
class AuditTests(Base):
    def setUp(self):
        super().setUp()
        try:
            self.model = apps.get_model("shops", "AuditLog")
        except LookupError:
            self.skipTest("The audit log is not installed in this project")

    def entry(self, age_days):
        row = make_row(self.model, shop=self.shop, action="price_changed", summary="Soap 100 -> 110")
        self.model.objects.filter(pk=row.pk).update(created_at=self.now - timedelta(days=age_days))
        return row.pk

    def test_warned_archived_then_deleted(self):
        old, recent = self.entry(400), self.entry(10)
        self.enable(clean_audit=True)
        self.cleanup()
        notice = RetentionNotice.objects.get(category="audit")
        self.assertEqual(notice.bills_count, 1)
        self.assertIn("change history", mail.outbox[-1].body)
        self.assertEqual(self.model.objects.count(), 2)                               # nothing removed yet
        self.cleanup(days=14)
        self.assertEqual(set(self.model.objects.values_list("pk", flat=True)), {recent})
        archive = DataArchive.objects.get(category="audit")
        self.assertEqual(archive.rows_count, 1)
        self.assertIn("price_changed", gzip.decompress(bytes(archive.data)).decode())
        log = RetentionLog.objects.get(category="audit", outcome="archived")
        self.assertEqual((log.rows_archived, log.rows_deleted), (1, 1))

    def test_it_is_off_unless_the_owner_chooses_it(self):
        old = self.entry(400)
        self.enable()                                    # the master switch only: audit cleanup stays off
        self.cleanup()
        self.cleanup(days=14)
        self.assertEqual(set(self.model.objects.values_list("pk", flat=True)), {old})
        self.assertEqual(RetentionNotice.objects.filter(category="audit").count(), 0)


# ======================= 4. finished online orders =======================
class OrderRetentionTests(Base):
    def setUp(self):
        super().setUp()
        self.c.patch(f"{API}/shop/store-settings/", {"store_enabled": True, "accepts_delivery": False, "accepts_pickup": True, "min_order": "0"}, format="json")
        self.s = register_shopper("Ret Cust", "9877700011")

    def place(self):
        r = self.s.post(f"{API}/store/orders/", {"shop": self.shop.id, "client_txn_id": str(uuid.uuid4()), "fulfilment": "pickup",
                                                "payment_method": "cash", "items": [{"shop_product": self.sp, "quantity": "1"}]}, format="json")
        assert r.status_code == 201, r.data
        return r.data["id"]

    def step(self, oid, action, **body):
        return self.c.post(f"{API}/shop/orders/{oid}/{action}/", body, format="json")

    def order(self, state, age_days=400):
        oid = self.place()
        if state == "completed":
            for a in ("accept", "pack", "ready"):
                self.step(oid, a)
            self.step(oid, "complete", payment_method="cash")
        elif state == "cancelled":
            self.s.post(f"{API}/store/orders/{oid}/cancel/")
        elif state == "rejected":
            self.step(oid, "reject", reason="closed today")
        elif state == "accepted":
            self.step(oid, "accept")
        elif state == "ready":
            for a in ("accept", "pack", "ready"):
                self.step(oid, a)
        Order.objects.filter(pk=oid).update(updated_at=self.now - timedelta(days=age_days))
        return oid

    def test_only_finished_orders_are_archived_and_removed(self):
        done, cancelled, rejected = self.order("completed"), self.order("cancelled"), self.order("rejected")
        placed, accepted, ready = self.order("placed"), self.order("accepted"), self.order("ready")
        recent = self.order("completed", age_days=10)
        before = self.snapshot()
        self.enable(clean_orders=True)
        self.cleanup()
        notice = RetentionNotice.objects.get(category="orders")
        self.assertEqual(notice.bills_count, 3)
        self.assertIn("online orders", mail.outbox[-1].subject)
        self.assertEqual(Order.objects.count(), 7)                                    # nothing removed yet
        self.cleanup(days=14)
        self.assertEqual(set(Order.objects.values_list("pk", flat=True)), {placed, accepted, ready, recent})
        self.assertEqual(OrderItem.objects.filter(order_id__in=[done, cancelled, rejected]).count(), 0)
        self.assertEqual(OrderEvent.objects.filter(order_id__in=[done, cancelled, rejected]).count(), 0)
        self.assertEqual(self.snapshot(), before)                                     # bills, customers, credit and stock are unchanged
        log = RetentionLog.objects.get(category="orders", outcome="archived")
        self.assertEqual((log.rows_archived, log.rows_deleted), (3, 3))
        self.assertEqual(RetentionNotice.objects.get(category="orders").status, "done")

    def test_the_archive_is_complete_and_never_holds_the_delivery_pin(self):
        done = self.order("completed")
        invoice = Sale.objects.get(pk=Order.objects.get(pk=done).sale_id).invoice_number
        self.enable(clean_orders=True)
        self.cleanup()
        self.cleanup(days=14)
        archive = DataArchive.objects.get(category="orders")
        self.assertEqual((archive.rows_count, archive.detail_count), (1, 1))
        self.assertEqual(hashlib.sha256(bytes(archive.data)).hexdigest(), archive.sha256)
        text = gzip.decompress(bytes(archive.data)).decode()
        self.assertIn(invoice, text)
        self.assertIn("customer_name", text)
        self.assertNotIn("delivery_pin", text)
        self.assertTrue(Sale.objects.filter(invoice_number=invoice).exists())          # the bill itself stays

    def test_an_order_on_hold_is_never_touched(self):
        held, other = self.order("completed"), self.order("completed")
        r = self.c.post(f"{API}/shop/orders/{held}/hold/", {"hold": True}, format="json")
        self.assertEqual((r.status_code, r.data["retention_hold"]), (200, True))
        self.enable(clean_orders=True)
        self.cleanup()
        self.cleanup(days=14)
        self.assertEqual(set(Order.objects.values_list("pk", flat=True)), {held})

    def test_an_order_linked_to_a_bill_with_money_owed_is_kept(self):
        oid = self.order("completed")
        Sale.objects.filter(pk=Order.objects.get(pk=oid).sale_id).update(amount_due=Decimal("50"))
        self.enable(clean_orders=True)
        self.cleanup()
        self.cleanup(days=14)
        self.assertEqual((Order.objects.filter(pk=oid).count(), RetentionNotice.objects.filter(category="orders").count()), (1, 0))

    def test_if_anything_else_would_be_deleted_everything_is_cancelled(self):
        oid = self.order("completed")
        self.enable(clean_orders=True)
        self.cleanup()
        with mock.patch("services.retention_service.Collector", self.blocked_collector(Order)):    # e.g. a rider payout record
            result = self.cleanup(days=14)
        self.assertEqual(result["categories"]["orders"]["outcome"], "blocked")
        self.assertEqual((Order.objects.filter(pk=oid).count(), DataArchive.objects.count()), (1, 0))
        self.assertEqual(RetentionNotice.objects.get(category="orders").status, "announced")

    def test_a_shop_that_now_keeps_orders_longer_is_respected(self):
        oid = self.order("completed")
        self.enable(clean_orders=True, orders_months=6)
        self.cleanup()
        self.enable(clean_orders=True, orders_months=60)
        self.cleanup(days=14)
        self.assertEqual(Order.objects.filter(pk=oid).count(), 1)

    def test_the_owner_can_email_the_orders_before_they_are_archived(self):
        self.order("completed")
        self.enable(clean_orders=True)
        self.cleanup()
        nid = RetentionNotice.objects.get(category="orders").id
        mail.outbox.clear()
        r = self.c.post(f"{API}/shop/retention/notices/{nid}/email-export/", {}, format="json")
        self.assertEqual((r.status_code, r.data["bills"]), (200, 1))
        header = zipfile.ZipFile(io.BytesIO(mail.outbox[0].attachments[0][1])).read("orders.csv").decode("utf-8-sig").splitlines()[0]
        self.assertIn("order_number", header)
        self.assertIn("item_product_name", header)
        self.cleanup(days=14)
        aid = DataArchive.objects.get(category="orders").id
        again = self.c.post(f"{API}/shop/retention/data-archives/{aid}/email/", {}, format="json")
        self.assertEqual((again.status_code, again.data["bills"]), (200, 1))