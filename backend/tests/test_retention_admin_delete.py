"""Permanent deletes in the retention area: platform superuser only, from the Django admin, with safety rules.
Bills themselves are never deleted; bills inside the minimum period (GST: 72 months) are never touched."""
from datetime import timedelta
from unittest import mock

from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.retention.models import ArchivedBill, BillArchive, DataArchive, RetentionLog, RetentionNotice, RetentionPolicy
from apps.sales.models import Sale, SaleItem
from services import retention_admin_service, retention_service
from services.exceptions import BusinessRuleError

from .test_retention import POLICY, Base


class AdminDeleteBase(Base):
    def setUp(self):
        super().setUp()
        self.root = User.objects.create_superuser("platform", password="Admin#Pass1")
        self.staff = User.objects.create_user("support", password="Support#Pass1", is_staff=True)

    def archive_bills(self, *ages):
        ids = [self.bill(age) for age in ages]
        self.enable(months=6)
        self.cleanup()
        self.cleanup(days=14)
        return ids, BillArchive.objects.get()

    def admin(self, user=None):
        c = APIClient()
        c.force_login(user or self.root)
        return c

    def run_action(self, model_url, ids, word="DELETE", user=None):
        c = self.admin(user)
        first = c.post(f"/admin/retention/{model_url}/", {"action": "delete_permanently", "_selected_action": ids})
        second = c.post(f"/admin/retention/{model_url}/", {"action": "delete_permanently", "_selected_action": ids,
                                                           "apply": "1", "confirm_word": word}, follow=True)
        return first, second


class BillArchiveDeleteTests(AdminDeleteBase):
    def test_superuser_deletes_archive_and_bills_stay(self):
        (old,), archive = self.archive_bills(250)
        sale_before = Sale.objects.values("invoice_number", "total", "amount_paid").get(pk=old)
        first, second = self.run_action("billarchive", [archive.pk])
        self.assertContains(first, "Type <strong>DELETE</strong>")       # confirmation page first
        self.assertContains(first, "ONLY copy")
        self.assertContains(second, "Deleted 1")
        self.assertFalse(BillArchive.objects.exists())
        marker = ArchivedBill.objects.get(sale_id=old)                  # the bill stays marked as archived
        self.assertIsNone(marker.archive)
        self.assertIsNotNone(marker.archive_deleted_at)
        self.assertEqual(Sale.objects.values("invoice_number", "total", "amount_paid").get(pk=old), sale_before)
        self.assertTrue(RetentionLog.objects.filter(outcome="admin_deleted", message__contains="platform").exists())
        # the daily cleanup does not archive the same bill again, and it still cannot be returned
        self.assertEqual(self.cleanup(days=40)["bills_archived"], 0)
        self.assertEqual(BillArchive.objects.count(), 0)
        self.assertEqual(self.c.get(f"{POLICY}").data["archived_bills"], 1)

    def test_wrong_word_or_not_superuser_deletes_nothing(self):
        _, archive = self.archive_bills(250)
        self.run_action("billarchive", [archive.pk], word="delete please")
        self.assertTrue(BillArchive.objects.filter(pk=archive.pk).exists())
        r = self.admin(self.staff).get("/admin/retention/billarchive/")
        self.assertNotIn(b"delete_permanently", r.content)
        with self.assertRaises(BusinessRuleError):
            retention_admin_service.delete_bill_archive(archive, self.staff)
        self.assertTrue(BillArchive.objects.filter(pk=archive.pk).exists())

    def test_bills_inside_the_minimum_period_are_kept(self):
        _, archive = self.archive_bills(250)                        # archived under a 6-month minimum
        with mock.patch.object(retention_service, "MIN_KEEP_MONTHS", 12):   # the shop now must keep 12 months
            _, second = self.run_action("billarchive", [archive.pk])
        self.assertContains(second, "kept")
        self.assertTrue(BillArchive.objects.filter(pk=archive.pk).exists())

    def test_gst_invoices_inside_72_months_are_kept(self):
        _, archive = self.archive_bills(250)
        Sale.objects.update(document_type="tax_invoice")
        with mock.patch.object(retention_service, "gst_min_months", return_value=72):
            with self.assertRaises(BusinessRuleError) as ctx:
                retention_admin_service.delete_bill_archive(archive, self.root)
        self.assertIn(ctx.exception.code, ("inside_minimum_period", "gst_record_retention"))
        self.assertTrue(BillArchive.objects.filter(pk=archive.pk).exists())

    def test_one_archived_bill_is_removed_from_its_archive(self):
        (a, b), archive = self.archive_bills(250, 260)
        self.assertEqual(archive.bills_count, 2)
        marker = ArchivedBill.objects.get(sale_id=a)
        self.run_action("archivedbill", [marker.pk])
        archive.refresh_from_db()
        self.assertEqual((archive.bills_count, archive.items_count), (1, 1))
        self.assertEqual([x["bill"]["id"] for x in retention_service.from_archive(archive)], [b])   # checked copy
        self.assertIsNone(ArchivedBill.objects.get(sale_id=a).archive)
        self.assertEqual(ArchivedBill.objects.get(sale_id=b).archive_id, archive.pk)
        self.run_action("archivedbill", [ArchivedBill.objects.get(sale_id=b).pk])
        self.assertFalse(BillArchive.objects.exists())                                 # nothing left: archive gone
        self.assertEqual(Sale.objects.filter(pk__in=[a, b]).count(), 2)
        self.assertEqual(SaleItem.objects.filter(sale_id__in=[a, b]).count(), 0)


class OtherRetentionDeleteTests(AdminDeleteBase):
    def test_notice_and_log_delete_keep_archives(self):
        _, archive = self.archive_bills(250)
        notice = RetentionNotice.objects.get()
        self.run_action("retentionnotice", [notice.pk])
        self.assertFalse(RetentionNotice.objects.exists())
        archive.refresh_from_db()
        self.assertIsNone(archive.notice_id)                       # the archive is kept
        log = RetentionLog.objects.exclude(outcome="admin_deleted").first()
        self.run_action("retentionlog", [log.pk])
        self.assertFalse(RetentionLog.objects.filter(pk=log.pk).exists())
        self.assertTrue(BillArchive.objects.filter(pk=archive.pk).exists())

    def test_data_archive_delete(self):
        archive = retention_service.store_archive(self.shop, None, "orders", [{"order": 1, "items": []}],
                                                  [self.now.date()], 0)
        self.run_action("dataarchive", [archive.pk])
        self.assertFalse(DataArchive.objects.exists())
        self.assertTrue(RetentionLog.objects.filter(outcome="admin_deleted", category="orders").exists())

    def test_policy_reset_cancels_waiting_warnings(self):
        self.bill(250)
        self.enable(months=6)
        self.cleanup()
        policy = RetentionPolicy.objects.get(shop=self.shop)
        self.run_action("retentionpolicy", [policy.pk])
        self.assertEqual(RetentionNotice.objects.get().status, "cancelled")
        self.assertFalse(retention_service.policy_for(self.shop).enabled)     # back to the defaults
        self.assertEqual(self.cleanup(days=20)["outcome"], "off")

    def test_shops_apps_have_no_delete(self):
        _, archive = self.archive_bills(250)
        for url in (f"/api/v1/shop/retention/archives/{archive.pk}/", "/api/v1/shop/retention/policy/"):
            self.assertIn(self.c.delete(url).status_code, (403, 404, 405))  # no delete route for the shop's apps
        self.assertTrue(BillArchive.objects.filter(pk=archive.pk).exists())
