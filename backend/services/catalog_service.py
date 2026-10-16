from django.db import transaction

from apps.catalog.models import Brand, MasterProduct, ProductBarcode, ProductChangeLog, ProductSuggestion
from services import barcode_service

TRACKED_FIELDS = ("name", "brand_id", "category_id", "pack_size", "unit", "description", "mrp",
                  "tax_rate", "hsn_code", "status", "is_loose", "search_keywords")


def snapshot(product):
    return {f: "" if getattr(product, f) is None else str(getattr(product, f)) for f in TRACKED_FIELDS}


def log_changes(product, before, user):
    after = snapshot(product)
    for field in TRACKED_FIELDS:
        if before.get(field) != after[field]:
            ProductChangeLog.objects.create(product=product, changed_by=user, field=field,
                                            old_value=before.get(field, ""), new_value=after[field])


def find_duplicates(name, brand_id, pack_size, unit, exclude_id=None):
    qs = MasterProduct.objects.filter(name__iexact=name.strip(), brand_id=brand_id, pack_size=pack_size, unit=unit)
    return qs.exclude(pk=exclude_id) if exclude_id else qs


@transaction.atomic
def add_barcode(product, code, symbology=None, is_primary=False):
    clean, detected = barcode_service.validate_barcode(code)
    return ProductBarcode.objects.create(product=product, code=clean, symbology=symbology or detected,
                                         is_primary=is_primary)


@transaction.atomic
def approve_suggestion(suggestion, reviewer, existing_product=None):
    """Approval never makes a trusted product by itself: it links an existing product or creates a DRAFT."""
    if existing_product is None:
        brand = Brand.objects.get_or_create(name=suggestion.brand_name.strip())[0] if suggestion.brand_name.strip() else None
        existing_product = MasterProduct.objects.create(
            name=suggestion.name, brand=brand, pack_size=suggestion.pack_size, unit=suggestion.unit,
            description=suggestion.notes, status=MasterProduct.Status.DRAFT, created_by=reviewer,
        )
        if suggestion.barcode:
            try:
                add_barcode(existing_product, suggestion.barcode, is_primary=True)
            except Exception:  # invalid or already registered: admin resolves it manually
                pass
    suggestion.status = ProductSuggestion.Status.APPROVED
    suggestion.resulting_product = existing_product
    suggestion.reviewed_by = reviewer
    suggestion.save(update_fields=["status", "resulting_product", "reviewed_by"])
    return existing_product
