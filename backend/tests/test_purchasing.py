import uuid
from decimal import Decimal

from rest_framework.test import APITestCase

from apps.inventory.models import ShopProduct, StockMovement
from apps.suppliers.models import SupplierLedger, SupplierPayment

from .helpers import API, add_listing, client_for, make_master, make_vendor


class PurchasingTests(APITestCase):
    def setUp(self):
        self.user, self.shop = make_vendor("buyer", "Buyer Shop")
        self.c = client_for(self.user, self.shop)
        self.master = make_master()
        self.sp = add_listing(self.c, self.master, price="100.00", cost="60.00", stock="10")["id"]
        self.sup = self.c.post(f"{API}/shop/suppliers/", {"name": "Agra Traders", "phone": "9811111111"}, format="json").data["id"]

    def buy(self, qty="20", cost="58.00", paid="500.00", txn=None, supplier=None, client=None, sp=None):
        body = {
            "client_txn_id": str(txn or uuid.uuid4()), "supplier": supplier or self.sup, "invoice_number": "INV-9",
            "items": [{"shop_product": sp or self.sp, "quantity": qty, "unit_cost": cost}],
            "payments": [{"method": "cash", "amount": paid}] if paid else [],
        }
        return (client or self.c).post(f"{API}/shop/purchases/", body, format="json")

    def stock(self):
        return ShopProduct.objects.get(pk=self.sp).stock_qty

    def test_goods_receipt_updates_stock_cost_and_supplier_balance(self):
        r = self.buy()
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(Decimal(r.data["total"]), Decimal("1160.00"))
        self.assertEqual(Decimal(r.data["amount_due"]), Decimal("660.00"))
        sp = ShopProduct.objects.get(pk=self.sp)
        self.assertEqual(sp.stock_qty, Decimal("30"))
        self.assertEqual(sp.purchase_cost, Decimal("58.00"))
        self.assertEqual(StockMovement.objects.filter(movement_type="purchase", shop_product=sp).count(), 1)
        self.assertEqual(Decimal(self.c.get(f"{API}/shop/suppliers/{self.sup}/").data["balance"]), Decimal("660.00"))
        self.assertEqual(SupplierLedger.objects.get().entry_type, "purchase")

    def test_purchase_is_idempotent(self):
        txn = uuid.uuid4()
        r1, r2 = self.buy(txn=txn), self.buy(txn=txn)
        self.assertEqual((r1.status_code, r2.status_code), (201, 200))
        self.assertEqual(r1.data["id"], r2.data["id"])
        self.assertEqual(self.stock(), Decimal("30"))

    def test_invalid_purchases_change_nothing(self):
        self.assertEqual(self.buy(paid="5000").data["code"], "overpayment")
        self.assertEqual(self.buy(qty="1.5").data["code"], "invalid_quantity")  # pieces are whole
        self.assertEqual(self.stock(), Decimal("10"))
        self.assertEqual(SupplierPayment.objects.count(), 0)

    def test_paying_the_supplier_reduces_balance(self):
        self.buy()
        r = self.c.post(f"{API}/shop/suppliers/{self.sup}/pay/", {"amount": "160", "method": "upi"}, format="json")
        self.assertEqual(Decimal(r.data["balance"]), Decimal("500.00"))
        over = self.c.post(f"{API}/shop/suppliers/{self.sup}/pay/", {"amount": "9999", "method": "cash"}, format="json")
        self.assertEqual(over.status_code, 400)
        self.assertEqual(list(SupplierLedger.objects.order_by("id").values_list("entry_type", flat=True)), ["purchase", "payment"])

    def test_purchase_return_partial_and_full(self):
        p = self.buy().data
        item = p["items"][0]["id"]
        r = self.c.post(f"{API}/shop/purchases/{p['id']}/return/", {"items": [{"purchase_item": item, "quantity": "5"}]}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "partially_returned")
        self.assertEqual(self.stock(), Decimal("25"))
        self.assertEqual(Decimal(self.c.get(f"{API}/shop/suppliers/{self.sup}/").data["balance"]), Decimal("370.00"))  # 660 - 290
        r = self.c.post(f"{API}/shop/purchases/{p['id']}/return/", {"items": [{"purchase_item": item, "quantity": "15"}]}, format="json")
        self.assertEqual(r.data["status"], "returned")
        self.assertEqual(Decimal(self.c.get(f"{API}/shop/suppliers/{self.sup}/").data["balance"]), Decimal("0.00"))
        self.assertEqual(SupplierPayment.objects.get(kind="refund").amount, Decimal("-500.00"))  # 1160 returned, 660 was owed

    def test_cannot_return_goods_that_were_already_sold(self):
        p = self.buy().data
        self.c.post(f"{API}/shop/products/{self.sp}/adjust-stock/", {"quantity_delta": "-25", "movement_type": "adjustment"}, format="json")
        r = self.c.post(f"{API}/shop/purchases/{p['id']}/return/",
                        {"items": [{"purchase_item": p["items"][0]["id"], "quantity": "20"}]}, format="json")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.stock(), Decimal("5"))

    def test_stock_valuation_report(self):
        self.buy()  # 30 pcs at cost 58
        r = self.c.get(f"{API}/shop/reports/stock-valuation/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Decimal(r.data["stock_value"]), Decimal("1740.00"))
        self.assertEqual(Decimal(r.data["payables_to_suppliers"]), Decimal("660.00"))

    def test_duplicate_supplier_name_is_refused(self):
        r = self.c.post(f"{API}/shop/suppliers/", {"name": "agra traders"}, format="json")
        self.assertEqual(r.status_code, 400)


class PurchasingIsolationAndRoleTests(APITestCase):
    def setUp(self):
        self.ua, self.shop_a = make_vendor("a_owner", "Shop A")
        self.ub, self.shop_b = make_vendor("b_owner", "Shop B")
        self.a, self.b = client_for(self.ua, self.shop_a), client_for(self.ub, self.shop_b)
        master = make_master()
        self.sp_a = add_listing(self.a, master, stock="5")["id"]
        self.sp_b = add_listing(self.b, master, stock="5")["id"]
        self.sup_a = self.a.post(f"{API}/shop/suppliers/", {"name": "Common Supplier"}, format="json").data["id"]

    def body(self, supplier, sp):
        return {"client_txn_id": str(uuid.uuid4()), "supplier": supplier,
                "items": [{"shop_product": sp, "quantity": "1", "unit_cost": "10"}], "payments": []}

    def test_vendor_b_cannot_see_or_use_vendor_a_suppliers(self):
        self.assertEqual(self.b.get(f"{API}/shop/suppliers/{self.sup_a}/").status_code, 404)
        self.assertEqual(self.b.get(f"{API}/shop/suppliers/").data["count"], 0)
        r = self.b.post(f"{API}/shop/purchases/", self.body(self.sup_a, self.sp_b), format="json")
        self.assertEqual(r.data["code"], "supplier_not_found")
        # same supplier name is fine for another vendor
        self.assertEqual(self.b.post(f"{API}/shop/suppliers/", {"name": "Common Supplier"}, format="json").status_code, 201)

    def test_vendor_cannot_receive_stock_into_another_shops_product(self):
        sup_b = self.b.post(f"{API}/shop/suppliers/", {"name": "B Supplier"}, format="json").data["id"]
        r = self.b.post(f"{API}/shop/purchases/", self.body(sup_b, self.sp_a), format="json")
        self.assertEqual(r.data["code"], "product_not_found")

    def test_roles(self):
        cashier, _ = make_vendor("cash1", role="cashier", shop=self.shop_a)
        inv, _ = make_vendor("inv1", role="inventory", shop=self.shop_a)
        self.assertEqual(client_for(cashier, self.shop_a).get(f"{API}/shop/suppliers/").status_code, 403)
        ci = client_for(inv, self.shop_a)
        self.assertEqual(ci.get(f"{API}/shop/suppliers/").status_code, 200)
        self.assertEqual(ci.post(f"{API}/shop/purchases/", self.body(self.sup_a, self.sp_a), format="json").status_code, 201)
        self.assertEqual(ci.get(f"{API}/shop/reports/stock-valuation/").status_code, 403)