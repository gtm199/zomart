"""Optional GST billing. Phase C: checkout, invoice snapshots, numbering, receipts, returns (credit notes),
online orders. GST-off shops must behave exactly as before."""
import re
import threading
import unittest
import uuid
from datetime import date, timedelta
from decimal import Decimal

from django.db import connection, transaction
from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.inventory.models import ShopProduct
from apps.sales.models import CreditNote, InvoiceSequence, Payment, Sale
from services import invoice_number_service as numbering

from .helpers import API, add_listing, checkout, client_for, make_master, make_vendor
from .test_gst import GST, GSTIN_DELHI, GSTIN_DELHI_2, enable_gst
from .test_orders import register_shopper

D = Decimal


def fy_now():
    return numbering.fy_label(numbering.fy_start_year(timezone.localdate()))


def sell(client, lines, payments=None, **extra):
    """lines: [(shop_product_id, qty, discount)]. Pays the exact total in cash unless payments are given."""
    body = {"client_txn_id": str(uuid.uuid4()),
            "items": [{"shop_product": sp, "quantity": q, "discount": d} for sp, q, d in lines],
            "payments": payments if payments is not None else []}
    body.update(extra)
    return client.post(f"{API}/shop/sales/", body, format="json")


class GstShopMixin:
    def make_gst_shop(self, username="gb_owner", scheme="regular"):
        self.owner, self.shop = make_vendor(username, "Delhi Kirana")
        self.c = client_for(self.owner, self.shop)
        enable_gst(self.c, scheme=scheme)
        self.c.patch(GST, {"gst_legal_name": "Delhi Kirana Pvt Ltd", "gst_address": "4 Karol Bagh, Delhi"},
                     format="json")
        # 118.00 @18% price includes GST
        self.rice = add_listing(self.c, make_master("Rice", "IndiaGate", None, tax="5.00"), price="118.00", stock="50")["id"]
        self.c.patch(f"{API}/shop/products/{self.rice}/", {"gst_rate": "18", "hsn_code": "1006"}, format="json")
        # 100.00 @5% tax added on top
        self.oil = add_listing(self.c, make_master("Oil", "Fortune", None, tax="5.00"), price="100.00", stock="50")["id"]
        self.c.patch(f"{API}/shop/products/{self.oil}/", {"gst_rate": "5", "hsn_code": "1512",
                                                          "price_includes_gst": False}, format="json")

    def pay(self, amount):
        return [{"method": "cash", "amount": str(amount)}]


