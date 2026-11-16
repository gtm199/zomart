"""Consecutive GST document numbers per shop, per series, per financial year (1 April - 31 March).

Safe under concurrent requests: the shop row is locked first (select_for_update), then the sequence row, and
the (shop, series, fy_start_year) unique constraint stops a second sequence ever being created. Must run
inside the caller's transaction so a failed bill rolls its number back (no gaps from failed bills).
Format: <prefix><yy-yy>/<6 digits>, e.g. T26-27/000001 (13 characters; GST allows up to 16).
"""
from django.db import transaction

from apps.sales.models import InvoiceSequence
from apps.shops.models import Shop

PREFIX = {"tax_invoice": "T", "bill_of_supply": "B", "credit_note": "CN"}


def fy_start_year(day):
    return day.year if day.month >= 4 else day.year - 1


def fy_label(start_year):
    return f"{start_year % 100:02d}-{(start_year + 1) % 100:02d}"


def next_number(shop, series, day):
    """day: the local date of the document. Returns the new number string."""
    if series not in PREFIX:
        raise ValueError(f"Unknown series {series}")
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("next_number must run inside a transaction")
    Shop.objects.select_for_update().only("pk").get(pk=shop.pk)   # serialises all numbering for this shop
    fy = fy_start_year(day)
    seq, _ = InvoiceSequence.objects.select_for_update().get_or_create(shop_id=shop.pk, series=series, fy_start_year=fy)
    seq.last_number += 1
    seq.save(update_fields=["last_number"])
    return f"{PREFIX[series]}{fy_label(fy)}/{seq.last_number:06d}"
