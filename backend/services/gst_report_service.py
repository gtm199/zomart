"""GST reports for a date range. Everything is summed in the database (no per-bill Python loops), so a 12-month
range stays light on the server and the phone only receives small summary tables.

Figures come only from what was saved on each bill and credit note at the time (snapshots), never from today's
product rates. Invoices and credit notes are shown separately and then netted, the way a CA usually wants them.
These are aids for filing, not a filed return.
"""
from datetime import date
from decimal import Decimal

from django.db.models import Count, DecimalField, ExpressionWrapper, F, Q, Sum
from django.db.models.functions import TruncDay, TruncMonth
from django.utils import timezone

from apps.purchases.models import Purchase, PurchaseItem
from apps.sales.models import CreditNote, CreditNoteItem, Sale, SaleItem
from services.accounting_service import add_months
from services.exceptions import BusinessRuleError

ZERO = Decimal("0.00")
GST_REPORT_MAX_MONTHS = 12
LIST_LIMIT = 500   # B2B invoices / credit notes listed per report; totals always cover the whole range
DISCLAIMER = ("These reports are an aid for filing, not a filed return. They are made from the rates and details "
              "entered in the app. Check them with your CA before filing.")
GST_DOCS = (Sale.DocumentType.TAX_INVOICE, Sale.DocumentType.BILL_OF_SUPPLY)


def has_gst_history(shop):
    return shop.gst_enabled or Sale.objects.filter(shop=shop, document_type__in=GST_DOCS).exists()


def parse_gst_range(shop, params):
    """from <= to, to not in the future, at most 12 months (a full financial year fits)."""
    if not has_gst_history(shop):
        raise BusinessRuleError("GST reports are for shops with GST billing switched on.", "gst_not_enabled", 403)
    today = timezone.localdate()
    try:
        start = date.fromisoformat(params["from"]) if params.get("from") else today.replace(day=1)
        end = date.fromisoformat(params["to"]) if params.get("to") else today
    except ValueError:
        raise BusinessRuleError("Use YYYY-MM-DD for from and to.", "invalid_date")
    if start > end:
        raise BusinessRuleError("The From date must be on or before the To date.", "invalid_range")
    if end > today:
        raise BusinessRuleError("The To date cannot be in the future.", "future_date")
    if end > add_months(start, GST_REPORT_MAX_MONTHS):
        raise BusinessRuleError(f"GST reports cover at most {GST_REPORT_MAX_MONTHS} months (one financial year).",
                                "range_too_long")
    return start, end


def _s(v):
    """Money as a 2-decimal string, whatever scale the database returns for a SUM."""
    return str(Decimal(v if v is not None else 0).quantize(Decimal("0.01")))