class GstCheckoutTests(GstShopMixin, APITestCase):
    def setUp(self):
        self.make_gst_shop()

    def test_gst_off_shop_bill_is_unchanged(self):
        user, shop = make_vendor("gb_plain", "Plain Shop")
        c = client_for(user, shop)
        sp = add_listing(c, make_master("Dal", "Tata", None, tax="5.00"), price="105.00", stock="5")["id"]
        r = checkout(c, sp, qty="1", payments=self.pay("105.00"))
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual((r.data["invoice_number"], r.data["document_type"]), ("INV-000001", "bill"))
        self.assertEqual(D(r.data["tax_total"]), D("5.00"))   # unchanged internal estimate
        for key in ("cgst_total", "seller_gstin", "gst_summary", "amount_in_words", "credit_notes"):
            self.assertNotIn(key, r.data)
        self.assertNotIn("taxable_value", r.data["items"][0])
        self.assertFalse(InvoiceSequence.objects.filter(shop=shop).exists())

    def test_tax_invoice_price_includes_gst(self):
        r = sell(self.c, [(self.rice, "2", "0")], self.pay("236.00"))
        self.assertEqual(r.status_code, 201, r.data)
        d = r.data
        self.assertEqual(d["document_type"], "tax_invoice")
        self.assertEqual(d["invoice_number"], f"T{fy_now()}/000001")
        self.assertTrue(re.fullmatch(r"T\d\d-\d\d/\d{6}", d["invoice_number"]))
        self.assertEqual((D(d["total"]), D(d["taxable_total"]), D(d["cgst_total"]), D(d["sgst_total"]),
                          D(d["igst_total"]), D(d["round_off"]), D(d["tax_total"])),
                         (D("236.00"), D("200.00"), D("18.00"), D("18.00"), D("0"), D("0"), D("36.00")))
        self.assertEqual((d["seller_gstin"], d["seller_legal_name"], d["seller_address"], d["place_of_supply"]),
                         (GSTIN_DELHI, "Delhi Kirana Pvt Ltd", "4 Karol Bagh, Delhi", "07"))
        item = d["items"][0]
        self.assertEqual((item["hsn_code"], item["tax_rate"], item["taxable_value"], item["cgst"]),
                         ("1006", "18.00", "200.00", "18.00"))
        self.assertEqual(d["gst_summary"][0]["tax"], "36.00")
        self.assertEqual(d["amount_in_words"], "Rupees Two Hundred Thirty Six Only")
        self.shop.refresh_from_db()
        self.assertEqual(self.shop.invoice_counter, 0)   # plain-bill counter untouched

    def test_tax_added_on_top_and_mixed_bill(self):
        r = sell(self.c, [(self.oil, "1", "0"), (self.rice, "1", "0")], self.pay("223.00"))
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(D(r.data["total"]), D("223.00"))           # 100 + 5% on top, + 118 incl.
        self.assertEqual(D(r.data["subtotal"]), D("218.00"))        # shelf prices before tax-on-top
        self.assertEqual(D(r.data["taxable_total"]), D("200.00"))
        self.assertEqual(D(r.data["cgst_total"]), D("11.50"))
        self.assertEqual([row["rate"] for row in r.data["gst_summary"]], ["5.00", "18.00"])
        short = sell(self.c, [(self.oil, "1", "0")], self.pay("100.00"))   # paying only the shelf price
        self.assertEqual(short.data["code"], "customer_required")

    def test_discount_is_taken_before_tax_and_line_balances(self):
        r = sell(self.c, [(self.rice, "2", "18")], self.pay("218.00"))
        self.assertEqual(r.status_code, 201, r.data)
        it = r.data["items"][0]
        self.assertEqual(it["cgst"], it["sgst"])
        self.assertEqual((it["taxable_value"], it["cgst"], it["line_total"]), ("184.74", "16.63", "218.00"))
        self.assertEqual(D(it["taxable_value"]) + D(it["cgst"]) + D(it["sgst"]), D(it["line_total"]))

    def test_zero_rated_product(self):
        salt = add_listing(self.c, make_master("Salt", "Tata", None, tax="0"), price="25.00", stock="5")["id"]
        self.c.patch(f"{API}/shop/products/{salt}/", {"gst_rate": "0"}, format="json")
        r = sell(self.c, [(salt, "1", "0")], self.pay("25.00"))
        self.assertEqual((D(r.data["taxable_total"]), D(r.data["tax_total"])), (D("25.00"), D("0")))

    def test_missing_rate_is_blocked_and_nothing_changes(self):
        sugar = add_listing(self.c, make_master("Sugar", "Madhur", None), price="50.00", stock="5")["id"]
        r = sell(self.c, [(sugar, "1", "0"), (self.rice, "1", "0")], self.pay("168.00"))
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["code"], "gst_rate_missing")
        self.assertIn("Sugar", r.data["detail"])
        self.assertEqual(Sale.objects.filter(shop=self.shop).count(), 0)
        self.assertEqual(ShopProduct.objects.get(pk=sugar).stock_qty, D("5"))
        ok = sell(self.c, [(self.rice, "1", "0")], self.pay("118.00"))
        self.assertTrue(ok.data["invoice_number"].endswith("/000001"))   # no number used up by the failure

    def test_offline_upload_with_missing_rate_is_kept_and_flagged(self):
        sugar = add_listing(self.c, make_master("Sugar", "Madhur", None, tax="5.00"), price="105.00", stock="5")["id"]
        r = sell(self.c, [(sugar, "1", "0")], self.pay("105.00"), offline=True,
                 client_created_at=timezone.now().isoformat())
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(r.data["needs_review"])
        self.assertIn("no GST rate confirmed", r.data["review_note"])
        self.assertEqual(r.data["items"][0]["tax_rate"], "5.00")

    def test_bills_made_before_gst_was_switched_on_stay_plain(self):
        self.shop.refresh_from_db()
        before = self.shop.gst_enabled_at - timedelta(minutes=30)
        r = sell(self.c, [(self.rice, "1", "0")], self.pay("118.00"), offline=True,
                 client_created_at=before.isoformat())
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual((r.data["document_type"], r.data["invoice_number"]), ("bill", "INV-000001"))

    def test_customer_gstin_optional_and_validated(self):
        bad = sell(self.c, [(self.rice, "1", "0")], self.pay("118.00"), customer_gstin="07ABCDE1234F1Z0")
        self.assertEqual(bad.status_code, 400)
        self.assertIn("customer_gstin", bad.data)
        ok = sell(self.c, [(self.rice, "1", "0")], self.pay("118.00"), customer_gstin=GSTIN_DELHI_2.lower(),
                  customer_gst_name="Sharma Traders")
        self.assertEqual(ok.status_code, 201, ok.data)
        self.assertEqual((ok.data["customer_gstin"], ok.data["customer_gst_name"]), (GSTIN_DELHI_2, "Sharma Traders"))
        self.assertEqual(D(ok.data["igst_total"]), D("0"))   # counter sale in Delhi stays intra-state

    def test_receipt_text_shows_gst_details(self):
        sale = sell(self.c, [(self.rice, "1", "0")], self.pay("118.00")).data
        text = self.c.get(f"{API}/shop/sales/{sale['id']}/receipt/").data["text"]
        for part in ("Delhi Kirana Pvt Ltd", f"GSTIN: {GSTIN_DELHI}", "TAX INVOICE", sale["invoice_number"],
                     "HSN 1006", "GST 18.00%", "CGST 9.00 SGST 9.00", "Rupees One Hundred Eighteen Only"):
            self.assertIn(part, text)

    def test_invoice_snapshot_never_changes_after_later_edits(self):
        sale = sell(self.c, [(self.rice, "1", "0"), (self.oil, "1", "0")], self.pay("223.00")).data
        before = self.c.get(f"{API}/shop/sales/{sale['id']}/").data
        self.c.patch(f"{API}/shop/products/{self.rice}/", {"gst_rate": "5", "hsn_code": "9999",
                                                           "selling_price": "500.00"}, format="json")
        self.c.patch(f"{API}/shop/products/{self.oil}/", {"price_includes_gst": True}, format="json")
        self.c.patch(GST, {"gst_legal_name": "New Name", "gstin": GSTIN_DELHI_2, "gst_address": "Elsewhere"},
                     format="json")
        self.c.patch(GST, {"gst_enabled": False}, format="json")
        after = self.c.get(f"{API}/shop/sales/{sale['id']}/").data
        self.assertEqual(before, after)
        self.assertEqual(after["seller_gstin"], GSTIN_DELHI)
        self.assertIn("Rice", after["items"][0]["product_name"])

    def test_composition_shop_issues_bill_of_supply(self):
        self.c.patch(GST, {"gst_scheme": "composition"}, format="json")
        unrated = add_listing(self.c, make_master("Tea", "Tata", None), price="60.00", stock="5")["id"]
        r = sell(self.c, [(self.rice, "1", "0"), (self.oil, "1", "0"), (unrated, "1", "0")], self.pay("278.00"))
        self.assertEqual(r.status_code, 201, r.data)   # no rate needed: no tax is charged
        self.assertEqual(r.data["document_type"], "bill_of_supply")
        self.assertEqual(r.data["invoice_number"], f"B{fy_now()}/000001")
        self.assertEqual((D(r.data["total"]), D(r.data["tax_total"]), D(r.data["cgst_total"])),
                         (D("278.00"), D("0"), D("0")))   # tax-on-top is ignored for composition
        self.assertIn("Composition taxable person", r.data["bill_of_supply_note"])
        text = self.c.get(f"{API}/shop/sales/{r.data['id']}/receipt/").data["text"]
        self.assertIn("BILL OF SUPPLY", text)
        self.assertNotIn("CGST", text)

    def test_disabling_gst_returns_to_plain_numbering(self):
        sell(self.c, [(self.rice, "1", "0")], self.pay("118.00"))
        self.c.patch(GST, {"gst_enabled": False}, format="json")
        r = sell(self.c, [(self.rice, "1", "0")], self.pay("118.00"))
        self.assertEqual((r.data["document_type"], r.data["invoice_number"]), ("bill", "INV-000001"))
        self.assertNotIn("cgst_total", r.data)

    def test_tenant_isolation_of_gst_bills(self):
        sale = sell(self.c, [(self.rice, "1", "0")], self.pay("118.00")).data
        other, other_shop = make_vendor("gb_other", "Other")
        oc = client_for(other, other_shop)
        self.assertEqual(oc.get(f"{API}/shop/sales/{sale['id']}/").status_code, 404)
        self.assertEqual(oc.get(f"{API}/shop/sales/{sale['id']}/receipt/").status_code, 404)
        self.assertEqual(oc.post(f"{API}/shop/sales/{sale['id']}/return/",
                                 {"items": [{"sale_item": sale["items"][0]["id"], "quantity": "1"}]},
                                 format="json").status_code, 404)


