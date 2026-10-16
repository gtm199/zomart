from decimal import Decimal

from django.db.models import Count, DecimalField, ExpressionWrapper, F, Sum

from apps.inventory.models import ShopProduct
from apps.suppliers.models import Supplier
from services.money import money

VALUE = ExpressionWrapper(F("stock_qty") * F("purchase_cost"), output_field=DecimalField(max_digits=20, decimal_places=3))


def stock_valuation(shop):
    """Stock value at latest purchase cost (not FIFO/average) plus what the shop owes suppliers."""
    rows = ShopProduct.objects.filter(shop=shop, stock_qty__gt=0)
    totals = rows.aggregate(value=Sum(VALUE), items=Count("id"))
    by_category = (rows.values(category=F("master_product__category__name"))
                   .annotate(value=Sum(VALUE), items=Count("id")).order_by("-value"))
    payables = Supplier.objects.filter(shop=shop).aggregate(t=Sum("balance"))["t"] or Decimal("0")
    return {
        "stock_value": money(totals["value"] or 0),
        "products_in_stock": totals["items"],
        "products_without_cost": rows.filter(purchase_cost=0).count(),
        "by_category": [{"category": r["category"] or "Uncategorised", "value": money(r["value"] or 0),
                         "items": r["items"]} for r in by_category],
        "payables_to_suppliers": money(payables),
        "note": "Valued at the latest purchase cost. Products with cost 0 add nothing to the value.",
    }