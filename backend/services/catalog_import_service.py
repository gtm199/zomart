"""Catalogue import (CSV or XLSX), validation and export. Used by the admin screen and the command line."""
import csv
import io
from decimal import Decimal, InvalidOperation

from django.db import transaction

from apps.catalog.models import Brand, Category, MasterProduct, ProductBarcode, ProductChangeLog
from services import barcode_service, catalog_service
from services import cloudinary_image_service as cis

LARGE_FILE_ROWS = 500   # above this, images are not checked during the import (run "Sync images" afterwards)


class ExistingProductRow(ValueError):
    """The row's barcode is already in the catalogue. The row is still skipped (never merged), but its image can be
    attached to that existing product."""

    def __init__(self, message, product_id, image_id):
        super().__init__(message)
        self.product_id, self.image_id = product_id, image_id

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


def _barcode_owner(raw):
    """The ProductBarcode already holding this code, or None (an invalid code has no owner)."""
    if not raw:
        return None
    try:
        code = barcode_service.validate_barcode(raw)[0]
    except ValueError:
        return None
    return ProductBarcode.objects.filter(code=code).first()


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
    raw = cis.clean_barcode_text(row.get("barcode"))   # raises ValueError for spreadsheet damage (6.9E+11)
    image_ref = cis.parse_image_ref(row.get("image"))  # raises ValueError for another site / bad value
    if catalog_service.find_duplicates(name, brand.pk if brand else None, pack, unit).exists():
        message = "possible duplicate of an existing product (skipped, never merged)"
        owner = _barcode_owner(raw)
        if owner:   # the same product again (same barcode): the row is skipped, its image can still be attached
            raise ExistingProductRow(message, owner.product_id, image_ref or owner.code)
        raise ValueError(message)
    barcode = None
    if raw:
        code, symbology = barcode_service.validate_barcode(raw)  # raises ValueError
        owner = ProductBarcode.objects.filter(code=code).select_related("product").first()
        if code in seen_barcodes or owner:
            who = f" (already on product #{owner.product_id}: {owner.product})" if owner else " (twice in this file)"
            if owner:
                raise ExistingProductRow(f"barcode {code} conflict{who}", owner.product_id, image_ref or code)
            raise ValueError(f"barcode {code} conflict{who}")
        barcode = (code, symbology)
    seen_keys.add(key)
    if barcode:
        seen_barcodes.add(barcode[0])
    return {"name": name, "brand": brand_name, "category": (row.get("category") or "").strip(),
            "pack_size": pack, "unit": unit, "mrp": mrp, "tax_rate": tax,
            "description": (row.get("description") or "").strip(), "barcode": barcode,
            "loose": (row.get("loose") or "").strip().lower() in {"1", "yes", "true", "y"},
            # image: the "image" column if filled, otherwise the barcode is the Cloudinary public ID
            "image_id": image_ref or (barcode[0] if barcode else ""),
            "image_from": "image column" if image_ref else ("barcode" if barcode else ""),}


def validate_rows(rows, existing=None):
    """Returns (good_rows, error_messages). Nothing is saved.
    existing (optional list): filled with rows whose barcode is already in the catalogue, for their images."""
    good, errors, seen_barcodes, seen_keys = [], [], set(), set()
    for n, row in enumerate(rows, start=2):
        try:
            d = _validate(row, seen_barcodes, seen_keys)
            d["row"] = n
            good.append(d)
        except ExistingProductRow as exc:
            errors.append(f"row {n}: {exc}")
            if existing is not None:
                existing.append({"row": n, "product_id": exc.product_id, "image_id": exc.image_id})
        except ValueError as exc:
            errors.append(f"row {n}: {exc}")
    return good, errors


