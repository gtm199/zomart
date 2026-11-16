"""Optional GST billing. Phase A: shop-level GST settings and GSTIN format validation."""
from decimal import Decimal

from django.test import SimpleTestCase
from rest_framework.test import APITestCase

from apps.shops.models import Shop, ShopGstChange
from apps.shops.roles import ROLE_CAPS, Cap
from services.gstin import GstinError, check_char, is_valid_gstin, mask, validate_gstin

from .helpers import API, add_listing, checkout, client_for, make_master, make_vendor

GST = f"{API}/shop/gst/"


def delhi_gstin(pan="AAACH7409R", entity="1"):
    """Builds a well-formed Delhi GSTIN with the correct check character."""
    first14 = f"07{pan}{entity}Z"
    return first14 + check_char(first14)


GSTIN_DELHI = delhi_gstin()
GSTIN_DELHI_2 = delhi_gstin("AABCU9603R")


class GstinFormatTests(SimpleTestCase):
    def test_known_published_gstins_pass(self):
        self.assertTrue(is_valid_gstin("27AAPFU0939F1ZV"))
        self.assertTrue(is_valid_gstin("29AAGCB7383J1Z4"))

    def test_built_delhi_gstin_passes_and_is_normalised(self):
        self.assertEqual(validate_gstin(" " + GSTIN_DELHI.lower() + " "), GSTIN_DELHI)
        self.assertEqual(validate_gstin(GSTIN_DELHI, state_code="07"), GSTIN_DELHI)

    def test_rejections(self):
        bad_check = GSTIN_DELHI[:14] + ("0" if GSTIN_DELHI[14] != "0" else "1")
        for value in ["", "07AAACH7409R1Z", GSTIN_DELHI + "X", bad_check,
                      "07AAAC17409R1Z5",   # PAN pattern broken
                      "07AAACH7409R1Y5",   # 14th character must be Z
                      "07AAACH7409R0Z5"]:  # entity number cannot be 0
            with self.subTest(value=value):
                self.assertFalse(is_valid_gstin(value))
        other_state = "99" + GSTIN_DELHI[2:14]
        self.assertFalse(is_valid_gstin("00" + GSTIN_DELHI[2:]))  # no state 00
        with self.assertRaises(GstinError):
            validate_gstin("27AAPFU0939F1ZV", state_code="07")  # valid, but Maharashtra
        self.assertTrue(is_valid_gstin(other_state + check_char(other_state)))

    def test_mask_hides_middle(self):
        self.assertNotIn(GSTIN_DELHI[7:11], mask(GSTIN_DELHI))
        self.assertEqual(len(mask(GSTIN_DELHI)), 15)


