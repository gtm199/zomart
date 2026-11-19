"""The only place stock and expiry batches change.

Batches (StockBatch): each lot with a known expiry date. Stock without a date is "undated".
  - stock coming in with an expiry date makes a new batch;
  - stock going out is taken from undated stock first, then from the batch that expires first (FEFO). This way a
    dated lot that may still be on the shelf is never forgotten, so its expiry alert is never missed;
  - a write-off or a purchase return takes from the named batch / that purchase's batch first;
  - the sum of quantity_left never exceeds stock_qty;
  - ShopProduct.expiry_date = earliest expiry among batches with pieces left (None when none are left).
"""
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum

from apps.inventory.models import ShopProduct, StockBatch, StockMovement
from services.exceptions import BusinessRuleError, InsufficientStock

ZERO = Decimal("0")
SOURCE_FOR = {StockMovement.Type.PURCHASE: StockBatch.Source.PURCHASE, StockMovement.Type.OPENING: StockBatch.Source.OPENING}


@transaction.atomic
def apply_movement(*, shop_product_id, delta, movement_type, user=None, reference_type="",
                   reference_id=None, note="", allow_negative=False, expiry_date=None, batch_no="", batch_id=None):
    """The only place stock changes. Locks the row, updates the balance, writes the ledger line and keeps the
    expiry batches in step. expiry_date/batch_no: for stock coming in. batch_id: take stock going out from this batch."""
    sp = ShopProduct.objects.select_for_update(of=("self",)).select_related("master_product__brand").get(pk=shop_product_id)
    new_balance = sp.stock_qty + delta
    if new_balance < 0 and not allow_negative:
        raise InsufficientStock(
            f"Not enough stock for {sp.master_product.display_name}: have {sp.stock_qty}, need {-delta}."
        )
    sp.stock_qty = new_balance
    sp.save(update_fields=["stock_qty", "updated_at"])
    movement = StockMovement.objects.create(
        shop=sp.shop, shop_product=sp, movement_type=movement_type, quantity_delta=delta,
        balance_after=new_balance, reference_type=reference_type, reference_id=reference_id,
        note=note, created_by=user,
    )
    if delta > 0 and expiry_date:
        StockBatch.objects.create(
            shop=sp.shop, shop_product=sp, expiry_date=expiry_date, batch_no=(batch_no or "").strip()[:40],
            quantity_received=delta, quantity_left=delta, source=SOURCE_FOR.get(movement_type, StockBatch.Source.RECEIVED),
            purchase_id=reference_id if reference_type == "purchase" else None, created_by=user)
    elif delta < 0:
        first = _open(sp)
        if batch_id is not None:
            first = first.filter(pk=batch_id)
        elif reference_type == "purchase_return" and reference_id:
            first = first.filter(purchase_id=reference_id)
        else:
            first = None
        if first is not None:
            _take(first, -delta)
    _fit(sp)
    sync_expiry(sp)
    return movement


def _open(sp):
    return StockBatch.objects.select_for_update().filter(shop_product=sp, quantity_left__gt=0).order_by("expiry_date", "id")


def _take(batches, quantity):
    """Takes up to `quantity` from these batches, earliest expiry first. Returns what is still to take."""
    for b in batches:
        if quantity <= 0:
            break
        part = min(b.quantity_left, quantity)
        b.quantity_left -= part
        b.save(update_fields=["quantity_left", "updated_at"])
        quantity -= part
    return quantity


def _fit(sp):
    """Batches never hold more than the stock: the extra comes off the earliest-expiring batches (FEFO)."""
    left = StockBatch.objects.filter(shop_product=sp, quantity_left__gt=0).aggregate(s=Sum("quantity_left"))["s"] or ZERO
    extra = left - max(sp.stock_qty, ZERO)
    if extra > 0:
        _take(_open(sp), extra)


def sync_expiry(sp):
    """ShopProduct.expiry_date follows the batches once the product has any. Products that never had a batch keep
    the date typed by hand (as before)."""
    if not StockBatch.objects.filter(shop_product=sp).exists():
        return
    first = StockBatch.objects.filter(shop_product=sp, quantity_left__gt=0).order_by("expiry_date").first()
    new = first.expiry_date if first else None
    if sp.expiry_date != new:
        ShopProduct.objects.filter(pk=sp.pk).update(expiry_date=new)
        sp.expiry_date = new


