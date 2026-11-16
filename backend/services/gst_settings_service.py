"""Shop-level GST settings. Views only call update_gst_settings(); all rules live here.

Rules:
- Switching GST on needs a GSTIN that passes the format check (format only, not a registration check),
  and the vendor must send gst_scheme in the same request (explicit confirmation; default shown is "regular").
- Switching GST off never deletes anything: GSTIN, names and past invoices stay as they were.
- gst_enabled_at records the moment GST was (re)switched on. Bills keep their own snapshot, so earlier bills never change.
- gst_price_mode is the shop-wide default (inclusive / exclusive). New products take it; existing products change only
  when the owner asks (apply_price_mode_to_all). Already-made bills never change. Composition shops charge no GST, so
  for them the mode has no effect on bills.
"""
from django.db import transaction
from django.utils import timezone

from apps.inventory.models import ShopProduct
from apps.shops.models import Shop, ShopGstChange
from services.exceptions import BusinessRuleError
from services.gst_service import RATE_SUGGESTIONS
from services.gstin import FORMAT_ONLY_NOTE, VALID_STATE_CODES, GstinError, validate_gstin

EDITABLE = ("gst_enabled", "gstin", "gst_legal_name", "gst_trade_name", "gst_address", "gst_scheme", "gst_state_code",
            "gst_price_mode", "apply_price_mode_to_all")
MRP_NOTE = ("Legal Metrology rules: MRP already includes all taxes, and packaged goods cannot be sold above MRP. "
            "With 'GST added on top', keep the selling price low enough that price + GST stays within the MRP.")


def settings_payload(shop):
    return {
        "gst_enabled": shop.gst_enabled,
        "gst_enabled_at": shop.gst_enabled_at,
        "gstin": shop.gstin,
        "gst_legal_name": shop.gst_legal_name,
        "gst_trade_name": shop.gst_trade_name,
        "gst_address": shop.gst_address,
        "gst_scheme": shop.gst_scheme,
        "gst_state_code": shop.gst_state_code,
        "gst_price_mode": shop.gst_price_mode,
        "products_count": ShopProduct.objects.filter(shop=shop).count(),
        "products_tax_on_top": ShopProduct.objects.filter(shop=shop, price_includes_gst=False).count(),
        "mrp_note": MRP_NOTE,
        "gstin_check_note": FORMAT_ONLY_NOTE,
        "gst_rate_suggestions": [str(r) for r in RATE_SUGGESTIONS],
    }


@transaction.atomic
def update_gst_settings(*, shop, user, data):
    """data: dict with any of EDITABLE keys (already type-checked by the serializer)."""
    locked = Shop.objects.select_for_update().get(pk=shop.pk)
    was_enabled, old_gstin, old_scheme = locked.gst_enabled, locked.gstin, locked.gst_scheme

    if "gst_state_code" in data:
        code = (data["gst_state_code"] or "").strip()
        if code not in VALID_STATE_CODES:
            raise BusinessRuleError("Invalid state code.", "invalid_state_code")
        locked.gst_state_code = code
    for field in ("gst_legal_name", "gst_trade_name", "gst_address"):
        if field in data:
            setattr(locked, field, (data[field] or "").strip())
    if "gst_scheme" in data:
        if data["gst_scheme"] not in Shop.GstScheme.values:
            raise BusinessRuleError("Invalid GST scheme.", "invalid_gst_scheme")
        locked.gst_scheme = data["gst_scheme"]
    if "gst_price_mode" in data:
        if data["gst_price_mode"] not in Shop.GstPriceMode.values:
            raise BusinessRuleError("Invalid price mode.", "invalid_price_mode")
        locked.gst_price_mode = data["gst_price_mode"]
    if data.get("apply_price_mode_to_all"):
        # One query; updated_at changes so every phone downloads the new setting on its next sync.
        ShopProduct.objects.filter(shop=locked).update(
            price_includes_gst=locked.gst_price_mode == Shop.GstPriceMode.INCLUSIVE, updated_at=timezone.now())

    enable = data.get("gst_enabled", locked.gst_enabled)
    gstin = data["gstin"] if "gstin" in data else locked.gstin
    gstin = (gstin or "").strip()
    if gstin:
        try:
            gstin = validate_gstin(gstin, state_code=locked.gst_state_code)
        except GstinError as exc:
            raise BusinessRuleError(str(exc), "invalid_gstin")
    elif enable:
        raise BusinessRuleError("Enter the shop's GSTIN before switching GST billing on.", "gstin_required")
    locked.gstin = gstin

    if enable and not was_enabled and "gst_scheme" not in data:
        # The vendor must actively choose regular or composition each time GST is switched on.
        raise BusinessRuleError("Confirm your GST scheme (Regular or Composition) to switch GST billing on.",
                                "gst_scheme_confirmation_required")
    if enable and not locked.gst_legal_name:
        locked.gst_legal_name = locked.name   # vendor can correct it; printed on tax invoices
    locked.gst_enabled = bool(enable)
    if locked.gst_enabled and not was_enabled:
        locked.gst_enabled_at = timezone.now()
    locked.save()

    gstin_changed = locked.gstin != old_gstin
    if locked.gst_enabled != was_enabled or locked.gst_scheme != old_scheme or gstin_changed:
        ShopGstChange.objects.create(shop=locked, changed_by=user, gst_enabled=locked.gst_enabled,
                                     gst_scheme=locked.gst_scheme, gstin_changed=gstin_changed)
    return locked
