"""Reports can show sales with GST (what customers paid) or without GST (taxable value). Profit is always worked out
without GST. The switch is offered only to shops that actually collect GST (regular scheme)."""
from decimal import Decimal

from django.utils import timezone
from rest_framework.test import APITestCase

from .helpers import API, client_for, make_vendor
from .test_gst import GST
from .test_gst_billing import GstShopMixin, sell

D = Decimal
LIMITS = f"{API}/shop/reports/limits/"


class ReportAmountTests(GstShopMixin, APITestCase):
    def setUp(self):
        self.make_gst_shop("ra_owner")
        sell(self.c, [(self.rice, "2", "0")], self.pay("236.00"))       # 2 x 118 incl. 18%  -> taxable 200
        sell(self.c, [(self.oil, "1", "0")], self.pay("105.00"))        # 100 + 5% on top    -> taxable 100
        today = timezone.localdate().isoformat()
        self.q = f"?from={today}&to={today}"

    def test_sales_by_product_and_category_carry_both_amounts(self):
        sa = self.c.get(f"{API}/shop/reports/sales-analysis/{self.q}").data
        rows = {r["product"].split()[1]: r for r in sa["all_products"]}
        self.assertEqual((rows["Rice"]["sales"], rows["Rice"]["sales_ex_tax"]), (D("236.00"), D("200.00")))
        self.assertEqual((rows["Oil"]["sales"], rows["Oil"]["sales_ex_tax"]), (D("105.00"), D("100.00")))
        # profit never includes GST: (taxable value) - cost (purchase cost 60 per piece from add_listing)
        self.assertEqual((rows["Rice"]["profit"], rows["Oil"]["profit"]), (D("80.00"), D("40.00")))
        cat = sa["by_category"][0]
        self.assertEqual((cat["sales"], cat["sales_ex_tax"]), (D("341.00"), D("300.00")))
        self.assertEqual(sa["top_sellers"][0]["sales_ex_tax"], D("200.00"))

    def test_profit_and_loss_gives_both_totals_matching_the_gst_report(self):
        pl = self.c.get(f"{API}/shop/reports/profit-loss/{self.q}").data
        self.assertEqual((pl["net_sales"], pl["sales_excluding_tax"], pl["tax_included_in_sales"]),
                         (D("341.00"), D("300.00"), D("41.00")))
        gst = self.c.get(f"{API}/shop/reports/gst/{self.q}").data["invoices"]
        self.assertEqual((D(gst["total"]), D(gst["taxable"]), D(gst["tax"])), (D("341.00"), D("300.00"), D("41.00")))

    def test_csv_export_has_both_columns(self):
        r = self.c.get(f"{API}/shop/reports/sales-analysis/{self.q}&export=csv")
        header = r.content.decode("utf-8").splitlines()[0]
        self.assertIn("sales,sales_excluding_tax,profit", header)

    def test_switch_offered_only_where_gst_is_collected(self):
        self.assertTrue(self.c.get(LIMITS).data["gst_amount_switch"])
        self.c.patch(GST, {"gst_scheme": "composition"}, format="json")
        self.assertFalse(self.c.get(LIMITS).data["gst_amount_switch"])
        self.c.patch(GST, {"gst_enabled": False}, format="json")
        self.assertFalse(self.c.get(LIMITS).data["gst_amount_switch"])
        plain, plain_shop = make_vendor("ra_plain", "Plain")
        self.assertFalse(client_for(plain, plain_shop).get(LIMITS).data["gst_amount_switch"])