class GstNumberingTests(GstShopMixin, APITestCase):
    def setUp(self):
        self.make_gst_shop("gn_owner")

    def test_financial_year_boundaries(self):
        self.assertEqual(numbering.fy_start_year(date(2027, 3, 31)), 2026)
        self.assertEqual(numbering.fy_start_year(date(2027, 4, 1)), 2027)
        self.assertEqual(numbering.fy_label(2026), "26-27")
        self.assertEqual(numbering.fy_label(2099), "99-00")

    def test_series_restart_each_financial_year_and_are_per_shop(self):
        other, other_shop = make_vendor("gn_other", "Other")
        with transaction.atomic():
            self.assertEqual(numbering.next_number(self.shop, "tax_invoice", date(2027, 3, 31)), "T26-27/000001")
            self.assertEqual(numbering.next_number(self.shop, "tax_invoice", date(2027, 4, 1)), "T27-28/000001")
            self.assertEqual(numbering.next_number(self.shop, "tax_invoice", date(2027, 3, 30)), "T26-27/000002")
            self.assertEqual(numbering.next_number(self.shop, "credit_note", date(2027, 3, 30)), "CN26-27/000001")
            self.assertEqual(numbering.next_number(other_shop, "tax_invoice", date(2027, 3, 31)), "T26-27/000001")

    def test_consecutive_numbers_on_real_bills(self):
        numbers = [sell(self.c, [(self.rice, "1", "0")], self.pay("118.00")).data["invoice_number"] for _ in range(3)]
        self.assertEqual([n[-6:] for n in numbers], ["000001", "000002", "000003"])
        self.assertEqual(len(set(numbers)), 3)