def gst_report(shop, start, end, period=None):
    period = period or ("day" if (end - start).days <= 62 else "month")
    trunc = TruncDay if period == "day" else TruncMonth
    docs = Sale.objects.filter(shop=shop, document_type__in=GST_DOCS, created_at__date__range=(start, end))
    notes = CreditNote.objects.filter(shop=shop, created_at__date__range=(start, end))

    inv_tot = docs.aggregate(count=Count("id"), taxable=Sum("taxable_total"), cgst=Sum("cgst_total"),
                             sgst=Sum("sgst_total"), igst=Sum("igst_total"), round_off=Sum("round_off"),
                             total=Sum("total"))
    cn_tot = notes.aggregate(count=Count("id"), taxable=Sum("taxable_total"), cgst=Sum("cgst_total"),
                             sgst=Sum("sgst_total"), igst=Sum("igst_total"), total=Sum("total"))

    def money_block(d, with_round_off=False):
        out = {k: _s(d.get(k)) for k in ("taxable", "cgst", "sgst", "igst", "total")}
        out["tax"] = _s(sum((d.get(k) or ZERO) for k in ("cgst", "sgst", "igst")))
        if with_round_off:
            out["round_off"] = _s(d.get("round_off"))
        out["count"] = d.get("count") or 0
        return out

    invoices = money_block(inv_tot, with_round_off=True)
    credit = money_block(cn_tot)
    net = {k: _s(Decimal(invoices[k]) - Decimal(credit[k])) for k in ("taxable", "cgst", "sgst", "igst", "tax", "total")}

    by_period = []
    for row in (docs.annotate(p=trunc("created_at")).values("p")
                .annotate(count=Count("id"), tax_invoices=Count("id", filter=Q(document_type=Sale.DocumentType.TAX_INVOICE)),
                          bills_of_supply=Count("id", filter=Q(document_type=Sale.DocumentType.BILL_OF_SUPPLY)),
                          taxable=Sum("taxable_total"), cgst=Sum("cgst_total"), sgst=Sum("sgst_total"),
                          igst=Sum("igst_total"), total=Sum("total"))
                .order_by("p")):
        p = timezone.localtime(row["p"]) if timezone.is_aware(row["p"]) else row["p"]
        by_period.append({"period": p.strftime("%Y-%m-%d" if period == "day" else "%Y-%m"),
                          "count": row["count"], "tax_invoices": row["tax_invoices"],
                          "bills_of_supply": row["bills_of_supply"],
                          **{k: _s(row[k]) for k in ("taxable", "cgst", "sgst", "igst", "total")}})

    items = SaleItem.objects.filter(sale__in=docs)
    by_rate = [{"rate": _s(r["tax_rate"]), "taxable": _s(r["taxable"]), "cgst": _s(r["cgst"]), "sgst": _s(r["sgst"]),
                "igst": _s(r["igst"]), "tax": _s((r["cgst"] or 0) + (r["sgst"] or 0) + (r["igst"] or 0)),
                "value": _s(r["value"])}
               for r in (items.values("tax_rate").annotate(taxable=Sum("taxable_value"), cgst=Sum("cgst"),
                                                           sgst=Sum("sgst"), igst=Sum("igst"), value=Sum("line_total"))
                         .order_by("tax_rate"))]
    by_hsn = [{"hsn": r["hsn_code"] or "-", "rate": _s(r["tax_rate"]), "unit": r["unit"] or "pc",
               "quantity": format(r["qty"].normalize(), "f") if r["qty"] is not None else "0",
               "taxable": _s(r["taxable"]), "cgst": _s(r["cgst"]), "sgst": _s(r["sgst"]), "igst": _s(r["igst"]),
               "value": _s(r["value"])}
              for r in (items.values("hsn_code", "tax_rate", "unit")
                        .annotate(qty=Sum("quantity"), taxable=Sum("taxable_value"), cgst=Sum("cgst"),
                                  sgst=Sum("sgst"), igst=Sum("igst"), value=Sum("line_total"))
                        .order_by("hsn_code", "tax_rate"))]
    cn_by_rate = [{"rate": _s(r["gst_rate"]), "taxable": _s(r["taxable"]), "cgst": _s(r["cgst"]),
                   "sgst": _s(r["sgst"]), "igst": _s(r["igst"]), "value": _s(r["value"])}
                  for r in (CreditNoteItem.objects.filter(credit_note__in=notes).values("gst_rate")
                            .annotate(taxable=Sum("taxable_value"), cgst=Sum("cgst"), sgst=Sum("sgst"),
                                      igst=Sum("igst"), value=Sum("line_total")).order_by("gst_rate"))]

    b2b_qs = docs.exclude(customer_gstin="").order_by("created_at", "id")
    b2b = [{"invoice": s.invoice_number, "date": timezone.localtime(s.created_at).date().isoformat(),
            "customer_gstin": s.customer_gstin, "customer_name": s.customer_gst_name, "taxable": _s(s.taxable_total),
            "cgst": _s(s.cgst_total), "sgst": _s(s.sgst_total), "igst": _s(s.igst_total), "total": _s(s.total)}
           for s in b2b_qs[:LIST_LIMIT]]
    note_rows = [{"number": n.number, "date": timezone.localtime(n.created_at).date().isoformat(),
                  "against": n.original_invoice_number, "taxable": _s(n.taxable_total), "cgst": _s(n.cgst_total),
                  "sgst": _s(n.sgst_total), "igst": _s(n.igst_total), "total": _s(n.total)}
                 for n in notes.order_by("created_at", "id")[:LIST_LIMIT]]
    first_last = docs.order_by("created_at", "id").values_list("invoice_number", flat=True)
    purchases = purchases_summary(shop, start, end)

    return {
        "shop": {"name": shop.name, "legal_name": shop.gst_legal_name or shop.name, "gstin": shop.gstin,
                 "scheme": shop.gst_scheme, "state_code": shop.gst_state_code},
        "from": str(start), "to": str(end), "period": period,
        "generated_at": timezone.localtime().isoformat(timespec="minutes"),
        "invoices": invoices, "credit_notes": credit, "net": net,
        "by_period": by_period, "by_rate": by_rate, "by_hsn": by_hsn, "credit_notes_by_rate": cn_by_rate,
        "b2b_invoices": b2b, "b2b_count": b2b_qs.count(),
        "credit_note_list": note_rows,
        "list_limit": LIST_LIMIT,
        "first_invoice": first_last.first(), "last_invoice": first_last.last(),
        "plain_bills_in_range": Sale.objects.filter(shop=shop, document_type=Sale.DocumentType.BILL,
                                                    created_at__date__range=(start, end)).count(),
        "items_missing": docs.filter(items__isnull=True).count(),
        "purchases": purchases,
        "delivery_fee_note": "GST on online-order delivery fees is not included (not charged in this version).",
        "disclaimer": DISCLAIMER,
    }