# ---------------- images (Cloudinary, by barcode) ----------------
def plan(rows, replace_images=False, known=None, check=True):
    """The preview: validates the rows and checks every image once.
    known: {public_id: status} from the preview, so the commit uses the same answers (equal totals) and is not slowed
    down by checking again. Large files (> LARGE_FILE_ROWS) are not checked here: run "Sync images" afterwards."""
    existing = []
    good, errors = validate_rows(rows, existing)
    for e in existing:
        p = MasterProduct.objects.filter(pk=e["product_id"]).only("image").first()
        e["has_image"] = bool(p and p.image)
        e["same_image"] = bool(p and p.image and p.image.name == e["image_id"])
        e["wanted"] = bool(e["image_id"]) and not e["same_image"] and (replace_images or not e["has_image"])
    ids = [d["image_id"] for d in good if d["image_id"]] + [e["image_id"] for e in existing if e["wanted"]]
    statuses = dict(known or {})
    todo = [i for i in dict.fromkeys(ids) if i not in statuses]
    large = len(rows) > LARGE_FILE_ROWS
    if todo and check and not large:
        statuses.update(cis.check_many(todo))
    for i in todo:
        statuses.setdefault(i, "not_checked")
    for d in good:
        d["image_status"] = statuses.get(d["image_id"], "") if d["image_id"] else "no_barcode"
    for e in existing:
        e["image_status"] = statuses.get(e["image_id"], "") if e["wanted"] else "kept"
    missing = ([d["image_id"] for d in good if d["image_status"] == cis.MISSING]
               + [e["image_id"] for e in existing if e["image_status"] == cis.MISSING])
    totals = {
        "products": len(good),
        "images_found": sum(1 for d in good if d["image_status"] == cis.FOUND),
        "images_missing": sum(1 for d in good if d["image_status"] == cis.MISSING),
        "images_unverified": sum(1 for d in good if d["image_status"] == cis.UNVERIFIED),
        "images_not_checked": sum(1 for d in good if d["image_status"] == "not_checked"),
        "no_barcode": sum(1 for d in good if d["image_status"] == "no_barcode"),
        "rows_with_errors": len(errors),
        "existing_images_to_attach": sum(1 for e in existing if e["image_status"] == cis.FOUND),
    }
    return {"good": good, "errors": errors, "existing": existing, "statuses": statuses, "totals": totals,
            "missing": missing, "large_file": large, "replace_images": replace_images}


def _log_image(product, user, old, new, how):
    ProductChangeLog.objects.create(product=product, changed_by=user if getattr(user, "pk", None) else None,
                                    field="image", old_value=old or "", new_value=f"{new} (attached by {how})")


@transaction.atomic
def commit_plan(p, activate=False, user=None):
    """Saves a plan: new products (with their image when it was found) and images for existing products.
    "missing" never blocks a product; "unverified" never changes an image. Running the same file again changes nothing."""
    created = commit_rows(p["good"], activate=activate, user=user)
    attached = 0
    for e in p["existing"]:
        if e["image_status"] != cis.FOUND:
            continue
        product = MasterProduct.objects.select_for_update().filter(pk=e["product_id"]).first()
        if product is None or product.image.name == e["image_id"]:
            continue                                   # already this image: nothing to do (idempotent)
        if product.image and not p["replace_images"]:
            continue
        old = product.image.name
        MasterProduct.objects.filter(pk=product.pk).update(image=e["image_id"])
        _log_image(product, user, old, e["image_id"], "catalogue import")
        attached += 1
    return {**p["totals"], "created": created, "existing_images_attached": attached}


@transaction.atomic
def commit_rows(good, activate=False, user=None):
    for d in good:
        brand = (Brand.objects.filter(name__iexact=d["brand"]).first() or Brand.objects.create(name=d["brand"])) if d["brand"] else None
        category = None
        if d["category"]:
            category = (Category.objects.filter(name__iexact=d["category"], parent=None).first()
                        or Category.objects.create(name=d["category"]))
        product = MasterProduct.objects.create(
            name=d["name"], brand=brand, category=category, pack_size=d["pack_size"], unit=d["unit"],
            mrp=d["mrp"], tax_rate=d["tax_rate"], description=d["description"], is_loose=d["loose"],
            status=MasterProduct.Status.ACTIVE if activate else MasterProduct.Status.DRAFT,
            created_by=user if getattr(user, "pk", None) else None)
        if d["barcode"]:
            ProductBarcode.objects.create(product=product, code=d["barcode"][0], symbology=d["barcode"][1], is_primary=True)
        if d.get("image_status") == cis.FOUND and d.get("image_id"):
            MasterProduct.objects.filter(pk=product.pk).update(image=d["image_id"])
            _log_image(product, user, "", d["image_id"], f"catalogue import, from the {d['image_from']}")
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