class ShopGstSettingsTests(APITestCase):
    def setUp(self):
        self.owner, self.shop = make_vendor("gst_owner", "Delhi Kirana")
        self.c = client_for(self.owner, self.shop)

    def test_existing_shops_default_to_gst_off(self):
        r = self.c.get(GST)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data["gst_enabled"])
        self.assertIsNone(r.data["gst_enabled_at"])
        self.assertEqual(r.data["gst_state_code"], "07")
        self.assertEqual(r.data["gst_scheme"], "regular")
        self.assertIn("Format check only", r.data["gstin_check_note"])
        self.assertFalse(self.c.get(f"{API}/shop/").data["gst_enabled"])

    def test_enabling_requires_gstin(self):
        r = self.c.patch(GST, {"gst_enabled": True}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["code"], "gstin_required")
        self.shop.refresh_from_db()
        self.assertFalse(self.shop.gst_enabled)

    def test_enabling_rejects_bad_or_out_of_state_gstin(self):
        bad = self.c.patch(GST, {"gst_enabled": True, "gstin": GSTIN_DELHI[:14] + "0" if GSTIN_DELHI[14] != "0"
                                 else GSTIN_DELHI[:14] + "1"}, format="json")
        self.assertEqual(bad.data["code"], "invalid_gstin")
        maharashtra = self.c.patch(GST, {"gst_enabled": True, "gstin": "27AAPFU0939F1ZV"}, format="json")
        self.assertEqual(maharashtra.data["code"], "invalid_gstin")
        self.assertIn("state code is 07", maharashtra.data["detail"])
        self.shop.refresh_from_db()
        self.assertFalse(self.shop.gst_enabled)
        self.assertEqual(self.shop.gstin, "")

    def test_enable_records_date_legal_name_and_audit(self):
        r = self.c.patch(GST, {"gst_enabled": True, "gstin": GSTIN_DELHI.lower(), "gst_scheme": "composition"},
                         format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data["gst_enabled"])
        self.assertEqual(r.data["gstin"], GSTIN_DELHI)
        self.assertEqual(r.data["gst_scheme"], "composition")
        self.assertEqual(r.data["gst_legal_name"], "Delhi Kirana")  # defaulted, editable
        self.assertIsNotNone(r.data["gst_enabled_at"])
        first_on = r.data["gst_enabled_at"]
        # Saving other fields while on does not move the switch-on date.
        r2 = self.c.patch(GST, {"gst_legal_name": "Delhi Kirana Pvt Ltd", "gst_address": "Shop 4, Karol Bagh"},
                          format="json")
        self.assertEqual(r2.data["gst_enabled_at"], first_on)
        self.assertEqual(r2.data["gst_legal_name"], "Delhi Kirana Pvt Ltd")
        log = ShopGstChange.objects.get(shop=self.shop)
        self.assertTrue(log.gst_enabled and log.gstin_changed)
        self.assertEqual(log.changed_by, self.owner)

    def test_disabling_keeps_all_gst_data(self):
        self.c.patch(GST, {"gst_enabled": True, "gstin": GSTIN_DELHI, "gst_legal_name": "DK Traders",
                           "gst_address": "Karol Bagh", "gst_scheme": "regular"}, format="json")
        r = self.c.patch(GST, {"gst_enabled": False}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.shop.refresh_from_db()
        self.assertFalse(self.shop.gst_enabled)
        self.assertEqual((self.shop.gstin, self.shop.gst_legal_name, self.shop.gst_address),
                         (GSTIN_DELHI, "DK Traders", "Karol Bagh"))
        self.assertIsNotNone(self.shop.gst_enabled_at)
        self.assertEqual(ShopGstChange.objects.filter(shop=self.shop).count(), 2)

    def test_reenabling_updates_switch_on_date(self):
        on1 = self.c.patch(GST, {"gst_enabled": True, "gstin": GSTIN_DELHI, "gst_scheme": "regular"},
                           format="json").data["gst_enabled_at"]
        self.c.patch(GST, {"gst_enabled": False}, format="json")
        on2 = self.c.patch(GST, {"gst_enabled": True, "gst_scheme": "regular"}, format="json").data["gst_enabled_at"]
        self.assertGreater(on2, on1)

    def test_switching_on_requires_scheme_confirmation(self):
        r = self.c.patch(GST, {"gst_enabled": True, "gstin": GSTIN_DELHI}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["code"], "gst_scheme_confirmation_required")
        self.shop.refresh_from_db()
        self.assertFalse(self.shop.gst_enabled)
        ok = self.c.patch(GST, {"gst_enabled": True, "gstin": GSTIN_DELHI, "gst_scheme": "regular"}, format="json")
        self.assertEqual(ok.status_code, 200, ok.data)
        # Once on, other edits do not need the scheme again.
        self.assertEqual(self.c.patch(GST, {"gst_trade_name": "DK"}, format="json").status_code, 200)

    def test_cannot_blank_gstin_while_enabled(self):
        self.c.patch(GST, {"gst_enabled": True, "gstin": GSTIN_DELHI, "gst_scheme": "regular"}, format="json")
        r = self.c.patch(GST, {"gstin": ""}, format="json")
        self.assertEqual(r.data["code"], "gstin_required")

    def test_invalid_state_code_and_scheme(self):
        self.assertEqual(self.c.patch(GST, {"gst_state_code": "00"}, format="json").data["code"], "invalid_state_code")
        self.assertEqual(self.c.patch(GST, {"gst_scheme": "flat"}, format="json").status_code, 400)

    def test_only_owner_can_change_gst(self):
        self.assertIn(Cap.MANAGE_GST, ROLE_CAPS["owner"])
        for role in ("manager", "cashier", "inventory", "accounts", "delivery"):
            self.assertNotIn(Cap.MANAGE_GST, ROLE_CAPS[role])
        for role in ("manager", "cashier", "accounts"):
            with self.subTest(role=role):
                user, _ = make_vendor(f"gst_{role}", role=role, shop=self.shop)
                c = client_for(user, self.shop)
                r = c.patch(GST, {"gst_enabled": True, "gstin": GSTIN_DELHI}, format="json")
                self.assertEqual(r.status_code, 403)
                self.assertEqual(c.get(GST).status_code, 200)  # needed for printing receipts
        self.shop.refresh_from_db()
        self.assertFalse(self.shop.gst_enabled)

    def test_manager_cannot_change_gst_through_shop_endpoint(self):
        manager, _ = make_vendor("gst_mgr2", role="manager", shop=self.shop)
        c = client_for(manager, self.shop)
        r = c.patch(f"{API}/shop/", {"name": "Renamed", "gstin": GSTIN_DELHI, "gst_enabled": True}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.shop.refresh_from_db()
        self.assertEqual(self.shop.name, "Renamed")   # normal settings still work
        self.assertEqual(self.shop.gstin, "")
        self.assertFalse(self.shop.gst_enabled)

    def test_tenant_isolation(self):
        self.c.patch(GST, {"gst_enabled": True, "gstin": GSTIN_DELHI, "gst_scheme": "regular"}, format="json")
        other, other_shop = make_vendor("gst_other", "Other Shop")
        oc = client_for(other, other_shop)
        self.assertFalse(oc.get(GST).data["gst_enabled"])
        self.assertEqual(oc.get(GST).data["gstin"], "")
        oc.patch(GST, {"gst_enabled": True, "gstin": GSTIN_DELHI_2, "gst_scheme": "regular"}, format="json")
        self.shop.refresh_from_db()
        self.assertEqual(self.shop.gstin, GSTIN_DELHI)
        # Using another shop's id is refused.
        self.assertEqual(client_for(other, self.shop).get(GST).status_code, 403)

    def test_gst_off_billing_unchanged(self):
        """Phase A must not change billing for any shop."""
        sp = add_listing(self.c, make_master(tax="5.00"), price="105.00", stock="5")["id"]
        r = checkout(self.c, sp, qty="1", payments=[{"method": "cash", "amount": "105.00"}])
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["invoice_number"], "INV-000001")
        self.assertEqual(Decimal(r.data["total"]), Decimal("105.00"))
        self.assertFalse(Shop.objects.get(pk=self.shop.pk).gst_enabled)


# ======================= Phase B: product GST settings + gst_service =======================
from apps.inventory.models import ShopProduct  # noqa: E402
from services import gst_service as g  # noqa: E402
from services.exceptions import BusinessRuleError  # noqa: E402

D = Decimal


def enable_gst(client, scheme="regular", gstin=None):
    r = client.patch(GST, {"gst_enabled": True, "gstin": gstin or GSTIN_DELHI, "gst_scheme": scheme}, format="json")
    assert r.status_code == 200, r.data
    return r


class GstMathTests(SimpleTestCase):
    def line(self, **kw):
        return g.compute_line(**kw)

    def test_rounding_rule_is_half_up_to_paisa(self):
        self.assertEqual(g.round_paise(D("0.005")), D("0.01"))
        self.assertEqual(g.round_paise(D("0.0049")), D("0.00"))
        self.assertEqual(g.round_paise(D("0.765")), D("0.77"))

    def test_inclusive_intra_state_split(self):
        ln = self.line(gross=D("118.00"), rate=D("18"))
        self.assertEqual((ln.taxable_value, ln.cgst, ln.sgst, ln.igst, ln.line_total),
                         (D("100.00"), D("9.00"), D("9.00"), D("0.00"), D("118.00")))
        ln = self.line(gross=D("105.00"), rate=D("5"))
        self.assertEqual((ln.taxable_value, ln.cgst, ln.sgst), (D("100.00"), D("2.50"), D("2.50")))

    def test_inclusive_odd_paisa_keeps_cgst_equal_sgst_and_line_balanced(self):
        # 10.00 @18%: formula taxable 8.47, tax 1.53 -> halves 0.765 -> 0.77 each; taxable becomes 8.46.
        ln = self.line(gross=D("10.00"), rate=D("18"))
        self.assertEqual((ln.cgst, ln.sgst), (D("0.77"), D("0.77")))
        self.assertEqual(ln.taxable_value, D("8.46"))
        self.assertEqual(ln.taxable_value + ln.tax, ln.line_total)
        self.assertEqual(ln.line_total, D("10.00"))   # customer pays the shelf price, never more

    def test_exclusive_tax_added_on_top(self):
        ln = self.line(gross=D("100.00"), rate=D("18"), price_includes_gst=False)
        self.assertEqual((ln.taxable_value, ln.cgst, ln.sgst, ln.line_total),
                         (D("100.00"), D("9.00"), D("9.00"), D("118.00")))
        ln = self.line(gross=D("10.10"), rate=D("5"), price_includes_gst=False)
        self.assertEqual((ln.cgst, ln.sgst, ln.line_total), (D("0.25"), D("0.25"), D("10.60")))

    def test_inter_state_uses_igst(self):
        ln = self.line(gross=D("118.00"), rate=D("18"), supply=g.INTER)
        self.assertEqual((ln.taxable_value, ln.cgst, ln.sgst, ln.igst), (D("100.00"), D("0"), D("0"), D("18.00")))
        ln = self.line(gross=D("10.10"), rate=D("5"), price_includes_gst=False, supply=g.INTER)
        self.assertEqual((ln.igst, ln.line_total), (D("0.51"), D("10.61")))

    def test_place_of_supply(self):
        self.assertEqual(g.place_of_supply("07"), g.INTRA)
        self.assertEqual(g.place_of_supply("07", "07"), g.INTRA)
        self.assertEqual(g.place_of_supply("07", "09"), g.INTER)

    def test_zero_rated(self):
        ln = self.line(gross=D("50.00"), rate=D("0"))
        self.assertEqual((ln.taxable_value, ln.tax, ln.line_total), (D("50.00"), D("0.00"), D("50.00")))

    def test_discount_is_applied_before_tax(self):
        ln = self.line(gross=D("236.00"), discount=D("118.00"), rate=D("18"))
        self.assertEqual((ln.taxable_value, ln.cgst, ln.sgst, ln.line_total),
                         (D("100.00"), D("9.00"), D("9.00"), D("118.00")))
        ln = self.line(gross=D("200.00"), discount=D("100.00"), rate=D("18"), price_includes_gst=False)
        self.assertEqual((ln.taxable_value, ln.line_total), (D("100.00"), D("118.00")))
        with self.assertRaises(BusinessRuleError):
            self.line(gross=D("10"), discount=D("11"), rate=D("5"))

    def test_bill_discount_allocated_proportionally_and_exactly(self):
        self.assertEqual(g.allocate_discount([D("100"), D("200"), D("300")], D("10")),
                         [D("1.67"), D("3.33"), D("5.00")])
        parts = g.allocate_discount([D("33.33"), D("33.33"), D("33.34")], D("1.00"))
        self.assertEqual(sum(parts), D("1.00"))
        self.assertEqual(g.allocate_discount([D("10")], D("0")), [D("0.00")])

    def test_composition_is_bill_of_supply_without_tax(self):
        bill = g.compute_bill([{"gross": D("118"), "rate": D("18")},
                               {"gross": D("100"), "rate": D("5"), "price_includes_gst": False}],
                              scheme=g.COMPOSITION)
        self.assertEqual(bill.document_type, g.DOC_BILL_OF_SUPPLY)
        self.assertEqual(bill.tax_total, D("0"))
        self.assertEqual(bill.taxable_total, D("218.00"))
        self.assertEqual(bill.grand_total, D("218.00"))
        self.assertEqual(g.document_type(True, "composition"), g.DOC_BILL_OF_SUPPLY)
        self.assertEqual(g.document_type(True, "regular"), g.DOC_TAX_INVOICE)
        self.assertEqual(g.document_type(False, "regular"), g.DOC_BILL)

    def test_bill_totals_equal_sum_of_lines_with_visible_round_off(self):
        rows = [{"gross": D("118"), "rate": D("18")}, {"gross": D("10"), "rate": D("18")},
                {"gross": D("105"), "rate": D("5")}, {"gross": D("10.10"), "rate": D("0")}]
        bill = g.compute_bill(rows)
        self.assertEqual(bill.lines_total, D("243.10"))
        self.assertEqual((bill.round_off, bill.grand_total), (D("0.00"), D("243.10")))  # default: no rounding
        self.assertEqual(bill.taxable_total + bill.tax_total, bill.lines_total)
        self.assertEqual(bill.cgst_total, sum(ln.cgst for ln in bill.lines))
        self.assertEqual(bill.cgst_total, bill.sgst_total)
        rupee = g.compute_bill(rows, round_to=D("1"))
        self.assertEqual((rupee.round_off, rupee.grand_total), (D("-0.10"), D("243.00")))
        self.assertEqual(rupee.lines_total + rupee.round_off, rupee.grand_total)
        self.assertEqual([r["rate"] for r in bill.rate_summary], [D("0"), D("5"), D("18")])
        r18 = bill.rate_summary[-1]
        self.assertEqual((r18["taxable_value"], r18["cgst"], r18["tax"]), (D("108.46"), D("9.77"), D("19.54")))

    def test_rate_and_hsn_validation(self):
        self.assertEqual(g.validate_rate("18"), D("18.00"))
        self.assertEqual(g.validate_rate("0.25"), D("0.25"))
        self.assertEqual(g.validate_rate("7.5"), D("7.50"))   # not limited to a slab list
        for bad in ("-1", "101", "12.345"):
            with self.subTest(rate=bad), self.assertRaises(ValueError):
                g.validate_rate(bad)
        for ok in ("", "1006", "100630", "10063010"):
            self.assertEqual(g.validate_hsn(ok), ok)
        for bad in ("123", "12345", "10AB", "1234567"):
            with self.subTest(hsn=bad), self.assertRaises(ValueError):
                g.validate_hsn(bad)

    def test_amount_in_words(self):
        self.assertEqual(g.amount_in_words(D("1234567.50")),
                         "Rupees Twelve Lakh Thirty Four Thousand Five Hundred Sixty Seven and Fifty Paise Only")
        self.assertEqual(g.amount_in_words(D("118")), "Rupees One Hundred Eighteen Only")
        self.assertEqual(g.amount_in_words(D("0")), "Rupees Zero Only")


class ProductGstSettingsTests(APITestCase):
    def setUp(self):
        self.owner, self.shop = make_vendor("pg_owner", "Delhi Mart")
        self.c = client_for(self.owner, self.shop)
        self.master = make_master(tax="5.00")
        self.master.hsn_code = "1101"
        self.master.save()
        self.sp = add_listing(self.c, self.master, price="105.00", stock="10")["id"]
        self.url = f"{API}/shop/products/{self.sp}/"

    def test_gst_off_shop_sees_and_sets_no_gst_fields(self):
        data = self.c.get(self.url).data
        for key in ("gst_rate", "hsn_code", "price_includes_gst", "suggested_gst_rate"):
            self.assertNotIn(key, data)
        r = self.c.patch(self.url, {"gst_rate": "5"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIsNone(ShopProduct.objects.get(pk=self.sp).gst_rate)

    def test_gst_on_shows_unconfirmed_with_catalogue_suggestion(self):
        enable_gst(self.c)
        data = self.c.get(self.url).data
        self.assertIsNone(data["gst_rate"])
        self.assertFalse(data["gst_confirmed"])
        self.assertTrue(data["price_includes_gst"])
        self.assertEqual((data["suggested_gst_rate"], data["suggested_hsn_code"]), ("5.00", "1101"))
        ids = [p["id"] for p in self.c.get(f"{API}/shop/products/?gst_unconfirmed=true").data["results"]]
        self.assertIn(self.sp, ids)

    def test_vendor_confirms_rate_hsn_and_any_rate_is_allowed(self):
        enable_gst(self.c)
        r = self.c.patch(self.url, {"gst_rate": "7.5", "hsn_code": "110100", "price_includes_gst": False}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual((r.data["gst_rate"], r.data["hsn_code"], r.data["price_includes_gst"], r.data["gst_confirmed"]),
                         ("7.50", "110100", False, True))
        self.assertIsNotNone(ShopProduct.objects.get(pk=self.sp).gst_confirmed_at)
        self.assertEqual(self.c.patch(self.url, {"hsn_code": "12345"}, format="json").status_code, 400)
        self.assertEqual(self.c.patch(self.url, {"gst_rate": "150"}, format="json").status_code, 400)
        ids = [p["id"] for p in self.c.get(f"{API}/shop/products/?gst_unconfirmed=true").data["results"]]
        self.assertNotIn(self.sp, ids)

    def test_create_listing_with_gst_fields(self):
        enable_gst(self.c)
        other = make_master(name="Oil", brand="Fortune", barcode=None, tax="18.00")
        r = self.c.post(f"{API}/shop/products/", {"master_product": other.id, "selling_price": "150.00",
                        "gst_rate": "5", "hsn_code": "1512"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual((r.data["gst_rate"], r.data["hsn_code"]), ("5.00", "1512"))

    def test_master_catalogue_update_never_overwrites_vendor_gst(self):
        enable_gst(self.c)
        self.c.patch(self.url, {"gst_rate": "5", "hsn_code": "1101"}, format="json")
        self.master.tax_rate = D("18.00")
        self.master.hsn_code = "9999"
        self.master.save()
        sp = ShopProduct.objects.get(pk=self.sp)
        self.assertEqual((sp.gst_rate, sp.hsn_code), (D("5.00"), "1101"))
        data = self.c.get(self.url).data
        self.assertEqual((data["gst_rate"], data["suggested_gst_rate"]), ("5.00", "18.00"))

    def test_missing_rate_guard(self):
        enable_gst(self.c)
        sp = ShopProduct.objects.select_related("master_product__brand").get(pk=self.sp)
        with self.assertRaises(BusinessRuleError) as ctx:
            g.require_confirmed_rate(sp)
        self.assertEqual(ctx.exception.code, "gst_rate_missing")
        self.assertIn("GST rate", ctx.exception.message)
        sp.gst_rate = D("5")
        self.assertEqual(g.require_confirmed_rate(sp), D("5"))

    def test_cashier_cannot_set_gst_and_disabling_hides_but_keeps(self):
        enable_gst(self.c)
        cashier, _ = make_vendor("pg_cashier", role="cashier", shop=self.shop)
        self.assertEqual(client_for(cashier, self.shop).patch(self.url, {"gst_rate": "5"}, format="json").status_code, 403)
        self.c.patch(self.url, {"gst_rate": "5"}, format="json")
        self.c.patch(GST, {"gst_enabled": False}, format="json")
        self.assertNotIn("gst_rate", self.c.get(self.url).data)
        self.assertEqual(ShopProduct.objects.get(pk=self.sp).gst_rate, D("5.00"))

    def test_other_shop_cannot_touch_products(self):
        enable_gst(self.c)
        other, other_shop = make_vendor("pg_other", "Other")
        oc = client_for(other, other_shop)
        enable_gst(oc, gstin=GSTIN_DELHI_2)
        self.assertEqual(oc.patch(self.url, {"gst_rate": "28"}, format="json").status_code, 404)
        self.assertIsNone(ShopProduct.objects.get(pk=self.sp).gst_rate)