def undated_qty(sp):
    left = StockBatch.objects.filter(shop_product=sp, quantity_left__gt=0).aggregate(s=Sum("quantity_left"))["s"] or ZERO
    return max(sp.stock_qty - left, ZERO)


# ---------------- batch actions (stock screen) ----------------
def _locked(shop_product):
    return ShopProduct.objects.select_for_update(of=("self",)).get(pk=shop_product.pk)


def _batch_of(sp, batch_id):
    b = StockBatch.objects.select_for_update().filter(shop_product=sp, pk=batch_id).first()
    if b is None:
        raise BusinessRuleError("Batch not found.", "batch_not_found", 404)
    return b


@transaction.atomic
def date_stock_in_hand(shop_product, *, expiry_date, quantity, batch_no="", user=None):
    """Gives an expiry date to stock already on the shelf (no stock change)."""
    sp = _locked(shop_product)
    free = undated_qty(sp)
    if quantity <= 0:
        raise BusinessRuleError("Quantity must be more than 0.", "invalid_quantity")
    if quantity > free:
        raise BusinessRuleError(f"Only {free} piece(s) have no expiry date yet.", "more_than_undated")
    b = StockBatch.objects.create(shop=sp.shop, shop_product=sp, expiry_date=expiry_date, batch_no=(batch_no or "").strip()[:40],
                                  quantity_received=quantity, quantity_left=quantity, source=StockBatch.Source.MANUAL,
                                  created_by=user)
    sync_expiry(sp)
    return b


@transaction.atomic
def edit_batch(shop_product, batch_id, *, expiry_date=None, batch_no=None):
    sp = _locked(shop_product)
    b = _batch_of(sp, batch_id)
    if expiry_date is not None:
        b.expiry_date = expiry_date
    if batch_no is not None:
        b.batch_no = batch_no.strip()[:40]
    b.save()
    sync_expiry(sp)
    return b


@transaction.atomic
def write_off_batch(shop_product, batch_id, *, quantity=None, kind=StockMovement.Type.EXPIRED, note="", user=None):
    """Throws away pieces of this batch: stock goes down (an 'expired' or 'damage' stock entry)."""
    sp = _locked(shop_product)
    b = _batch_of(sp, batch_id)
    quantity = b.quantity_left if quantity is None else quantity
    if quantity <= 0 or quantity > b.quantity_left:
        raise BusinessRuleError(f"This batch has {b.quantity_left} piece(s) left.", "invalid_quantity")
    label = f"Batch exp {b.expiry_date:%d %b %Y}" + (f" ({b.batch_no})" if b.batch_no else "")
    return apply_movement(shop_product_id=sp.pk, delta=-quantity, movement_type=kind, user=user,
                          reference_type="batch", reference_id=b.pk, note=(note or label)[:255], batch_id=b.pk)


@transaction.atomic
def close_batch(shop_product, batch_id, *, note="", user=None):
    """'Not on the shelf any more' (already sold or counted wrong): the batch is closed, the stock does not change.
    Its pieces count as undated stock from now on."""
    sp = _locked(shop_product)
    b = _batch_of(sp, batch_id)
    b.quantity_left = ZERO
    b.note = (note or f"Closed by {getattr(user, 'username', 'staff')}: not on the shelf")[:255]
    b.save(update_fields=["quantity_left", "note", "updated_at"])
    sync_expiry(sp)
    return b


@transaction.atomic
def set_shelf_expiry(shop_product, expiry_date, user=None):
    """The old single 'expiry date of the stock in hand' field, kept working:
    a date corrects the earliest open batch, or dates all undated stock; blank closes all batches."""
    sp = _locked(shop_product)
    open_ = _open(sp)
    if expiry_date is None:
        open_.update(quantity_left=ZERO, note="Expiry date cleared")
        ShopProduct.objects.filter(pk=sp.pk).update(expiry_date=None)
        return
    first = open_.first()
    if first is not None:
        first.expiry_date = expiry_date
        first.save(update_fields=["expiry_date", "updated_at"])
    elif sp.stock_qty > 0:
        StockBatch.objects.create(shop=sp.shop, shop_product=sp, expiry_date=expiry_date, quantity_received=sp.stock_qty,
                                  quantity_left=sp.stock_qty, source=StockBatch.Source.MANUAL, created_by=user)
    else:   # no stock: keep the date as typed, like before
        ShopProduct.objects.filter(pk=sp.pk).update(expiry_date=expiry_date)
        return
    sync_expiry(sp)
