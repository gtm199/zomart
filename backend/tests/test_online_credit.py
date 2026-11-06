import uuid
from decimal import Decimal

from rest_framework.test import APITestCase

from apps.customers.models import Customer, CustomerLedger

from .helpers import API, add_listing, client_for, make_master, make_vendor
from .test_orders import register_shopper


class OnlineCreditTests(APITestCase):
    def setUp(self):
        self.owner, self.shop = make_vendor("cr_owner", "Credit Shop")
        self.v = client_for(self.owner, self.shop)
        self.sp = add_listing(self.v, make_master("Soap", barcode=None, pack="1"), price="100.00", cost="60.00", stock="50")["id"]
        self.v.patch(f"{API}/shop/store-settings/", {"store_enabled": True, "accepts_delivery": True, "accepts_pickup": True,
                                                   "delivery_fee": "20.00", "min_order": "0"}, format="json")
        self.s = register_shopper()

    # ----- helpers -----
    def ask(self, client=None):
        return (client or self.s).post(f"{API}/store/credit/request/", {"shop": self.shop.id}, format="json")

    def approve(self, credit_id, limit="500", **extra):
        return self.v.post(f"{API}/shop/credit-requests/{credit_id}/approve/", dict(limit=limit, **extra), format="json")

    def give_credit(self, limit="500"):
        self.ask()
        r = self.v.get(f"{API}/shop/credit-requests/?status=requested").data["results"][0]
        return self.approve(r["id"], limit)

    def place(self, qty="1", payment="credit", fulfilment="pickup", client=None):
        return (client or self.s).post(f"{API}/store/orders/", {
            "shop": self.shop.id, "client_txn_id": str(uuid.uuid4()), "fulfilment": fulfilment, "address": "12 Gandhi Road, Etawah",
            "payment_method": payment, "items": [{"shop_product": self.sp, "quantity": qty}]}, format="json")

    def hand_over(self, order_id):
        for step in ("accept", "pack", "ready", "complete"):
            r = self.v.post(f"{API}/shop/orders/{order_id}/{step}/", {}, format="json")
            self.assertEqual(r.status_code, 200, (step, r.data))
        return r

    def mine(self):
        return self.s.get(f"{API}/store/credit/").data[0]

    # ----- asking and approving -----
    def test_request_then_approve_links_a_new_customer_with_a_limit(self):
        self.assertEqual(self.ask().data["status"], "requested")
        row = self.v.get(f"{API}/shop/credit-requests/?status=requested").data["results"][0]
        self.assertEqual((row["shopper_phone"], row["same_phone_customer"]), ("9876543210", None))
        done = self.approve(row["id"], "500")
        self.assertEqual(done.status_code, 200, done.data)
        customer = Customer.objects.get(shop=self.shop, phone="9876543210")
        self.assertEqual(customer.credit_limit, Decimal("500"))
        me = self.mine()
        self.assertEqual((me["status"], me["limit"], me["owed"], me["available"]), ("approved", "500.00", "0.00", "500.00"))
        self.approve(row["id"], "800")  # the limit can be changed later
        self.assertEqual(Customer.objects.filter(shop=self.shop).count(), 1)
        self.assertEqual(self.mine()["limit"], "800.00")

    def test_an_existing_customer_with_the_same_number_is_only_linked_on_purpose(self):
        existing = Customer.objects.create(shop=self.shop, name="Old Customer", phone="9876543210", balance=Decimal("120"))
        self.ask()
        row = self.v.get(f"{API}/shop/credit-requests/?status=requested").data["results"][0]
        self.assertEqual(row["same_phone_customer"]["owed"], "120.00")
        self.assertEqual(self.approve(row["id"]).data["code"], "customer_exists")   # never linked automatically
        self.assertEqual(self.approve(row["id"], customer=existing.id).status_code, 200)
        self.assertEqual(self.mine()["owed"], "120.00")
        other = register_shopper("Raju", "9123456780")
        self.ask(other)
        row2 = [r for r in self.v.get(f"{API}/shop/credit-requests/?status=requested").data["results"]][0]
        self.assertEqual(self.approve(row2["id"], customer=existing.id).data["code"], "already_linked")

    def test_only_owner_or_manager_gives_credit(self):
        self.ask()
        rid = self.v.get(f"{API}/shop/credit-requests/").data["results"][0]["id"]
        cashier, _ = make_vendor("cr_cashier", role="cashier", shop=self.shop)
        cc = client_for(cashier, self.shop)
        self.assertEqual(cc.get(f"{API}/shop/credit-requests/").status_code, 200)
        self.assertEqual(cc.post(f"{API}/shop/credit-requests/{rid}/approve/", {"limit": "100"}, format="json").status_code, 403)
        self.assertEqual(self.v.post(f"{API}/shop/credit-requests/{rid}/decline/", {}, format="json").data["status"], "declined")
        self.assertEqual(self.ask().data["status"], "requested")  # a declined customer may ask again

    # ----- ordering on credit -----
    def test_credit_orders_need_approval_and_respect_the_limit(self):
        self.assertEqual(self.place().data["code"], "credit_not_approved")
        self.ask()
        self.assertEqual(self.place().data["code"], "credit_not_approved")          # asked, not approved yet
        self.give_credit("250")
        first = self.place(qty="2")                                                  # 200 promised
        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(self.mine()["available"], "50.00")
        self.assertEqual(self.place(qty="1").data["code"], "credit_limit_exceeded")  # 100 > 50 left
        self.hand_over(first.data["id"])
        self.assertEqual(Customer.objects.get(phone="9876543210").balance, Decimal("200"))
        self.assertEqual(self.mine()["available"], "50.00")
        self.v.post(f"{API}/shop/customers/{Customer.objects.get(phone='9876543210').id}/receive-payment/",
                    {"amount": "150", "method": "cash", "note": "private remark"}, format="json")
        self.assertEqual(self.mine()["available"], "200.00")
        self.assertEqual(self.place(qty="2").status_code, 201)

    def test_the_delivery_fee_is_not_put_on_the_account(self):
        self.give_credit("500")
        order = self.place(qty="1", fulfilment="delivery").data
        self.assertEqual(Decimal(order["total"]), Decimal("120.00"))
        self.hand_over(order["id"])
        self.assertEqual(Customer.objects.get(phone="9876543210").balance, Decimal("100"))  # items only

    def test_the_customer_sees_their_own_account_and_nobody_elses(self):
        self.give_credit("500")
        self.hand_over(self.place(qty="1").data["id"])
        cid = Customer.objects.get(phone="9876543210").id
        self.v.post(f"{API}/shop/customers/{cid}/receive-payment/", {"amount": "40", "method": "cash", "note": "private remark"}, format="json")
        rows = self.s.get(f"{API}/store/credit/{self.shop.id}/ledger/").data
        self.assertEqual([r["entry_type"] for r in rows], ["payment", "credit_sale"])
        self.assertTrue(rows[1]["note"].startswith("INV-"))
        self.assertEqual(rows[0]["note"], "")                      # the shop's private note is never shown
        self.assertEqual(Decimal(rows[0]["balance_after"]), Decimal("60"))
        stranger = register_shopper("Stranger", "9012345678")
        self.assertEqual(stranger.get(f"{API}/store/credit/{self.shop.id}/ledger/").data, [])
        self.assertEqual(stranger.get(f"{API}/store/credit/").data, [])

    def test_suspending_stops_new_credit_but_keeps_the_dues_visible(self):
        self.give_credit("500")
        self.hand_over(self.place(qty="2").data["id"])
        rid = self.v.get(f"{API}/shop/credit-requests/?status=approved").data["results"][0]["id"]
        self.assertEqual(self.v.post(f"{API}/shop/credit-requests/{rid}/suspend/", {}, format="json").data["status"], "suspended")
        self.assertEqual(self.place().data["code"], "credit_not_approved")
        me = self.mine()
        self.assertEqual((me["status"], me["owed"]), ("suspended", "200.00"))

    def test_cancelled_credit_orders_leave_nothing_on_the_account(self):
        self.give_credit("500")
        order = self.place(qty="3").data
        self.assertEqual(self.mine()["reserved"], "300.00")
        self.s.post(f"{API}/store/orders/{order['id']}/cancel/")
        me = self.mine()
        self.assertEqual((me["reserved"], me["owed"]), ("0.00", "0.00"))
        self.assertEqual(CustomerLedger.objects.count(), 0)

    def test_cash_orders_still_work_without_credit(self):
        self.assertEqual(self.place(payment="cash").status_code, 201)