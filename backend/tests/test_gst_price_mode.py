"""Shop-wide GST price mode: prices include GST (default, MRP style) or GST is added on top (exclusive).
Each product can still differ. Bills already made never change. Includes the MRP warning (Legal Metrology)."""
from decimal import Decimal

from rest_framework.test import APITestCase

from apps.inventory.models import ShopProduct
from apps.sales.models import Sale

from .helpers import API, add_listing, client_for, make_master, make_vendor
from .test_gst import GST, GSTIN_DELHI_2, enable_gst
from .test_gst_billing import sell

D = Decimal


class GstPriceModeTests(APITestCase):
    def setUp(self):
        self.owner, self.shop = make_vendor("pm_owner", "Mode Shop")
        self.c = client_for(self.owner, self.shop)
        enable_gst(self.c)
        self.rice = add_listing(self.c, make_master("Rice", "IndiaGate", None, tax="5.00"), price="100.00", stock="20")["id"]
        self.c.patch(f"{API}/shop/products/{self.rice}/", {"gst_rate": "5"}, format="json")

    def url(self, sp):
        return f"{API}/shop/products/{sp}/"

    def test_default_is_inclusive_and_existing_behaviour_is_unchanged(self):
        g = self.c.get(GST).data
        self.assertEqual(g["gst_price_mode"], "inclusive")
        self.assertIn("MRP", g["mrp_note"])
        self.assertTrue(ShopProduct.objects.get(pk=self.rice).price_includes_gst)
        r = sell(self.c, [(self.rice, "1", "0")], [{"method": "cash", "amount": "100.00"}])
        self.assertEqual((D(r.data["total"]), D(r.data["taxable_total"])), (D("100.00"), D("95.24")))

    def test_switching_mode_alone_changes_only_new_products(self):
        r = self.c.patch(GST, {"gst_price_mode": "exclusive"}, format="json")
        self.assertEqual((r.status_code, r.data["gst_price_mode"]), (200, "exclusive"))
        self.assertTrue(ShopProduct.objects.get(pk=self.rice).price_includes_gst)        # existing product untouched
        new = add_listing(self.c, make_master("Oil", "Fortune", None), price="200.00")
        self.assertFalse(new["price_includes_gst"])                                      # new product follows the shop
        chosen = self.c.post(f"{API}/shop/products/", {"master_product": make_master("Dal", "Tata", None).id,
                             "selling_price": "90.00", "price_includes_gst": True}, format="json").data
        self.assertTrue(chosen["price_includes_gst"])                                    # an explicit choice wins

    def test_apply_to_all_products_and_bill_adds_gst_on_top(self):
        before = ShopProduct.objects.get(pk=self.rice).updated_at
        r = self.c.patch(GST, {"gst_price_mode": "exclusive", "apply_price_mode_to_all": True}, format="json")
        self.assertEqual((r.data["products_tax_on_top"], r.data["products_count"]), (1, 1))
        sp = ShopProduct.objects.get(pk=self.rice)
        self.assertFalse(sp.price_includes_gst)
        self.assertGreater(sp.updated_at, before)                                       # phones re-download it
        bill = sell(self.c, [(self.rice, "2", "0")], [{"method": "cash", "amount": "210.00"}])
        self.assertEqual(bill.status_code, 201, bill.data)
        self.assertEqual((D(bill.data["total"]), D(bill.data["taxable_total"]), D(bill.data["cgst_total"])),
                         (D("210.00"), D("200.00"), D("5.00")))
        self.assertFalse(bill.data["items"][0]["price_includes_gst"])

    def test_back_to_inclusive_never_changes_old_bills(self):
        self.c.patch(GST, {"gst_price_mode": "exclusive", "apply_price_mode_to_all": True}, format="json")
        old = sell(self.c, [(self.rice, "1", "0")], [{"method": "cash", "amount": "105.00"}]).data
        self.c.patch(GST, {"gst_price_mode": "inclusive", "apply_price_mode_to_all": True}, format="json")
        self.assertTrue(ShopProduct.objects.get(pk=self.rice).price_includes_gst)
        new = sell(self.c, [(self.rice, "1", "0")], [{"method": "cash", "amount": "100.00"}]).data
        self.assertEqual((D(new["total"]), new["items"][0]["price_includes_gst"]), (D("100.00"), True))
        saved = Sale.objects.get(pk=old["id"])
        self.assertEqual((saved.total, saved.items.get().price_includes_gst), (D("105.00"), False))

    def test_customer_price_and_mrp_warning(self):
        master = make_master("Ghee", "Amul", None, tax="12.00")
        master.mrp = D("500.00")
        master.save()
        sp = add_listing(self.c, master, price="500.00")["id"]
        self.c.patch(self.url(sp), {"gst_rate": "12"}, format="json")
        inc = self.c.get(self.url(sp)).data
        self.assertEqual((inc["customer_price"], inc["mrp"], inc["above_mrp"]), ("500.00", "500.00", False))
        self.c.patch(self.url(sp), {"price_includes_gst": False}, format="json")
        exc = self.c.get(self.url(sp)).data
        self.assertEqual((exc["customer_price"], exc["above_mrp"]), ("560.00", True))   # 500 + 12% is above MRP
        self.c.patch(self.url(sp), {"selling_price": "446.43"}, format="json")
        paisa = self.c.get(self.url(sp)).data
        self.assertEqual((paisa["customer_price"], paisa["above_mrp"]), ("500.01", True))  # CGST/SGST 26.79 each: 1 paisa over
        self.c.patch(self.url(sp), {"selling_price": "446.42"}, format="json")
        ok = self.c.get(self.url(sp)).data
        self.assertEqual((ok["customer_price"], ok["above_mrp"]), ("500.00", False))    # 446.42 + 2 x 26.79 = 500.00

    def test_composition_shop_charges_no_gst_whatever_the_mode(self):
        self.c.patch(GST, {"gst_scheme": "composition", "gst_price_mode": "exclusive", "apply_price_mode_to_all": True},
                     format="json")
        r = sell(self.c, [(self.rice, "1", "0")], [{"method": "cash", "amount": "100.00"}])
        self.assertEqual((r.data["document_type"], D(r.data["total"]), D(r.data["tax_total"])),
                         ("bill_of_supply", D("100.00"), D("0")))
        self.assertEqual(self.c.get(self.url(self.rice)).data["customer_price"], "100.00")

    def test_only_owner_changes_mode_and_only_for_own_shop(self):
        manager, _ = make_vendor("pm_mgr", role="manager", shop=self.shop)
        self.assertEqual(client_for(manager, self.shop).patch(GST, {"gst_price_mode": "exclusive"},
                                                              format="json").status_code, 403)
        self.assertEqual(self.c.patch(GST, {"gst_price_mode": "both"}, format="json").status_code, 400)
        other, other_shop = make_vendor("pm_other", "Other")
        oc = client_for(other, other_shop)
        enable_gst(oc, gstin=GSTIN_DELHI_2)
        oc.patch(GST, {"gst_price_mode": "exclusive", "apply_price_mode_to_all": True}, format="json")
        self.assertTrue(ShopProduct.objects.get(pk=self.rice).price_includes_gst)        # my products untouched
        self.assertEqual(self.c.get(GST).data["gst_price_mode"], "inclusive")
