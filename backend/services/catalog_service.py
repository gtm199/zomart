from django.db import transaction
from django.utils import timezone

from apps.catalog.models import Brand, Category, MasterProduct, ProductBarcode, ProductChangeLog, ProductSuggestion
from apps.inventory.models import ShopProduct
from apps.shops.models import Shop, ShopNotification
from services import barcode_service
from services.exceptions import BusinessRuleError

TRACKED_FIELDS = ("name", "brand_id", "category_id", "pack_size", "unit", "description", "mrp",
                  "tax_rate", "hsn_code", "status", "is_loose", "search_keywords")
APPROVER_PERMISSION = "catalog.approve_masterproduct"
VERIFY_SOURCES = {"pack", "manufacturer", "distributor", "other"}


def snapshot(product):
    return {f: "" if getattr(product, f) is None else str(getattr(product, f)) for f in TRACKED_FIELDS}


# ---------------- who may activate / deactivate ----------------
def can_approve(user):
    return bool(user and (user.is_superuser or user.has_perm(APPROVER_PERMISSION)))


def ensure_can_set_status(user, old_status, new_status):
    """Editors may create and edit drafts and send them for review. Only approvers make products live or take them off."""
    if new_status == old_status:
        return
    if new_status in (MasterProduct.Status.ACTIVE, MasterProduct.Status.INACTIVE) and not can_approve(user):
        raise BusinessRuleError(
            "Only an approver can activate or deactivate products. Use 'Submit for review' instead.",
            "approval_required", 403)


# ---------------- change history ----------------
def log_changes(product, before, user):
    after = snapshot(product)
    changed = set()
    for field in TRACKED_FIELDS:
        if before.get(field) != after[field]:
            ProductChangeLog.objects.create(product=product, changed_by=user, field=field,
                                            old_value=before.get(field, ""), new_value=after[field])
            changed.add(field)
    if changed & {"mrp", "tax_rate"} and product.mrp_verified_at:
        # a changed price or tax rate has not been checked yet
        MasterProduct.objects.filter(pk=product.pk).update(mrp_verified_at=None, mrp_verified_by=None, mrp_source="")
        product.mrp_verified_at, product.mrp_verified_by, product.mrp_source = None, None, ""
    if "status" in changed and before.get("status") == MasterProduct.Status.ACTIVE \
            and after["status"] == MasterProduct.Status.INACTIVE:
        notify_deactivated(product)


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


# ---------------- verified MRP / GST ----------------
def mark_verified(product, user, source="pack"):
    if source not in VERIFY_SOURCES:
        raise BusinessRuleError("Unknown source.", "invalid_source")
    if product.mrp is None:
        raise BusinessRuleError("Set the MRP before marking it as verified.", "no_mrp")
    product.mrp_source = source
    product.mrp_verified_by = user
    product.mrp_verified_at = timezone.now()
    product.save(update_fields=["mrp_source", "mrp_verified_by", "mrp_verified_at", "updated_at"])


# ---------------- tell shops ----------------
def notify_deactivated(product):
    shop_ids = set(ShopProduct.objects.filter(master_product=product).values_list("shop_id", flat=True))
    ShopNotification.objects.bulk_create([
        ShopNotification(
            shop_id=sid, kind="product_deactivated", title="Product removed from catalogue",
            message=f"{product.display_name} is no longer in the catalogue and can't be sold. "
                    f"Check My Stock for what is left.")
        for sid in shop_ids])


# ---------------- explicit merge tools (never automatic) ----------------
@transaction.atomic
def merge_products(source_id, target_id, user=None, commit=False):
    """Move every shop listing and barcode of a duplicate (source) onto the right product (target)."""
    if source_id == target_id:
        raise BusinessRuleError("Choose two different products.", "same_product")
    source = MasterProduct.objects.select_for_update().get(pk=source_id)
    target = MasterProduct.objects.select_for_update().get(pk=target_id)
    if source.merged_into_id:
        raise BusinessRuleError("The source product was already merged.", "already_merged")
    src_shops = set(ShopProduct.objects.filter(master_product=source).values_list("shop_id", flat=True))
    tgt_shops = set(ShopProduct.objects.filter(master_product=target).values_list("shop_id", flat=True))
    both = src_shops & tgt_shops
    if both:
        names = list(Shop.objects.filter(pk__in=both).values_list("name", flat=True))
        raise BusinessRuleError(
            "These shops stock BOTH products, so their stock cannot be combined automatically: "
            + ", ".join(names) + ". Ask them to move the stock first.", "merge_conflict")
    report = {"source": source.display_name, "target": target.display_name,
              "shops_moved": len(src_shops), "barcodes_moved": source.barcodes.count()}
    if not commit:
        return report
    ShopProduct.objects.filter(master_product=source).update(master_product=target, updated_at=timezone.now())
    ProductBarcode.objects.filter(product=source).update(product=target, is_primary=False)
    source.status = MasterProduct.Status.INACTIVE
    source.merged_into = target
    source.save(update_fields=["status", "merged_into", "updated_at"])
    ProductSuggestion.objects.filter(resulting_product=source).update(resulting_product=target)
    ProductChangeLog.objects.create(product=source, changed_by=user, field="merged_into", new_value=str(target.pk))
    ProductChangeLog.objects.create(product=target, changed_by=user, field="merged_from", new_value=str(source.pk))
    return report


@transaction.atomic
def merge_brands(source_id, target_id, commit=False):
    if source_id == target_id:
        raise BusinessRuleError("Choose two different brands.", "same_brand")
    source, target = Brand.objects.get(pk=source_id), Brand.objects.get(pk=target_id)
    products = MasterProduct.objects.filter(brand=source)
    existing = {(p.name.lower(), p.pack_size, p.unit) for p in MasterProduct.objects.filter(brand=target)}
    clashes = [p.display_name for p in products if (p.name.lower(), p.pack_size, p.unit) in existing]
    if clashes:
        raise BusinessRuleError("These products would become duplicates; merge them first: " + ", ".join(clashes[:10]),
                                "merge_conflict")
    report = {"source": source.name, "target": target.name, "products_moved": products.count()}
    if commit:
        products.update(brand=target)
        source.delete()
    return report


@transaction.atomic
def merge_categories(source_id, target_id, commit=False):
    if source_id == target_id:
        raise BusinessRuleError("Choose two different categories.", "same_category")
    source, target = Category.objects.get(pk=source_id), Category.objects.get(pk=target_id)
    node = target
    while node is not None:  # the target must not sit inside the source
        if node.pk == source.pk:
            raise BusinessRuleError("The target is a sub-category of the source.", "merge_conflict")
        node = node.parent
    child_names = set(source.children.values_list("name", flat=True))
    if target.children.filter(name__in=child_names).exists():
        raise BusinessRuleError("Both categories have a sub-category with the same name; merge those first.", "merge_conflict")
    report = {"source": source.name, "target": target.name,
              "products_moved": MasterProduct.objects.filter(category=source).count(),
              "subcategories_moved": source.children.count()}
    if commit:
        MasterProduct.objects.filter(category=source).update(category=target)
        source.children.update(parent=target)
        source.delete()
    return report