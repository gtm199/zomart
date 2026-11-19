"""Online Orders > Deliveries: number of deliveries and delivery charges, kept separate from bills and reports."""
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone
from rest_framework.test import APITestCase

from apps.orders.models import Order, OrderEvent
from apps.sales.models import Sale

from .helpers import API, client_for, make_vendor
from . import test_orders as base   # module import: its test class is not run a second time

STATS = f"{API}/shop/orders/delivery-stats/"


class DeliveryStatsTests(APITestCase):
    """Setup from OrderFlowTests (without re-running its tests): delivery fee Rs 20, free above Rs 200,
    minimum order Rs 50, item Rs 30."""
    setUp = base.OrderFlowTests.setUp
    place = base.OrderFlowTests.place
    vendor = base.OrderFlowTests.vendor

    def deliver(self, qty="2", pay="cash"):
        oid = self.place(qty=qty).data["id"]
        self.vendor(oid, "accept")
        self.vendor(oid, "pack")
        self.vendor(oid, "ready")
        self.assertEqual(self.vendor(oid, "complete", payment_method=pay).data["status"], "completed")
        return oid

    def test_counts_deliveries_and_charges(self):
        self.v.post(f"{API}/shop/products/{self.sp}/adjust-stock/", {"quantity_delta": "20", "movement_type": "purchase"}, format="json")
        self.deliver("2")                            # Rs 20 fee
        self.deliver("2", pay="upi")                   # Rs 20 fee
        self.deliver("8")                              # free delivery (above Rs 200)
        pickup = self.place(fulfilment="pickup").data["id"]
        self.vendor(pickup, "accept"); self.vendor(pickup, "pack"); self.vendor(pickup, "ready")
        self.vendor(pickup, "complete", payment_method="cash")
        self.vendor(self.place().data["id"], "reject", reason="Closed")
        self.place()                                   # still waiting
        r = self.v.get(STATS)
        self.assertEqual(r.status_code, 200, r.data)
        d = r.data
        self.assertEqual((d["deliveries"], d["charges"], d["paid_deliveries"], d["free_deliveries"]), (3, "40.00", 2, 1))
        self.assertEqual((d["average_charge"], d["not_delivered"], d["in_progress_now"]), ("13.33", 1, 1))
        self.assertEqual(d["by_day"][0], {"date": str(timezone.localdate()), "deliveries": 3, "charges": "40.00"})
        self.assertEqual({p["method"]: p["charges"] for p in d["by_payment"]}, {"cash": "20.00", "upi": "20.00"})
        self.assertEqual(sum(x["deliveries"] for x in d["by_rider"]), 3)

    def test_charges_are_not_in_bills_or_reports(self):
        oid = self.deliver("2")
        sale = Sale.objects.get(pk=Order.objects.get(pk=oid).sale_id)
        self.assertEqual(sale.total, Decimal("60.00"))   # items only; the Rs 20 delivery charge is not billed
        today = str(timezone.localdate())
        pl = self.v.get(f"{API}/shop/reports/profit-loss/", {"from": today, "to": today})
        if pl.status_code == 200:
            self.assertNotIn("delivery", str(pl.data).lower())

    def test_counted_on_the_day_it_was_delivered(self):
        oid = self.deliver("2")
        yesterday = timezone.now() - timedelta(days=1)
        OrderEvent.objects.filter(order_id=oid, status="completed").update(created_at=yesterday)
        y = str(timezone.localdate(yesterday))
        self.assertEqual(self.v.get(STATS).data["deliveries"], 0)
        self.assertEqual(self.v.get(STATS, {"from": y, "to": y}).data["deliveries"], 1)

    def test_period_checks_and_shop_isolation(self):
        self.deliver("2")
        tomorrow = str(timezone.localdate() + timedelta(days=1))
        self.assertEqual(self.v.get(STATS, {"from": tomorrow, "to": tomorrow}).status_code, 400)
        self.assertEqual(self.v.get(STATS, {"from": "2020-01-01", "to": str(timezone.localdate())}).status_code, 400)
        self.assertEqual(self.v.get(STATS, {"from": "bad"}).status_code, 400)
        other, shop_b = make_vendor("stats_other", "Other Shop")
        self.assertEqual(client_for(other, shop_b).get(STATS).data["deliveries"], 0)
        cashier, _ = make_vendor("stats_cashier", role="cashier", shop=self.shop)   # cashiers handle online orders
        self.assertEqual(client_for(cashier, self.shop).get(STATS).status_code, 200)
        self.assertEqual(base.register_shopper(phone="9876500000").get(STATS).status_code, 401)   # not for customers
