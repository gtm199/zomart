"""Optional GST billing. Phase E: GST reports, report date limits (3 months for every shop's PDF export,
12 months for GST shops), roles and tenant isolation."""
from datetime import timedelta
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.sales.models import CreditNote, Sale
from services.accounting_service import add_months

from .helpers import API, add_listing, checkout, client_for, make_master, make_vendor
from .test_gst import GSTIN_DELHI_2, enable_gst
from .test_gst_billing import GstShopMixin, sell

D = Decimal
GST_REPORT = f"{API}/shop/reports/gst/"
PL = f"{API}/shop/reports/profit-loss/"


def rng(start, end):
    return f"?from={start.isoformat()}&to={end.isoformat()}"


class GstReportTests(GstShopMixin, APITestCase):
    def setUp(self):
        self.make_gst_shop("rp_owner")
        self.today = timezone.localdate()
        s1 = sell(self.c, [(self.rice, "2", "0")], self.pay("236.00")).data                          # 18% incl.
        s2 = sell(self.c, [(self.oil, "1", "0"), (self.rice, "1", "0")], self.pay("223.00"),
                  customer_gstin=GSTIN_DELHI_2, customer_gst_name="Sharma Traders").data                 # B2B
        self.c.post(f"{API}/shop/sales/{s1['id']}/return/",
                    {"items": [{"sale_item": s1["items"][0]["id"], "quantity": "1"}]}, format="json")  # credit note
        self.sales = (s1, s2)

    def report(self, client=None, start=None, end=None, extra=""):
        start, end = start or self.today, end or self.today
        return (client or self.c).get(GST_REPORT + rng(start, end) + extra)

    def test_report_totals_match_the_saved_invoices_and_credit_notes(self):
        r = self.report()
        self.assertEqual(r.status_code, 200, r.data)
        d = r.data
        sums = Sale.objects.filter(shop=self.shop).exclude(document_type="bill").aggregate(
            t=Sum("taxable_total"), c=Sum("cgst_total"), s=Sum("sgst_total"), total=Sum("total"))
        inv = d["invoices"]
        self.assertEqual((inv["count"], D(inv["taxable"]), D(inv["cgst"]), D(inv["sgst"]), D(inv["total"])),
                         (2, sums["t"], sums["c"], sums["s"], sums["total"]))
        self.assertEqual((D(inv["taxable"]), D(inv["cgst"]), D(inv["total"])), (D("400.00"), D("29.50"), D("459.00")))
        cn = CreditNote.objects.get(shop=self.shop)
        self.assertEqual((d["credit_notes"]["count"], D(d["credit_notes"]["total"]), D(d["credit_notes"]["cgst"])),
                         (1, cn.total, cn.cgst_total))
        self.assertEqual(D(d["net"]["cgst"]), D(inv["cgst"]) - cn.cgst_total)
        self.assertEqual(D(d["net"]["taxable"]), D("300.00"))
        # rate-wise and HSN-wise tables add up to the invoice totals
        self.assertEqual([row["rate"] for row in d["by_rate"]], ["5.00", "18.00"])
        self.assertEqual(sum(D(row["taxable"]) for row in d["by_rate"]), D(inv["taxable"]))
        self.assertEqual(sum(D(row["cgst"]) for row in d["by_hsn"]), D(inv["cgst"]))
        rice = next(row for row in d["by_hsn"] if row["hsn"] == "1006")
        self.assertEqual((rice["quantity"], rice["taxable"], rice["rate"]), ("3", "300.00", "18.00"))
        self.assertEqual(d["credit_notes_by_rate"][0]["rate"], "18.00")
        # daily rows add up too
        self.assertEqual(sum(D(row["total"]) for row in d["by_period"]), D(inv["total"]))
        self.assertEqual(d["period"], "day")
        self.shop.refresh_from_db()
        self.assertEqual(d["shop"]["gstin"], self.shop.gstin)
        self.assertIn("not a filed return", d["disclaimer"])

    def test_b2b_and_credit_note_lists(self):
        d = self.report().data
        self.assertEqual(d["b2b_count"], 1)
        self.assertEqual((d["b2b_invoices"][0]["customer_gstin"], d["b2b_invoices"][0]["total"]),
                         (GSTIN_DELHI_2, "223.00"))
        self.assertEqual(d["credit_note_list"][0]["against"], self.sales[0]["invoice_number"])
        self.assertEqual((d["first_invoice"], d["last_invoice"]),
                         (self.sales[0]["invoice_number"], self.sales[1]["invoice_number"]))

    def test_old_invoices_report_their_saved_rates_after_rate_changes(self):
        before = self.report().data["by_rate"]
        self.c.patch(f"{API}/shop/products/{self.rice}/", {"gst_rate": "5"}, format="json")
        self.assertEqual(self.report().data["by_rate"], before)

    def test_monthly_grouping(self):
        d = self.report(extra="&period=month").data
        self.assertEqual(d["period"], "month")
        self.assertEqual(len(d["by_period"]), 1)
        self.assertEqual(d["by_period"][0]["period"], self.today.strftime("%Y-%m"))
        self.assertEqual(self.report(extra="&period=week").status_code, 400)

    def test_range_limits_for_gst_reports(self):
        ok = self.report(start=add_months(self.today, -12), end=self.today)
        self.assertEqual(ok.status_code, 200, ok.data)
        self.assertEqual(ok.data["period"], "month")
        too_long = self.report(start=add_months(self.today, -12) - timedelta(days=1), end=self.today)
        self.assertEqual(too_long.data["code"], "range_too_long")
        future = self.report(start=self.today, end=self.today + timedelta(days=1))
        self.assertEqual(future.data["code"], "future_date")
        backwards = self.report(start=self.today, end=self.today - timedelta(days=1))
        self.assertEqual(backwards.data["code"], "invalid_range")

    def test_full_financial_year_fits(self):
        start = self.today.replace(year=self.today.year - 1, month=4, day=1) if self.today.month < 4 \
            else self.today.replace(year=self.today.year - 1, month=4, day=1)
        end = start.replace(year=start.year + 1, month=3, day=31)
        self.assertEqual(self.report(start=start, end=end).status_code, 200)

    def test_pdf_export_limit_is_12_months_for_gst_shops(self):
        start = add_months(self.today, -12)
        self.assertEqual(self.c.get(PL + rng(start, self.today) + "&export=pdf").status_code, 200)
        bad = self.c.get(PL + rng(start - timedelta(days=1), self.today) + "&export=pdf")
        self.assertEqual(bad.data["code"], "range_too_long")
        future = self.c.get(PL + rng(self.today, self.today + timedelta(days=1)) + "&export=pdf")
        self.assertEqual(future.data["code"], "future_date")
        limits = self.c.get(f"{API}/shop/reports/limits/").data
        self.assertEqual((limits["gst_enabled"], limits["max_export_months"], limits["gst_report_max_months"]),
                         (True, 12, 12))

    def test_only_owner_and_manager_see_gst_reports(self):
        for role, code in (("manager", 200), ("accounts", 403), ("cashier", 403), ("inventory", 403)):
            with self.subTest(role=role):
                user, _ = make_vendor(f"rp_{role}", role=role, shop=self.shop)
                self.assertEqual(self.report(client=client_for(user, self.shop)).status_code, code)

    def test_tenant_isolation(self):
        other, other_shop = make_vendor("rp_other", "Other Shop")
        oc = client_for(other, other_shop)
        enable_gst(oc, gstin=GSTIN_DELHI_2)
        d = self.report(client=oc).data
        self.assertEqual((d["invoices"]["count"], d["credit_notes"]["count"], d["b2b_count"]), (0, 0, 0))
        self.assertEqual(d["by_rate"], [])
        self.assertEqual(client_for(other, self.shop).get(GST_REPORT).status_code, 403)

    def test_report_still_available_after_gst_is_switched_off(self):
        self.c.patch(f"{API}/shop/gst/", {"gst_enabled": False}, format="json")
        r = self.report()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["invoices"]["count"], 2)


class NonGstReportLimitTests(APITestCase):
    def setUp(self):
        self.user, self.shop = make_vendor("rp_plain", "Plain Shop")
        self.c = client_for(self.user, self.shop)
        self.today = timezone.localdate()

    def test_pdf_export_is_three_months_and_never_in_the_future(self):
        start = add_months(self.today, -3)
        self.assertEqual(self.c.get(PL + rng(start, self.today) + "&export=pdf").status_code, 200)
        bad = self.c.get(PL + rng(start - timedelta(days=1), self.today) + "&export=pdf")
        self.assertEqual(bad.data["code"], "range_too_long")
        self.assertEqual(self.c.get(PL + rng(self.today, self.today + timedelta(days=3)) + "&export=pdf").data["code"],
                         "future_date")
        limits = self.c.get(f"{API}/shop/reports/limits/").data
        self.assertEqual((limits["gst_enabled"], limits["max_export_months"]), (False, 3))

    def test_gst_report_refused_for_non_gst_shop(self):
        sp = add_listing(self.c, make_master(), price="105.00", stock="5")["id"]
        checkout(self.c, sp, qty="1", payments=[{"method": "cash", "amount": "105.00"}])
        r = self.c.get(GST_REPORT)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.data["code"], "gst_not_enabled")