@unittest.skipUnless(connection.vendor == "postgresql", "real row locks need PostgreSQL")
class GstConcurrentNumberingTests(TransactionTestCase):
    def test_parallel_checkouts_get_unique_consecutive_numbers(self):
        owner, shop = make_vendor("gc_owner", "Busy Shop")
        c = client_for(owner, shop)
        enable_gst(c)
        sp = add_listing(c, make_master("Rice", "IndiaGate", None), price="118.00", stock="100")["id"]
        c.patch(f"{API}/shop/products/{sp}/", {"gst_rate": "18"}, format="json")
        results, errors = [], []

        def worker():
            try:
                r = sell(client_for(owner, shop), [(sp, "1", "0")], [{"method": "cash", "amount": "118.00"}])
                results.append((r.status_code, r.data.get("invoice_number")))
            except Exception as exc:  # pragma: no cover
                errors.append(exc)
            finally:
                connection.close()

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(sorted(code for code, _ in results), [201] * 8)
        self.assertEqual(sorted(int(n[-6:]) for _, n in results), list(range(1, 9)))
        self.assertEqual(ShopProduct.objects.get(pk=sp).stock_qty, D("92"))


class GstReturnTests(GstShopMixin, APITestCase):
    def setUp(self):
        self.make_gst_shop("gr_owner")

    def ret(self, sale, item_index, quantity):
        item = sale["items"][item_index]["id"]
        return self.c.post(f"{API}/shop/sales/{sale['id']}/return/",
                           {"items": [{"sale_item": item, "quantity": quantity}]}, format="json")

    def test_return_creates_linked_credit_note_with_reversed_tax(self):
        sale = sell(self.c, [(self.rice, "3", "0")], self.pay("354.00")).data
        r = self.ret(sale, 0, "1")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "partially_returned")
        cn = r.data["credit_notes"][0]
        self.assertEqual(cn["number"], f"CN{fy_now()}/000001")
        self.assertEqual(cn["original_invoice_number"], sale["invoice_number"])
        self.assertEqual((cn["total"], cn["taxable_total"], cn["cgst_total"], cn["sgst_total"]),
                         ("118.00", "100.00", "9.00", "9.00"))
        self.assertEqual(cn["items"][0]["hsn_code"], "1006")
        # stock and money stay consistent with a normal return
        self.assertEqual(ShopProduct.objects.get(pk=self.rice).stock_qty, D("48"))
        self.assertEqual(Payment.objects.get(kind="refund", sale_id=sale["id"]).amount, D("-118.00"))
        self.assertEqual(CreditNote.objects.get(sale_id=sale["id"]).total, D("118.00"))

    def test_credit_notes_add_up_exactly_to_the_line_tax(self):
        cheap = add_listing(self.c, make_master("Biscuit", "Parle", None), price="10.00", stock="10")["id"]
        self.c.patch(f"{API}/shop/products/{cheap}/", {"gst_rate": "18"}, format="json")
        sale = sell(self.c, [(cheap, "3", "0")], self.pay("30.00")).data
        line = sale["items"][0]
        self.assertEqual((line["cgst"], line["taxable_value"]), ("2.29", "25.42"))
        self.assertEqual(self.ret(sale, 0, "1").data["credit_notes"][0]["cgst_total"], "0.76")
        final = self.ret(sale, 0, "2").data
        self.assertEqual(final["status"], "returned")
        notes = CreditNote.objects.filter(sale_id=sale["id"])
        self.assertEqual(notes.count(), 2)
        self.assertEqual(sum(n.cgst_total for n in notes), D("2.29"))
        self.assertEqual(sum(n.sgst_total for n in notes), D("2.29"))
        self.assertEqual(sum(n.total for n in notes), D("30.00"))
        self.assertEqual(sorted(n.number[-6:] for n in notes), ["000001", "000002"])

    def test_credit_sale_return_on_gst_invoice_reverses_credit(self):
        cust = self.c.post(f"{API}/shop/customers/", {"name": "Ravi", "phone": "9000000099"}, format="json").data["id"]
        sale = sell(self.c, [(self.rice, "2", "0")], [], customer=cust).data
        r = self.ret(sale, 0, "1")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["credit_notes"][0]["total"], "118.00")
        self.assertEqual(D(self.c.get(f"{API}/shop/customers/{cust}/").data["balance"]), D("118.00"))

    def test_plain_bill_return_makes_no_credit_note(self):
        user, shop = make_vendor("gr_plain", "Plain")
        c = client_for(user, shop)
        sp = add_listing(c, make_master("Dal", "Tata", None), price="50.00", stock="5")["id"]
        sale = checkout(c, sp, qty="2", payments=self.pay("100.00")).data
        r = c.post(f"{API}/shop/sales/{sale['id']}/return/",
                   {"items": [{"sale_item": sale["items"][0]["id"], "quantity": "1"}]}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("credit_notes", r.data)
        self.assertFalse(CreditNote.objects.exists())


class GstOnlineOrderTests(GstShopMixin, APITestCase):
    def setUp(self):
        self.make_gst_shop("go_owner")
        r = self.c.patch(f"{API}/shop/store-settings/", {"store_enabled": True, "accepts_pickup": True,
                                                          "min_order": "0"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.s = register_shopper()

    def place(self, sp, quantity="1"):
        return self.s.post(f"{API}/store/orders/", {
            "shop": self.shop.id, "client_txn_id": str(uuid.uuid4()), "fulfilment": "pickup", "address": "",
            "payment_method": "cash", "items": [{"shop_product": sp, "quantity": quantity}]}, format="json")

    def vendor(self, oid, action, **body):
        return self.c.post(f"{API}/shop/orders/{oid}/{action}/", body, format="json")

    def test_online_order_uses_the_same_gst_rules(self):
        r = self.place(self.oil, "2")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(D(r.data["subtotal"]), D("210.00"))   # 2 x 100 + 5% on top
        self.assertNotIn("gst", str(r.data).lower())             # no GST details sent to the customer app
        oid = r.data["id"]
        for step in ("accept", "pack", "ready"):
            self.assertEqual(self.vendor(oid, step).status_code, 200)
        done = self.vendor(oid, "complete", payment_method="upi")
        self.assertEqual(done.status_code, 200, done.data)
        sale = Sale.objects.get(shop=self.shop)
        self.assertEqual((sale.document_type, sale.total, sale.amount_paid, sale.amount_due),
                         ("tax_invoice", D("210.00"), D("210.00"), D("0")))
        self.assertEqual((sale.cgst_total, sale.taxable_total), (D("5.00"), D("200.00")))

    def test_lowered_quantity_keeps_gst_on_top(self):
        oid = self.place(self.oil, "3").data["id"]
        item = self.s.get(f"{API}/store/orders/{oid}/").data["items"][0]["id"]
        r = self.vendor(oid, "accept", items=[{"item": item, "quantity": "1"}])
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(D(r.data["subtotal"]), D("105.00"))

    def test_product_without_rate_cannot_be_ordered(self):
        tea = add_listing(self.c, make_master("Tea", "Tata", None), price="60.00", stock="5")["id"]
        r = self.place(tea)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["code"], "item_unavailable")
        self.assertNotIn("GST", r.data["detail"])
