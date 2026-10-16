from django.db import transaction

from apps.inventory.models import ShopProduct, StockMovement
from services.exceptions import InsufficientStock


@transaction.atomic
def apply_movement(*, shop_product_id, delta, movement_type, user=None, reference_type="",
                   reference_id=None, note="", allow_negative=False):
    """The only place stock changes. Locks the row, updates the balance and writes the ledger line."""
    sp = ShopProduct.objects.select_for_update(of=("self",)).select_related("master_product__brand").get(pk=shop_product_id)
    new_balance = sp.stock_qty + delta
    if new_balance < 0 and not allow_negative:
        raise InsufficientStock(
            f"Not enough stock for {sp.master_product.display_name}: have {sp.stock_qty}, need {-delta}."
        )
    sp.stock_qty = new_balance
    sp.save(update_fields=["stock_qty", "updated_at"])
    return StockMovement.objects.create(
        shop=sp.shop, shop_product=sp, movement_type=movement_type, quantity_delta=delta,
        balance_after=new_balance, reference_type=reference_type, reference_id=reference_id,
        note=note, created_by=user,
    )
