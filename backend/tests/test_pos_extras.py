import uuid
from decimal import Decimal

from rest_framework.test import APITestCase

from apps.inventory.models import ShopProduct

from .helpers import API, EAN_ATTA, add_listing, checkout, client_for, make_master, make_vendor


class LooseItemTests(APITestCase):
    def setUp(self):
        self.user, self.shop = make_vendor("loose_owner", "Loose Shop")
        self.c = client_for(self.user, self.shop)
        sugar = make_master("Loose Sugar", barcode=None, unit="kg", pack="1")
        sugar.is_loose = True
        sugar.save()
        self.sugar = add_listing(self.c, sugar, price="60.00", cost="45.00", stock="10")["id"]
        self.soap = add_listing(self.c, make_master("Soap", barcode=EAN_ATTA, pack="1"), price="30.00", cost="20.00", stock="10")["id"]

    def test_quarter_kilo_sale_takes_the_right_stock_and_price(self):
        r = checkout(self.c, self.sugar, qty="0.250", payments=[{"method": "cash", "amount": "15.00"}])
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(Decimal(r.data["total"]), Decimal("15.00"))
        self.assertEqual(r.data["items"][0]["unit"], "kg")
        self.assertEqual(ShopProduct.objects.get(pk=self.sugar).stock_qty, Decimal("9.750"))
        text = self.c.get(f"{API}/shop/sales/{r.data['id']}/receipt/").data["text"]
        self.assertIn("kg", text)

    def test_amount_style_sale_rounds_to_the_paisa(self):
        # Rs 50 of sugar at Rs 60 a kg is 0.833 kg, which is Rs 49.98 once rounded
        r = checkout(self.c, self.sugar, qty="0.833", payments=[{"method": "cash", "amount": "49.98"}])
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(Decimal(r.data["total"]), Decimal("49.98"))

    def test_piece_items_stay_whole_and_have_no_unit_on_the_bill(self):
        self.assertEqual(checkout(self.c, self.soap, qty="0.5", payments=[{"method": "cash", "amount": "15"}]).data["code"], "invalid_quantity")
        r = checkout(self.c, self.soap, qty="2", payments=[{"method": "cash", "amount": "60.00"}])
        self.assertEqual(r.data["items"][0]["unit"], "")

    def test_sync_tells_the_phone_which_items_are_sold_by_weight(self):
        products = {p["id"]: p for p in self.c.get(f"{API}/shop/sync/").data["products"]}
        self.assertEqual((products[self.sugar]["unit"], products[self.sugar]["loose"]), ("kg", True))
        self.assertFalse(products[self.soap]["loose"])


class CreditLimitTests(APITestCase):
    def setUp(self):
        self.user, self.shop = make_vendor("limit_owner", "Limit Shop")
        self.c = client_for(self.user, self.shop)
        self.sp = add_listing(self.c, make_master(), price="300.00", cost="200.00", stock="20")["id"]
        r = self.c.post(f"{API}/shop/customers/", {"name": "Meena", "phone": "9000000066", "credit_limit": "1000"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.cust = r.data["id"]

    def test_online_credit_sale_over_the_limit_is_refused(self):
        self.assertEqual(checkout(self.c, self.sp, qty="3", payments=[], customer=self.cust).status_code, 201)   # 900
        r = checkout(self.c, self.sp, qty="1", payments=[], customer=self.cust)                                  # would be 1200
        self.assertEqual((r.status_code, r.data["code"]), (409, "credit_limit"))
        self.assertEqual(Decimal(self.c.get(f"{API}/shop/customers/{self.cust}/").data["balance"]), Decimal("900.00"))

    def test_bill_made_on_the_phone_is_accepted_but_flagged(self):
        body = {"client_txn_id": str(uuid.uuid4()), "offline": True, "customer": self.cust,
                "items": [{"shop_product": self.sp, "quantity": "4", "unit_price": "300.00"}], "payments": []}
        r = self.c.post(f"{API}/shop/sales/", body, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(r.data["needs_review"])
        self.assertIn("over the credit limit", r.data["review_note"])

    def test_limit_is_shared_with_the_phone_and_only_owner_or_manager_may_set_it(self):
        sync = self.c.get(f"{API}/shop/sync/").data
        self.assertEqual(sync["customers"][0]["credit_limit"], "1000.00")
        cashier, _ = make_vendor("limit_cashier", role="cashier", shop=self.shop)
        cc = client_for(cashier, self.shop)
        self.assertEqual(cc.patch(f"{API}/shop/customers/{self.cust}/", {"credit_limit": "99999"}, format="json").status_code, 403)
        self.assertEqual(cc.post(f"{API}/shop/customers/", {"name": "Walk-in", "phone": "9000000067"}, format="json").status_code, 201)
        self.assertEqual(cc.post(f"{API}/shop/customers/", {"name": "Sneaky", "phone": "9000000068", "credit_limit": "5"}, format="json").status_code, 403)
        manager, _ = make_vendor("limit_manager", role="manager", shop=self.shop)
        self.assertEqual(client_for(manager, self.shop).patch(f"{API}/shop/customers/{self.cust}/", {"credit_limit": "2000"}, format="json").status_code, 200)

    def test_customers_without_a_limit_are_not_restricted(self):
        free = self.c.post(f"{API}/shop/customers/", {"name": "Regular", "phone": "9000000069"}, format="json").data["id"]
        self.assertEqual(checkout(self.c, self.sp, qty="10", payments=[], customer=free).status_code, 201)


class PastBillSearchTests(APITestCase):
    def test_search_by_invoice_number_and_customer_name(self):
        user, shop = make_vendor("search_owner", "Search Shop")
        c = client_for(user, shop)
        sp = add_listing(c, make_master(), price="100.00", stock="5")["id"]
        cust = c.post(f"{API}/shop/customers/", {"name": "Kamla Devi", "phone": "9000000070"}, format="json").data["id"]
        checkout(c, sp, qty="1", payments=[{"method": "cash", "amount": "100.00"}], customer=cust)
        self.assertEqual(c.get(f"{API}/shop/sales/?search=000001").data["count"], 1)
        self.assertEqual(c.get(f"{API}/shop/sales/?search=kamla").data["count"], 1)
        self.assertEqual(c.get(f"{API}/shop/sales/?search=zzz").data["count"], 0)