"""Date-range reports, ageing and cash close. Everything is filtered by shop."""
from collections import defaultdict
from datetime import date
from decimal import Decimal

from django.db.models import DecimalField, ExpressionWrapper, F, Min, Sum
from django.utils import timezone

from apps.customers.models import Customer, CustomerLedger
from apps.expenses.models import CashClose, Expense
from apps.inventory.models import ShopProduct
from apps.sales.models import Payment, SaleItem
from apps.suppliers.models import Supplier, SupplierLedger, SupplierPayment
from services.exceptions import BusinessRuleError
from services.money import money

ZERO = Decimal("0")
_DEC = DecimalField(max_digits=24, decimal_places=8)


def _plain(d):
    """2.000 -> "2" and 100.000 -> "100" (never scientific notation)."""
    return format(d.normalize(), "f")


import calendar
PDF_EXPORT_MAX_MONTHS = 3        # every shop
GST_PDF_EXPORT_MAX_MONTHS = 12   # shops with GST billing on (a full financial year fits)

def add_months(d, n):
    """Same day n months later, clamped to month end (30 Nov + 3 -> 28/29 Feb)."""
    m = d.month - 1 + n
    y, m = d.year + m // 12, m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def report_limits(shop):
    """What the app may offer. The server enforces the same numbers in parse_range()."""
    gst = bool(shop is not None and shop.gst_enabled)
    return {"gst_enabled": gst, "max_export_months": GST_PDF_EXPORT_MAX_MONTHS if gst else PDF_EXPORT_MAX_MONTHS,
            "max_range_days": 366, "gst_report_max_months": GST_PDF_EXPORT_MAX_MONTHS if gst else 0,
            # the "amounts with / without GST" switch is offered only where GST is actually collected
            "gst_amount_switch": gst and shop.gst_scheme != "composition"}


def parse_range(params, shop=None):
    today = timezone.localdate()
    try:
        start = date.fromisoformat(params["from"]) if params.get("from") else today.replace(day=1)
        end = date.fromisoformat(params["to"]) if params.get("to") else today
    except ValueError:
        raise BusinessRuleError("Use YYYY-MM-DD for from and to.", "invalid_date")
    if start > end or (end - start).days > 366:
        raise BusinessRuleError("Choose a range of at most one year, with from before to.", "invalid_range")
    if params.get("export") == "pdf":
        months = report_limits(shop)["max_export_months"]
        if end > today:
            raise BusinessRuleError("The To date cannot be in the future.", "future_date")
        if end > add_months(start, months):
            raise BusinessRuleError(f"PDF export covers at most {months} months.", "range_too_long")
    return start, end


def sales_breakdown(shop, start, end):
    """Net of returns. Sales are counted on the day they were billed (credit sales included).
    Summed per product in the database (one row per product, not per bill line), so long ranges - up to
    12 months for GST shops - stay light on the server."""
    net_qty = F("quantity") - F("returned_qty")
    rows = (SaleItem.objects.filter(sale__shop=shop, sale__created_at__date__range=(start, end), quantity__gt=0)
            .values("shop_product_id", "shop_product__master_product__category__name")
            .annotate(name=Min("product_name"), qty=Sum(net_qty),
                      revenue=Sum(ExpressionWrapper(F("line_total") * net_qty / F("quantity"), output_field=_DEC)),
                      tax=Sum(ExpressionWrapper(F("tax_amount") * net_qty / F("quantity"), output_field=_DEC)),
                      cost=Sum(ExpressionWrapper(net_qty * F("purchase_cost"), output_field=_DEC))))
    totals = {"net_sales": ZERO, "tax": ZERO, "revenue_ex_tax": ZERO, "cost_of_goods": ZERO}
    products = {}
    for r in rows:
        revenue, tax, cost = r["revenue"] or ZERO, r["tax"] or ZERO, r["cost"] or ZERO
        totals["net_sales"] += revenue
        totals["tax"] += tax
        totals["revenue_ex_tax"] += revenue - tax
        totals["cost_of_goods"] += cost
        products[r["shop_product_id"]] = {
            "product": r["name"], "category": r["shop_product__master_product__category__name"] or "Uncategorised",
            "quantity": r["qty"] or ZERO, "sales": revenue, "sales_ex_tax": revenue - tax, "profit": revenue - tax - cost}
    totals["gross_profit"] = totals["revenue_ex_tax"] - totals["cost_of_goods"]
    return totals, products


def profit_and_loss(shop, start, end):
    totals, _ = sales_breakdown(shop, start, end)
    exp = (Expense.objects.filter(shop=shop, is_voided=False, expense_date__range=(start, end))
           .values("category__name").annotate(total=Sum("amount")).order_by("-total"))
    expenses_total = sum((e["total"] for e in exp), ZERO)
    collected = defaultdict(lambda: ZERO)
    for row in (Payment.objects.filter(shop=shop, created_at__date__range=(start, end))
                .values("method").annotate(total=Sum("amount"))):
        collected[row["method"]] += row["total"]
    return {
        "from": str(start), "to": str(end),
        "net_sales": money(totals["net_sales"]),
        "tax_included_in_sales": money(totals["tax"]),
        "sales_excluding_tax": money(totals["revenue_ex_tax"]),
        "cost_of_goods_sold": money(totals["cost_of_goods"]),
        "gross_profit": money(totals["gross_profit"]),
        "expenses_total": money(expenses_total),
        "expenses_by_category": [{"category": e["category__name"], "amount": money(e["total"])} for e in exp],
        "net_profit": money(totals["gross_profit"] - expenses_total),
        "money_collected_by_method": {k: money(v) for k, v in collected.items()},
        "note": ("Net profit = gross profit - expenses. Cost of goods uses the purchase cost saved at the time of sale. "
                 "Not included: tax payable, depreciation, owner's drawings. Money collected includes customer "
                 "payments for earlier credit sales and is net of refunds."),
    }


