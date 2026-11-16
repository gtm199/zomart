"""Optional GST billing. Phase F: GST details on purchases (input tax in reports) and the retention rules for GST
records (72-month default minimum, GST invoices and credit notes inside it are never archived)."""
import uuid
from datetime import timedelta
from decimal import Decimal

from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.purchases.models import Purchase
from apps.sales.models import CreditNote, CreditNoteItem, Sale, SaleItem
from services import retention_service

from .helpers import API, add_listing, client_for, make_master, make_vendor
from .test_gst import GST, GSTIN_DELHI_2, enable_gst
from .test_gst_billing import GstShopMixin, sell

D = Decimal
POLICY = f"{API}/shop/retention/policy/"
GST_REPORT = f"{API}/shop/reports/gst/"
SUPPLIER_GSTIN = "27AAPFU0939F1ZV"   # well-formed Maharashtra GSTIN (suppliers can be in any state)


class GstPurchaseTests(GstShopMixin, APITestCase):
    def setUp(self):
        self.make_gst_shop("pu_owner")
        self.sup = self.c.post(f"{API}/shop/suppliers/", {"name": "Agra Traders", "gstin": SUPPLIER_GSTIN},
                               format="json").data["id"]

    def buy(self, items, client=None, **extra):
        body = {"client_txn_id": str(uuid.uuid4()), "supplier": self.sup, "invoice_number": "AT/77",
                "items": items, "payments": [], **extra}
        return (client or self.c).post(f"{API}/shop/purchases/", body, format="json")

    def test_purchase_records_supplier_gstin_and_gst_per_line(self):
        r = self.buy([{"shop_product": self.rice, "quantity": "10", "unit_cost": "100.00", "gst_rate": "18",
                       "gst_amount": "152.54"},
                      {"shop_product": self.oil, "quantity": "5", "unit_cost": "80.00", "gst_rate": "5", "gst_amount": "19.05"}])
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual((r.data["supplier_gstin"], r.data["gst_total"], r.data["invoice_number"]),
                         (SUPPLIER_GSTIN, "171.59", "AT/77"))   # supplier's saved GSTIN used by default
        self.assertEqual(r.data["total"], "1400.00")                # what is owed is unchanged by the GST record
        self.assertEqual(D(self.c.get(f"{API}/shop/suppliers/{self.sup}/").data["balance"]), D("1400.00"))
        self.assertEqual(r.data["items"][0]["gst_amount"], "152.54")

    def test_typed_supplier_gstin_is_format_checked(self):
        bad = self.buy([{"shop_product": self.rice, "quantity": "1", "unit_cost": "100"}], supplier_gstin="27AAPFU0939F1ZX")
        self.assertEqual(bad.status_code, 400)
        self.assertIn("supplier_gstin", bad.data)
        ok = self.buy([{"shop_product": self.rice, "quantity": "1", "unit_cost": "100"}], supplier_gstin=GSTIN_DELHI_2)
        self.assertEqual(ok.data["supplier_gstin"], GSTIN_DELHI_2)

    def test_gst_amount_cannot_exceed_the_line(self):
        r = self.buy([{"shop_product": self.rice, "quantity": "1", "unit_cost": "100", "gst_amount": "100.01"}])
        self.assertEqual(r.data["code"], "invalid_gst_amount")
        self.assertEqual(Purchase.objects.count(), 0)

    def test_report_shows_input_tax_net_of_returns(self):
        p = self.buy([{"shop_product": self.rice, "quantity": "10", "unit_cost": "118.00", "gst_rate": "18",
                       "gst_amount": "180.00"}]).data
        today = timezone.localdate().isoformat()
        rep = self.c.get(f"{GST_REPORT}?from={today}&to={today}").data["purchases"]
        self.assertEqual((rep["count"], rep["with_supplier_gstin"], rep["value"], rep["gst"]), (1, 1, "1180.00", "180.00"))
        self.assertEqual(rep["by_rate"][0]["rate"], "18.00")
        self.assertEqual(rep["by_supplier"][0]["supplier_gstin"], SUPPLIER_GSTIN)
        self.assertIn("CA", rep["note"])
        r = self.c.post(f"{API}/shop/purchases/{p['id']}/return/",
                        {"items": [{"purchase_item": p["items"][0]["id"], "quantity": "5"}]}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        rep = self.c.get(f"{GST_REPORT}?from={today}&to={today}").data["purchases"]
        self.assertEqual((rep["value"], rep["gst"]), ("590.00", "90.00"))

    def test_purchases_are_tenant_scoped_in_reports(self):
        self.buy([{"shop_product": self.rice, "quantity": "1", "unit_cost": "100", "gst_amount": "15.25"}])
        other, other_shop = make_vendor("pu_other", "Other")
        oc = client_for(other, other_shop)
        enable_gst(oc, gstin=GSTIN_DELHI_2)
        self.assertEqual(oc.get(GST_REPORT).data["purchases"]["count"], 0)


class NonGstPurchaseTests(APITestCase):
    def test_non_gst_shop_neither_sees_nor_sends_gst_fields(self):
        user, shop = make_vendor("pu_plain", "Plain")
        c = client_for(user, shop)
        sp = add_listing(c, make_master("Dal", "Tata", None), price="50.00", stock="1")["id"]
        sup = c.post(f"{API}/shop/suppliers/", {"name": "Local", "gstin": SUPPLIER_GSTIN}, format="json").data["id"]
        body = {"client_txn_id": str(uuid.uuid4()), "supplier": sup, "items": [{"shop_product": sp, "quantity": "2",
                "unit_cost": "40"}], "payments": []}
        r = c.post(f"{API}/shop/purchases/", body, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        for key in ("supplier_gstin", "gst_total"):
            self.assertNotIn(key, r.data)
        self.assertNotIn("gst_amount", r.data["items"][0])
        self.assertEqual(Purchase.objects.get().supplier_gstin, "")   # saved supplier GSTIN not copied
        body["client_txn_id"] = str(uuid.uuid4())
        body["items"][0]["gst_amount"] = "5"
        self.assertEqual(c.post(f"{API}/shop/purchases/", body, format="json").data["code"], "gst_not_enabled")


class GstRetentionTests(GstShopMixin, APITestCase):
    def setUp(self):
        self.now = timezone.now()
        self.make_gst_shop("rg_owner")
        self.owner.email = "owner@example.com"
        self.owner.save()

    def gst_bill(self, age_days, qty="1"):
        r = sell(self.c, [(self.rice, qty, "0")], self.pay(str(118 * int(qty)) + ".00"))
        assert r.status_code == 201, r.data
        Sale.objects.filter(pk=r.data["id"]).update(created_at=self.now - timedelta(days=age_days))
        return r.data

    def test_policy_minimum_is_72_months_for_gst_shops(self):
        data = self.c.get(POLICY).data
        self.assertEqual((data["minimums"]["bills_months"], data["minimum_months"], data["gst_records"]), (72, 72, True))
        self.assertGreaterEqual(data["keep_months"], 72)
        self.assertIn("CA", data["gst_note"])
        low = self.c.patch(POLICY, {"enabled": True, "keep_months": 24}, format="json")
        self.assertEqual((low.status_code, low.data["code"]), (400, "below_gst_minimum"))
        self.assertEqual(self.c.patch(POLICY, {"enabled": True, "keep_months": 84}, format="json").status_code, 200)
        plain_user, plain_shop = make_vendor("rg_plain", "Plain")
        self.assertEqual(client_for(plain_user, plain_shop).get(POLICY).data["minimums"]["bills_months"], 6)

    @override_settings(GST_RECORD_RETENTION_MONTHS=96)
    def test_minimum_comes_from_settings_once_the_ca_confirms_it(self):
        self.shop.refresh_from_db()
        self.assertEqual(retention_service.min_keep_months(self.shop), 96)
        self.assertEqual(self.c.get(POLICY).data["minimums"]["bills_months"], 96)

    def test_switching_gst_off_keeps_the_protection(self):
        self.gst_bill(1)
        self.c.patch(GST, {"gst_enabled": False}, format="json")
        self.shop.refresh_from_db()
        self.assertEqual(retention_service.min_keep_months(self.shop), 72)

    def test_gst_invoices_inside_the_minimum_are_never_selected(self):
        inside = self.gst_bill(400)            # 13 months old: inside 72 months
        outside = self.gst_bill(80 * 31)       # about 80 months old
        with_note = self.gst_bill(80 * 31, qty="2")
        self.c.post(f"{API}/shop/sales/{with_note['id']}/return/",
                    {"items": [{"sale_item": with_note["items"][0]["id"], "quantity": "1"}]}, format="json")  # recent credit note
        picked = set(retention_service.eligible(self.shop, self.now).values_list("id", flat=True))
        self.assertNotIn(inside["id"], picked)        # even with a cutoff of "now" (e.g. an older warning)
        self.assertNotIn(with_note["id"], picked)     # its credit note is recent
        self.assertIn(outside["id"], picked)

    def test_cleanup_respects_the_minimum_and_never_removes_credit_notes(self):
        self.c.patch(POLICY, {"enabled": True, "keep_months": 72, "notify_days": 14}, format="json")
        young = self.gst_bill(400)
        old = self.gst_bill(80 * 31, qty="2")
        self.c.post(f"{API}/shop/sales/{old['id']}/return/",
                    {"items": [{"sale_item": old["items"][0]["id"], "quantity": "1"}]}, format="json")
        CreditNote.objects.update(created_at=self.now - timedelta(days=80 * 31))   # the credit note is old too
        notes_before, note_items_before = CreditNote.objects.count(), CreditNoteItem.objects.count()
        first = retention_service.run_for_shop(self.shop, now=self.now)
        self.assertEqual((first["outcome"], first["announced_bills"]), ("announced", 1))
        done = retention_service.run_for_shop(self.shop, now=self.now + timedelta(days=14))
        self.assertEqual((done["outcome"], done["bills_archived"]), ("archived", 1))
        self.assertEqual(SaleItem.objects.filter(sale_id=old["id"]).count(), 0)      # only the very old bill's items
        self.assertEqual(SaleItem.objects.filter(sale_id=young["id"]).count(), 1)
        self.assertEqual((CreditNote.objects.count(), CreditNoteItem.objects.count()), (notes_before, note_items_before))
        kept = Sale.objects.get(pk=old["id"])                                          # the invoice header stays
        self.assertEqual((kept.document_type, kept.invoice_number, kept.cgst_total),
                         ("tax_invoice", old["invoice_number"], D(old["cgst_total"])))

    def test_preview_uses_the_gst_minimum(self):
        self.c.patch(POLICY, {"enabled": True, "keep_months": 72}, format="json")
        self.gst_bill(400)
        self.gst_bill(30 * 31)
        self.assertEqual(self.c.get(POLICY).data["preview"]["bills"], 0)