_DEC = DecimalField(max_digits=24, decimal_places=8)


def purchases_summary(shop, start, end):
    """Input tax as recorded from supplier bills (purchase date in range), net of goods returned to suppliers.
    Recorded figures only: whether input tax can be claimed is a question for the CA (no ITC logic here)."""
    purchases = Purchase.objects.filter(shop=shop, purchase_date__range=(start, end))
    items = PurchaseItem.objects.filter(purchase__in=purchases, quantity__gt=0)
    kept = F("quantity") - F("returned_qty")
    net_gst = ExpressionWrapper(F("gst_amount") * kept / F("quantity"), output_field=_DEC)
    net_value = ExpressionWrapper(F("line_total") * kept / F("quantity"), output_field=_DEC)
    tot = items.aggregate(value=Sum(net_value), gst=Sum(net_gst))
    by_rate = [{"rate": _s(r["gst_rate"]) if r["gst_rate"] is not None else "not given",
                "value": _s(r["value"]), "gst": _s(r["gst"])}
               for r in items.values("gst_rate").annotate(value=Sum(net_value), gst=Sum(net_gst)).order_by("gst_rate")]
    by_supplier = [{"supplier": r["sname"], "supplier_gstin": r["sgstin"] or "-", "bills": r["bills"],
                    "value": _s(r["value"]), "gst": _s(r["gst"])}
                   for r in (items.values(sname=F("purchase__supplier__name"), sgstin=F("purchase__supplier_gstin"))
                             .annotate(bills=Count("purchase", distinct=True), value=Sum(net_value), gst=Sum(net_gst))
                             .order_by("sname", "sgstin"))]
    return {
        "count": purchases.count(),
        "with_supplier_gstin": purchases.exclude(supplier_gstin="").count(),
        "value": _s(tot["value"]), "gst": _s(tot["gst"]),
        "by_rate": by_rate, "by_supplier": by_supplier,
        "note": ("Input tax as entered from supplier bills, after goods returned to suppliers. Whether it can be "
                 "claimed is for your CA to decide; the app does no input-tax-credit filing."),
    }