def sales_analysis(shop, start, end, limit=10):
    _, products = sales_breakdown(shop, start, end)
    rows = sorted(products.values(), key=lambda r: r["sales"], reverse=True)
    categories = defaultdict(lambda: {"sales": ZERO, "sales_ex_tax": ZERO, "profit": ZERO})
    for r in rows:
        categories[r["category"]]["sales"] += r["sales"]
        categories[r["category"]]["sales_ex_tax"] += r["sales_ex_tax"]
        categories[r["category"]]["profit"] += r["profit"]
    # "sales" includes GST (what customers paid); "sales_ex_tax" leaves it out. The app's report switch picks one.
    fmt = lambda r: {**r, "quantity": _plain(r["quantity"]), "sales": money(r["sales"]),
                     "sales_ex_tax": money(r["sales_ex_tax"]), "profit": money(r["profit"])}
    slow = (ShopProduct.objects.filter(shop=shop, is_enabled=True, stock_qty__gt=0)
            .exclude(pk__in=products.keys()).select_related("master_product__brand").order_by("-stock_qty")[:30])
    return {
        "from": str(start), "to": str(end),
        "top_sellers": [fmt(r) for r in rows[:limit]],
        "all_products": [fmt(r) for r in rows],
        "by_category": sorted(
            [{"category": k, "sales": money(v["sales"]), "sales_ex_tax": money(v["sales_ex_tax"]),
              "profit": money(v["profit"])} for k, v in categories.items()],
            key=lambda r: r["sales"], reverse=True),
        "slow_movers": [{"product": s.master_product.display_name, "stock": _plain(s.stock_qty),
                         "stock_value_at_cost": money(s.stock_qty * s.purchase_cost)} for s in slow],
    }


BUCKETS = [("0-30 days", 0, 30), ("31-60 days", 31, 60), ("61-90 days", 61, 90), ("over 90 days", 91, 10**6)]


def _age_split(balance, entries, today):
    """Assume payments clear the oldest bills first, so what is still owed sits on the newest bills."""
    out = {name: ZERO for name, _, _ in BUCKETS}
    out["unallocated"] = ZERO
    remaining = balance
    for created_at, amount in entries:  # newest first
        if remaining <= 0:
            break
        part = min(amount, remaining)
        days = (today - timezone.localtime(created_at).date()).days
        name = next(n for n, lo, hi in BUCKETS if lo <= days <= hi)
        out[name] += part
        remaining -= part
    out["unallocated"] = remaining if remaining > 0 else ZERO
    return out


def _ageing_block(people, ledger_model, fk_name, credit_type, today):
    totals = defaultdict(lambda: ZERO)
    rows = []
    for person in people:
        entries = list(ledger_model.objects.filter(**{fk_name: person}, entry_type=credit_type)
                       .order_by("-created_at").values_list("created_at", "amount"))
        split = _age_split(person.balance, entries, today)
        for k, v in split.items():
            totals[k] += v
        rows.append({"name": person.name, "phone": person.phone, "balance": money(person.balance),
                     **{k: money(v) for k, v in split.items()}})
    rows.sort(key=lambda r: r["balance"], reverse=True)
    return {"total": money(sum((p.balance for p in people), ZERO)),
            "buckets": {k: money(v) for k, v in totals.items()}, "rows": rows}


def ageing(shop):
    today = timezone.localdate()
    return {
        "as_of": str(today),
        "receivables": _ageing_block(list(Customer.objects.filter(shop=shop, balance__gt=0)),
                                     CustomerLedger, "customer", CustomerLedger.EntryType.CREDIT_SALE, today),
        "payables": _ageing_block(list(Supplier.objects.filter(shop=shop, balance__gt=0)),
                                  SupplierLedger, "supplier", SupplierLedger.EntryType.PURCHASE, today),
        "note": "Ageing assumes payments clear the oldest bills first. 'unallocated' is balance not traced to a bill.",
    }


def cash_position(shop, day, opening=None):
    def total(qs):
        return qs.aggregate(t=Sum("amount"))["t"] or ZERO
    cash_in = total(Payment.objects.filter(shop=shop, method="cash", created_at__date=day))  # sales + receipts - refunds
    cash_expenses = total(Expense.objects.filter(shop=shop, method="cash", expense_date=day, is_voided=False))
    supplier_cash = total(SupplierPayment.objects.filter(shop=shop, method="cash", created_at__date=day))  # paid - refunds
    if opening is None:
        last = CashClose.objects.filter(shop=shop, close_date__lt=day).order_by("-close_date").first()
        opening = last.counted_cash if last else ZERO
    expected = opening + cash_in - cash_expenses - supplier_cash
    return {"date": str(day), "opening_cash": money(opening), "cash_received_net": money(cash_in),
            "cash_expenses": money(cash_expenses), "cash_paid_to_suppliers_net": money(supplier_cash),
            "expected_cash": money(expected)}


def close_day(shop, user, day, counted, opening=None, note=""):
    if CashClose.objects.filter(shop=shop, close_date=day).exists():
        raise BusinessRuleError("This day is already closed.", "already_closed")
    pos = cash_position(shop, day, opening)
    counted = money(counted)
    return CashClose.objects.create(
        shop=shop, close_date=day, opening_cash=pos["opening_cash"], expected_cash=pos["expected_cash"],
        counted_cash=counted, difference=counted - pos["expected_cash"], note=note, closed_by=user)