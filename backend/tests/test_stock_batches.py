"""Batch and expiry tracking: each dated lot is a batch; sales take undated stock first, then the earliest expiry;
the product's expiry date follows its batches, so it never goes stale."""
import uuid
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone
from rest_framework.test import APITestCase

from apps.inventory.models import ShopProduct, StockBatch, StockMovement
from services import inventory_service

from .helpers import API, add_listing, client_for, make_master, make_vendor

D = Decimal


class BatchTests(APITestCase):
    def setUp(self):
        self.user, self.shop = make_vendor("batch_owner", "Batch Shop")
        self.c = client_for(self.user, self.shop)
        self.sp = add_listing(self.c, make_master("Milk Bread", barcode=None), stock="0")["id"]
        self.sup = self.c.post(f"{API}/shop/suppliers/", {"name": "Batch Supplier"}, format="json").data["id"]
        self.today = timezone.localdate()

    def day(self, n):
        return self.today + timedelta(days=n)

    def buy(self, qty, days, batch_no=""):
        item = {"shop_product": self.sp, "quantity": str(qty), "unit_cost": "20"}
        if days is not None:
            item.update(expiry_date=str(self.day(days)), batch_no=batch_no)
        r = self.c.post(f"{API}/shop/purchases/", {"client_txn_id": str(uuid.uuid4()), "supplier": self.sup,
                                                   "payments": [], "items": [item]}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        return r.data

    def sell(self, qty):
        inventory_service.apply_movement(shop_product_id=self.sp, delta=-D(qty), movement_type=StockMovement.Type.SALE)

    def product(self):
        return self.c.get(f"{API}/shop/products/{self.sp}/").data

    def batches(self):
        return self.c.get(f"{API}/shop/products/{self.sp}/batches/").data

    def left(self):
        return [(b["expiry_date"], D(b["quantity_left"])) for b in self.batches()["batches"]]

    def test_each_lot_is_a_batch_and_the_date_moves_on_when_the_old_lot_is_sold(self):
        self.buy(5, 10, "OLD-1")
        self.buy(10, 90, "NEW-2")
        p = self.product()
        self.assertEqual((p["expiry_date"], D(p["expiry_qty"]), p["batches_count"]), (str(self.day(10)), D("5"), 2))
        self.sell(6)                                   # FEFO: the 5 old pieces go, then 1 of the new lot
        self.assertEqual(self.left(), [(str(self.day(90)), D("9"))])
        self.assertEqual(self.product()["expiry_date"], str(self.day(90)))   # the old date is gone: no false alert
        self.assertEqual(self.product()["expiry_status"], "ok")

    def test_undated_stock_is_sold_first_so_dated_stock_is_never_forgotten(self):
        self.buy(4, 5)
        self.buy(6, None)                              # no date given
        self.assertEqual(self.batches()["undated_qty"], "6.000")
        self.sell(6)
        self.assertEqual(self.left(), [(str(self.day(5)), D("4"))])
        self.sell(1)
        self.assertEqual(self.left(), [(str(self.day(5)), D("3"))])
        self.assertEqual(D(ShopProduct.objects.get(pk=self.sp).stock_qty), D("3"))

    def test_write_off_takes_that_batch_and_lowers_stock(self):
        self.buy(5, -2)                                # already expired
        self.buy(10, 60)
        a = self.c.get(f"{API}/shop/products/expiry-alerts/").data
        self.assertEqual(a["expired_count"], 1)
        old = self.batches()["batches"][0]
        r = self.c.post(f"{API}/shop/products/{self.sp}/batches/{old['id']}/write-off/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(D(r.data["product"]["stock_qty"]), D("10"))
        self.assertEqual(self.left(), [(str(self.day(60)), D("10"))])
        m = StockMovement.objects.filter(shop_product_id=self.sp).first()
        self.assertEqual((m.movement_type, m.quantity_delta), ("expired", D("-5")))
        self.assertEqual(self.c.get(f"{API}/shop/products/expiry-alerts/").data["expired_count"], 0)
        bad = self.c.post(f"{API}/shop/products/{self.sp}/batches/{old['id']}/write-off/", {"quantity": "1"}, format="json")
        self.assertEqual(bad.status_code, 400)

    def test_close_batch_keeps_stock_and_date_for_stock_in_hand(self):
        self.buy(5, -1)
        b = self.batches()["batches"][0]
        r = self.c.post(f"{API}/shop/products/{self.sp}/batches/{b['id']}/close/", {}, format="json")
        self.assertEqual((D(r.data["product"]["stock_qty"]), r.data["batches"], r.data["undated_qty"]), (D("5"), [], "5.000"))
        self.assertIsNone(r.data["product"]["expiry_date"])
        add = self.c.post(f"{API}/shop/products/{self.sp}/batches/add/", {"expiry_date": str(self.day(40)), "quantity": "3",
                                                                           "batch_no": "SHELF"}, format="json")
        self.assertEqual(add.status_code, 200, add.data)
        self.assertEqual((add.data["undated_qty"], add.data["batches"][0]["batch_no"]), ("2.000", "SHELF"))
        too_many = self.c.post(f"{API}/shop/products/{self.sp}/batches/add/", {"expiry_date": str(self.day(40)), "quantity": "3"}, format="json")
        self.assertEqual(too_many.status_code, 400)
        edit = self.c.post(f"{API}/shop/products/{self.sp}/batches/{add.data['batches'][0]['id']}/edit/",
                           {"expiry_date": str(self.day(20))}, format="json")
        self.assertEqual(edit.data["product"]["expiry_date"], str(self.day(20)))

    def test_purchase_return_takes_that_purchase_batch(self):
        first = self.buy(5, 10)
        self.buy(5, 90)
        item = first["items"][0]["id"]
        r = self.c.post(f"{API}/shop/purchases/{first['id']}/return/", {"items": [{"purchase_item": item, "quantity": "5"}]},
                        format="json")
        self.assertIn(r.status_code, (200, 201), r.data)
        self.assertEqual(self.left(), [(str(self.day(90)), D("5"))])

    def test_stock_received_on_stock_screen_with_date_and_opening_stock(self):
        r = self.c.post(f"{API}/shop/products/{self.sp}/adjust-stock/", {"quantity_delta": "7", "movement_type": "purchase",
                                                                          "expiry_date": str(self.day(15)), "batch_no": "R7"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual((r.data["expiry_date"], r.data["expiry_qty"]), (str(self.day(15)), "7.000"))
        bad = self.c.post(f"{API}/shop/products/{self.sp}/adjust-stock/", {"quantity_delta": "-1", "movement_type": "adjustment",
                                                                            "expiry_date": str(self.day(15))}, format="json")
        self.assertEqual(bad.status_code, 400)
        new = self.c.post(f"{API}/shop/products/", {"master_product": make_master("Curd", barcode=None).id, "selling_price": "30",
                                                    "opening_stock": "4", "expiry_date": str(self.day(3))}, format="json")
        self.assertEqual(new.status_code, 201, new.data)
        self.assertEqual((new.data["expiry_date"], new.data["expiry_qty"]), (str(self.day(3)), "4.000"))

    def test_other_shop_cannot_touch_batches(self):
        self.buy(5, 10)
        b = self.batches()["batches"][0]
        other, shop_b = make_vendor("batch_other", "Other")
        o = client_for(other, shop_b)
        self.assertEqual(o.get(f"{API}/shop/products/{self.sp}/batches/").status_code, 404)
        self.assertEqual(o.post(f"{API}/shop/products/{self.sp}/batches/{b['id']}/write-off/", {}, format="json").status_code, 404)
        self.assertEqual(StockBatch.objects.get(pk=b["id"]).quantity_left, D("5"))

    def test_cashier_can_view_but_not_change_batches(self):
        self.buy(5, 10)
        b = self.batches()["batches"][0]
        cashier, _ = make_vendor("batch_cashier", role="cashier", shop=self.shop)
        cc = client_for(cashier, self.shop)
        self.assertEqual(cc.get(f"{API}/shop/products/{self.sp}/batches/").status_code, 200)
        self.assertEqual(cc.post(f"{API}/shop/products/{self.sp}/batches/{b['id']}/close/", {}, format="json").status_code, 403)

    def test_batches_never_exceed_stock(self):
        self.buy(5, 10)
        self.buy(5, 20)
        self.c.post(f"{API}/shop/products/{self.sp}/adjust-stock/", {"quantity_delta": "-8", "movement_type": "adjustment"}, format="json")
        total = sum(q for _, q in self.left())
        self.assertEqual(total, D("2"))
        self.assertEqual(self.left(), [(str(self.day(20)), D("2"))])
