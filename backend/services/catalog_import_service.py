"""Catalogue import (CSV or XLSX), validation and export. Used by the admin screen and the command line."""
import csv
import io
from decimal import Decimal, InvalidOperation

from django.db import transaction

from apps.catalog.models import Brand, Category, MasterProduct, ProductBarcode
from services import barcode_service, catalog_service

UNITS = {u.value for u in MasterProduct.Unit}


def read_csv(text):
    return list(csv.DictReader(io.StringIO(text)))


def read_xlsx(fileobj):
    from openpyxl import load_workbook

    ws = load_workbook(fileobj, read_only=True, data_only=True).active
    rows = ws.iter_rows(values_only=True)
    header = [str(h).strip().lower() if h is not None else "" for h in next(rows, [])]
    out = []
    for r in rows:
        if all(c is None for c in r):
            continue
        item = {}
        for key, cell in zip(header, r):
            if isinstance(cell, float) and cell.is_integer():
                cell = int(cell)  # Excel turned a barcode into a number
            item[key] = "" if cell is None else str(cell)
        out.append(item)
    return out


def _validate(row, seen_barcodes, seen_keys):
    name = (row.get("name") or "").strip()
    if not name:
        raise ValueError("name is required")
    unit = (row.get("unit") or "pc").strip().lower()
    if unit not in UNITS:
        raise ValueError(f"unit must be one of {sorted(UNITS)}")
    try:
        pack = Decimal((row.get("pack_size") or "1").strip())
        mrp = Decimal(row["mrp"].strip()) if (row.get("mrp") or "").strip() else None
        tax = Decimal(row["tax_rate"].strip()) if (row.get("tax_rate") or "").strip() else None
    except InvalidOperation:
        raise ValueError("pack_size, mrp and tax_rate must be numbers")
    if pack <= 0 or (mrp is not None and mrp < 0) or (tax is not None and not 0 <= tax <= 100):
        raise ValueError("pack_size, mrp or tax_rate is out of range")
    brand_name = (row.get("brand") or "").strip()
    brand = Brand.objects.filter(name__iexact=brand_name).first() if brand_name else None
    key = (name.lower(), brand_name.lower(), pack, unit)
    if key in seen_keys:
        raise ValueError("same product appears twice in this file")
    if catalog_service.find_duplicates(name, brand.pk if brand else None, pack, unit).exists():
        raise ValueError("possible duplicate of an existing product (skipped, never merged)")
    barcode = None
    raw = (row.get("barcode") or "").strip()
    if raw:
        code, symbology = barcode_service.validate_barcode(raw)  # raises ValueError
        owner = ProductBarcode.objects.filter(code=code).select_related("product").first()
        if code in seen_barcodes or owner:
            who = f" (already on product #{owner.product_id}: {owner.product})" if owner else " (twice in this file)"
            raise ValueError(f"barcode {code} conflict{who}")
        barcode = (code, symbology)
    seen_keys.add(key)
    if barcode:
        seen_barcodes.add(barcode[0])
    return {"name": name, "brand": brand_name, "category": (row.get("category") or "").strip(),
            "pack_size": pack, "unit": unit, "mrp": mrp, "tax_rate": tax,
            "description": (row.get("description") or "").strip(), "barcode": barcode,
            "loose": (row.get("loose") or "").strip().lower() in {"1", "yes", "true", "y"},}


def validate_rows(rows):
    """Returns (good_rows, error_messages). Nothing is saved."""
    good, errors, seen_barcodes, seen_keys = [], [], set(), set()
    for n, row in enumerate(rows, start=2):
        try:
            good.append(_validate(row, seen_barcodes, seen_keys))
        except ValueError as exc:
            errors.append(f"row {n}: {exc}")
    return good, errors


@transaction.atomic
def commit_rows(good, activate=False):
    for d in good:
        brand = (Brand.objects.filter(name__iexact=d["brand"]).first() or Brand.objects.create(name=d["brand"])) if d["brand"] else None
        category = None
        if d["category"]:
            category = (Category.objects.filter(name__iexact=d["category"], parent=None).first()
                        or Category.objects.create(name=d["category"]))
        product = MasterProduct.objects.create(
            name=d["name"], brand=brand, category=category, pack_size=d["pack_size"], unit=d["unit"],
            mrp=d["mrp"], tax_rate=d["tax_rate"], description=d["description"], is_loose=d["loose"],
            status=MasterProduct.Status.ACTIVE if activate else MasterProduct.Status.DRAFT)
        if d["barcode"]:
            ProductBarcode.objects.create(product=product, code=d["barcode"][0], symbology=d["barcode"][1], is_primary=True)
    return len(good)


EXPORT_HEADER = ["name", "brand", "category", "pack_size", "unit", "barcode", "mrp", "tax_rate", "description",
                 "status", "mrp_verified", "other_barcodes"]


def export_rows(queryset):
    """Same columns as the import file (plus a few extra), so an export can be edited and imported again."""
    rows = []
    for p in queryset.select_related("brand", "category").prefetch_related("barcodes"):
        codes = [b.code for b in sorted(p.barcodes.all(), key=lambda b: (not b.is_primary, b.id))]
        rows.append([p.name, p.brand.name if p.brand_id else "", p.category.name if p.category_id else "",
                     format(p.pack_size.normalize(), "f"), p.unit, codes[0] if codes else "",
                     "" if p.mrp is None else p.mrp, "" if p.tax_rate is None else p.tax_rate, p.description,
                     p.status, "yes" if p.mrp_verified_at else "no", "|".join(codes[1:])])
    return EXPORT_HEADER, rows