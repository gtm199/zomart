"""Online-order deliveries: how many were delivered and the delivery charges, for the Online Orders screen only.

Kept separate on purpose: delivery charges are not part of any bill (order_service.complete), so they are not in sales,
profit & loss, the GST report or any other report, and nothing here changes them. Read-only.
A delivery counts on the day it was completed (handed over), not the day it was ordered.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Count, DateTimeField, OuterRef, Q, Subquery, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from apps.orders.models import Order, OrderEvent
from services import order_service
from services.exceptions import BusinessRuleError

MAX_DAYS = 366
ZERO = Decimal("0.00")
NOTE = "Delivery charges are kept separate: they are not part of bills, sales or reports."


def _money(v):
    return str((v or ZERO).quantize(Decimal("0.01")))


def parse_period(params):
    """from/to as YYYY-MM-DD (default: today). Not in the future, at most 366 days."""
    today = timezone.localdate()
    try:
        d_from = date.fromisoformat(params.get("from") or str(today))
        d_to = date.fromisoformat(params.get("to") or str(d_from if params.get("from") else today))
    except ValueError:
        raise BusinessRuleError("Dates must be YYYY-MM-DD.", "invalid_date")
    if d_from > d_to:
        raise BusinessRuleError("The start date is after the end date.", "invalid_range")
    if d_to > today:
        raise BusinessRuleError("The end date cannot be in the future.", "future_date")
    if (d_to - d_from).days + 1 > MAX_DAYS:
        raise BusinessRuleError(f"Choose at most {MAX_DAYS} days.", "range_too_long")
    return d_from, d_to


def delivery_stats(shop, d_from, d_to):
    done_at = (OrderEvent.objects.filter(order=OuterRef("pk"), status=Order.Status.COMPLETED)
               .order_by("id").values("created_at")[:1])
    delivered = (Order.objects.filter(shop=shop, fulfilment=Order.Fulfilment.DELIVERY, status=Order.Status.COMPLETED)
                 .annotate(done_day=TruncDate(Subquery(done_at, output_field=DateTimeField())))
                 .filter(done_day__gte=d_from, done_day__lte=d_to))
    totals = delivered.aggregate(n=Count("id"), fees=Sum("delivery_fee"), free=Count("id", filter=Q(delivery_fee=0)))

    by_day = {r["done_day"]: r for r in delivered.values("done_day").annotate(n=Count("id"), fees=Sum("delivery_fee"))}
    days = []
    if (d_to - d_from).days < 62:   # a day-by-day list for short periods
        day = d_to
        while day >= d_from:
            r = by_day.get(day)
            days.append({"date": str(day), "deliveries": r["n"] if r else 0, "charges": _money(r["fees"] if r else None)})
            day -= timedelta(days=1)

    by_rider = [{"rider": (r["rider__first_name"] or r["rider__username"] or "No rider recorded"),
                 "deliveries": r["n"], "charges": _money(r["fees"])}
                for r in delivered.values("rider_id", "rider__first_name", "rider__username")
                .annotate(n=Count("id"), fees=Sum("delivery_fee")).order_by("-n")]
    by_payment = [{"method": r["payment_method"], "deliveries": r["n"], "charges": _money(r["fees"])}
                  for r in delivered.values("payment_method").annotate(n=Count("id"), fees=Sum("delivery_fee")).order_by("-n")]

    ordered = Order.objects.filter(shop=shop, fulfilment=Order.Fulfilment.DELIVERY,
                                   created_at__date__gte=d_from, created_at__date__lte=d_to)
    now = Order.objects.filter(shop=shop, fulfilment=Order.Fulfilment.DELIVERY, status__in=order_service.ACTIVE)
    n = totals["n"] or 0
    return {
        "from": str(d_from), "to": str(d_to),
        "deliveries": n,
        "charges": _money(totals["fees"]),
        "paid_deliveries": n - (totals["free"] or 0),
        "free_deliveries": totals["free"] or 0,
        "average_charge": _money((totals["fees"] or ZERO) / n if n else None),
        "not_delivered": ordered.filter(status__in=[Order.Status.CANCELLED, Order.Status.REJECTED]).count(),
        "in_progress_now": now.count(),
        "out_for_delivery_now": now.filter(status=Order.Status.OUT_FOR_DELIVERY).count(),
        "by_day": days,
        "by_rider": by_rider,
        "by_payment": by_payment,
        "note": NOTE,
    }
