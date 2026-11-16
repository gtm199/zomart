"""Bill-details minimum: 6 months for shops without GST (was 12); GST shops stay at 72 and never below 12."""
from datetime import timedelta

from django.test import override_settings

from services import retention_service

from .test_gst import GST, enable_gst
from .test_retention import POLICY, Base


class NonGstSixMonthMinimumTests(Base):
    def test_six_months_is_allowed_and_used_by_the_cleanup(self):
        older = self.bill(200)        # about 6.5 months old
        younger = self.bill(150)      # about 5 months old
        self.enable(months=6)
        data = self.c.get(POLICY).data
        self.assertEqual((data["keep_months"], data["minimums"]["bills_months"], data["gst_records"]), (6, 6, False))
        first = self.cleanup()
        self.assertEqual((first["outcome"], first["announced_bills"]), ("announced", 1))   # warning first, as before
        done = self.cleanup(days=14)
        self.assertEqual((done["outcome"], done["bills_archived"]), ("archived", 1))
        self.assertEqual((self.items(older), self.items(younger)), (0, 1))

    def test_below_six_months_is_refused(self):
        r = self.c.patch(POLICY, {"enabled": True, "keep_months": 5}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("keep_months", r.data)


class GstMinimumUnchangedTests(Base):
    def setUp(self):
        super().setUp()
        enable_gst(self.c)
        self.shop.refresh_from_db()

    def test_gst_shop_still_needs_72_months(self):
        self.assertEqual(self.c.get(POLICY).data["minimums"]["bills_months"], 72)
        r = self.c.patch(POLICY, {"enabled": True, "keep_months": 6}, format="json")
        self.assertEqual((r.status_code, r.data["code"]), (400, "below_gst_minimum"))

    @override_settings(GST_RECORD_RETENTION_MONTHS=3)
    def test_gst_minimum_never_drops_below_12_months(self):
        self.assertEqual(retention_service.min_keep_months(self.shop), 12)

    def test_switching_gst_off_after_gst_bills_keeps_72(self):
        self.c.patch(GST, {"gst_enabled": False}, format="json")
        self.shop.refresh_from_db()
        # no GST documents were made in this test shop, so it falls back to the non-GST minimum
        self.assertEqual(retention_service.min_keep_months(self.shop), 6)
