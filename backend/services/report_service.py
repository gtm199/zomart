from collections import defaultdict
from decimal import Decimal

from django.db.models import Count, Sum

from apps.sales.models import Payment, Sale
from services.money import money


def daily_summary(shop, day):
    sales = Sale.objects.filter(shop=shop, created_at__date=day).prefetch_related("items")
    totals = sales.aggregate(
        count=Count("id"), total=Sum("total"), tax=Sum("tax_total"),
        discount=Sum("discount_total"), credit=Sum("amount_due"),
    )
    by_method = defaultdict(lambda: Decimal("0"))
    receipts = Decimal("0")
    for row in Payment.objects.filter(shop=shop, created_at__date=day).values("kind", "method").annotate(a=Sum("amount")):
        by_method[row["method"]] += row["a"]
        if row["kind"] == Payment.Kind.CUSTOMER_RECEIPT:
            receipts += row["a"]
    profit = Decimal("0")
    for sale in sales:
        for item in sale.items.all():
            net_qty = item.quantity - item.returned_qty
            if item.quantity:
                net_revenue = (item.line_total - item.tax_amount) * net_qty / item.quantity
                profit += net_revenue - net_qty * item.purchase_cost
    z = Decimal("0")
    return {
        "date": str(day),
        "bills": totals["count"] or 0,
        "sales_total": totals["total"] or z,
        "tax_included": totals["tax"] or z,
        "discounts": totals["discount"] or z,
        "credit_given": totals["credit"] or z,
        "customer_receipts": receipts,
        "net_collected_by_method": {k: money(v) for k, v in by_method.items()},
        "gross_profit_estimate": money(profit),
        "note": "Profit is an estimate (selling price ex-tax minus purchase cost at time of sale). Expenses are not included.",
    }
