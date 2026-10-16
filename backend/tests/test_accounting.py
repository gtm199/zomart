import uuid
from decimal import Decimal

from django.utils import timezone
from rest_framework.test import APITestCase

from .helpers import API, add_listing, checkout, client_for, make_master, make_vendor


class AccountingTests(APITestCase):
    def setUp(self):
        self.user, self.shop = make_vendor("acc_owner", "Acc Shop")
        self.c = client_for(self.user, self.shop)
        self.listing = add_listing(self.c, make_master(), price="105.00", cost="60.00", stock="10")["id"]
        self.today = str(timezone.localdate())
        self.range = f"from={self.today}&to={self.today}"

    def sell(self, qty="2", paid="210.00", customer=None):
        payments = [{"method": "cash", "amount": paid}] if paid and paid != "0" else []
        return checkout(self.c, self.listing, qty=qty, payments=payments, customer=customer)

    def expense(self, category="Rent", amount="30.00", method="cash"):
        return self.c.post(f"{API}/shop/expenses/", {"category": category, "amount": amount, "method": method}, format="json")

    def test_expense_categories_are_reused_and_void_removes_from_reports(self):
        e1 = self.expense("Rent")
        self.expense("rent", "20.00")
        self.assertEqual(e1.status_code, 201, e1.data)
        listing = self.c.get(f"{API}/shop/expenses/").data["results"]
        self.assertEqual({e["category"] for e in listing}, {"Rent"})
        self.c.post(f"{API}/shop/expenses/{e1.data['id']}/void/")
        pl = self.c.get(f"{API}/shop/reports/profit-loss/?{self.range}").data
        self.assertEqual(Decimal(pl["expenses_total"]), Decimal("20.00"))

    def test_net_profit_is_gross_profit_minus_expenses(self):
        self.sell()                    # 2 x 105 = 210 incl 10 tax -> ex-tax 200, cost 120
        self.expense("Rent", "30.00")
        pl = self.c.get(f"{API}/shop/reports/profit-loss/?{self.range}").data
        self.assertEqual(Decimal(pl["net_sales"]), Decimal("210.00"))
        self.assertEqual(Decimal(pl["cost_of_goods_sold"]), Decimal("120.00"))
        self.assertEqual(Decimal(pl["gross_profit"]), Decimal("80.00"))
        self.assertEqual(Decimal(pl["net_profit"]), Decimal("50.00"))
        self.assertEqual(Decimal(pl["money_collected_by_method"]["cash"]), Decimal("210.00"))

    def test_returns_reduce_reported_profit(self):
        sale = self.sell().data
        self.c.post(f"{API}/shop/sales/{sale['id']}/return/",
                    {"items": [{"sale_item": sale["items"][0]["id"], "quantity": "1"}]}, format="json")
        pl = self.c.get(f"{API}/shop/reports/profit-loss/?{self.range}").data
        self.assertEqual(Decimal(pl["net_sales"]), Decimal("105.00"))
        self.assertEqual(Decimal(pl["gross_profit"]), Decimal("40.00"))

    def test_sales_analysis_top_sellers_and_slow_movers(self):
        slow = add_listing(self.c, make_master("Slow Dal", barcode=None), price="50.00", cost="40.00", stock="4")["id"]
        self.sell()
        r = self.c.get(f"{API}/shop/reports/sales-analysis/?{self.range}").data
        self.assertEqual(r["top_sellers"][0]["quantity"], "2")
        self.assertEqual(Decimal(r["top_sellers"][0]["profit"]), Decimal("80.00"))
        self.assertTrue(any("Slow Dal" in s["product"] for s in r["slow_movers"]))
        csv = self.c.get(f"{API}/shop/reports/sales-analysis/?{self.range}&export=csv")
        self.assertEqual(csv.status_code, 200)
        self.assertIn("text/csv", csv["Content-Type"])

    def test_receivables_and_payables_ageing(self):
        cust = self.c.post(f"{API}/shop/customers/", {"name": "Ramesh", "phone": "9000000009"}, format="json").data["id"]
        self.sell(qty="1", paid="5.00", customer=cust)  # 100 on credit
        sup = self.c.post(f"{API}/shop/suppliers/", {"name": "Delhi Traders"}, format="json").data["id"]
        self.c.post(f"{API}/shop/purchases/", {"client_txn_id": str(uuid.uuid4()), "supplier": sup,
                    "items": [{"shop_product": self.listing, "quantity": "10", "unit_cost": "50"}], "payments": []}, format="json")
        a = self.c.get(f"{API}/shop/reports/ageing/").data
        self.assertEqual(Decimal(a["receivables"]["total"]), Decimal("100.00"))
        self.assertEqual(Decimal(a["receivables"]["buckets"]["0-30 days"]), Decimal("100.00"))
        self.assertEqual(Decimal(a["payables"]["total"]), Decimal("500.00"))
        self.assertEqual(a["receivables"]["rows"][0]["name"], "Ramesh")

    def test_cash_close_expected_cash_and_difference(self):
        self.sell()                    # +210 cash
        self.expense("Tea", "30.00")   # -30 cash
        self.expense("Electricity", "100.00", method="upi")  # not cash
        pos = self.c.get(f"{API}/shop/cash-close/").data["position"]
        self.assertEqual(Decimal(pos["expected_cash"]), Decimal("180.00"))
        r = self.c.post(f"{API}/shop/cash-close/", {"counted_cash": "275", "opening_cash": "100"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(Decimal(r.data["expected_cash"]), Decimal("280.00"))
        self.assertEqual(Decimal(r.data["difference"]), Decimal("-5.00"))
        again = self.c.post(f"{API}/shop/cash-close/", {"counted_cash": "275"}, format="json")
        self.assertEqual(again.data["code"], "already_closed")

    def test_isolation_roles_and_bad_dates(self):
        other, shop_b = make_vendor("acc_other", "Other Shop")
        b = client_for(other, shop_b)
        self.expense()
        self.assertEqual(b.get(f"{API}/shop/expenses/").data["count"], 0)
        self.assertEqual(Decimal(b.get(f"{API}/shop/reports/profit-loss/").data["expenses_total"]), Decimal("0.00"))
        cashier, _ = make_vendor("acc_cashier", role="cashier", shop=self.shop)
        cc = client_for(cashier, self.shop)
        self.assertEqual(cc.get(f"{API}/shop/expenses/").status_code, 403)
        self.assertEqual(cc.get(f"{API}/shop/reports/ageing/").status_code, 403)
        self.assertEqual(self.c.get(f"{API}/shop/reports/profit-loss/?from=2026-13-40").data["code"], "invalid_date")

    def test_expense_csv_export(self):
        self.expense("Salary", "5000.00")
        r = self.c.get(f"{API}/shop/expenses/?export=csv")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Salary", r.content.decode("utf-8"))