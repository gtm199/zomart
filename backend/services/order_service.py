"""Online orders: placing, the shop's steps, and turning a finished order into a normal bill."""
import secrets
import uuid
from decimal import Decimal

from django.db import IntegrityError, transaction

from apps.catalog.models import MasterProduct
from apps.inventory.models import ShopProduct
from apps.orders.models import Order, OrderEvent, OrderItem, ShopperShop
from apps.shops.models import Shop
from services import billing_service, subscription_service
from services.exceptions import BusinessRuleError
from services.money import money, qty

S = Order.Status
F = Order.Fulfilment
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O or 1/I

ACTIVE = [S.PLACED, S.ACCEPTED, S.PACKED, S.OUT_FOR_DELIVERY, S.READY_FOR_PICKUP]
NEXT_STEPS = {
    S.PLACED: {S.ACCEPTED, S.REJECTED},
    S.ACCEPTED: {S.PACKED, S.CANCELLED},
    S.PACKED: {S.OUT_FOR_DELIVERY, S.READY_FOR_PICKUP, S.CANCELLED},
    S.OUT_FOR_DELIVERY: {S.COMPLETED, S.CANCELLED},
    S.READY_FOR_PICKUP: {S.COMPLETED, S.CANCELLED},
}


def ensure_store_code(shop):
    if shop.store_code:
        return shop.store_code
    while True:
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(6))
        if not Shop.objects.filter(store_code=code).exists():
            break
    shop.store_code = code
    shop.save(update_fields=["store_code"])
    return code


def takes_orders(shop):
    return bool(shop.is_active and shop.is_approved and shop.store_enabled and subscription_service.is_write_allowed(shop))


def delivery_fee_for(shop, fulfilment, subtotal):
    if fulfilment != F.DELIVERY:
        return Decimal("0.00")
    if shop.free_delivery_above is not None and subtotal >= shop.free_delivery_above:
        return Decimal("0.00")
    return shop.delivery_fee


def _event(order, status, note=""):
    OrderEvent.objects.create(order=order, status=status, note=note[:255])


# ---------------- the customer places an order ----------------
def place_order(*, shopper, shop_id, items, fulfilment, address, note, payment_method, client_txn_id):
    """Idempotent on (shopper, client_txn_id). Returns (order, created)."""
    existing = Order.objects.filter(shopper=shopper, client_txn_id=client_txn_id).first()
    if existing:
        return existing, False
    try:
        with transaction.atomic():
            order = _place(shopper, shop_id, items, fulfilment, address, note, payment_method, client_txn_id)
    except IntegrityError:
        existing = Order.objects.filter(shopper=shopper, client_txn_id=client_txn_id).first()
        if existing:
            return existing, False
        raise
    return order, True


def _place(shopper, shop_id, items, fulfilment, address, note, payment_method, client_txn_id):
    shop = Shop.objects.select_for_update().filter(pk=shop_id).first()
    if shop is None or not takes_orders(shop):
        raise BusinessRuleError("This shop is not taking online orders right now.", "shop_closed")
    if fulfilment == F.DELIVERY and not shop.accepts_delivery:
        raise BusinessRuleError("This shop does not deliver. Choose pickup.", "no_delivery")
    if fulfilment == F.PICKUP and not shop.accepts_pickup:
        raise BusinessRuleError("This shop does not offer pickup. Choose delivery.", "no_pickup")
    address = (address or "").strip()
    if fulfilment == F.DELIVERY and len(address) < 8:
        raise BusinessRuleError("Enter your full delivery address.", "address_required")

    ids = [row["shop_product"] for row in items]
    if not ids:
        raise BusinessRuleError("Your basket is empty.", "empty_order")
    if len(set(ids)) != len(ids):
        raise BusinessRuleError("An item appears twice. Change its quantity instead.", "duplicate_item")
    products = {
        p.pk: p for p in ShopProduct.objects.select_related("master_product").filter(
            shop=shop, pk__in=ids, is_enabled=True, online_visible=True,
            master_product__status=MasterProduct.Status.ACTIVE)
    }
    lines, subtotal = [], Decimal("0")
    for row in items:
        sp = products.get(row["shop_product"])
        if sp is None:
            raise BusinessRuleError("An item in your basket is no longer sold online by this shop.", "item_unavailable")
        master = sp.master_product
        quantity = qty(row["quantity"])
        if quantity <= 0 or quantity > 1000:
            raise BusinessRuleError("Invalid quantity.", "invalid_quantity")
        if master.unit == MasterProduct.Unit.PIECE and quantity != quantity.to_integral_value():
            raise BusinessRuleError(f"{master.display_name} is sold in whole pieces.", "invalid_quantity")
        if sp.stock_qty < quantity and not shop.allow_negative_stock:
            raise BusinessRuleError(f"{master.display_name} is out of stock for that quantity.", "out_of_stock")
        line_total = money(sp.selling_price * quantity)
        subtotal += line_total
        lines.append((sp, master, quantity, line_total))
    if subtotal < shop.min_order:
        raise BusinessRuleError(f"This shop's minimum order is Rs {shop.min_order}.", "below_minimum")

    fee = delivery_fee_for(shop, fulfilment, subtotal)
    shop.order_counter += 1
    shop.save(update_fields=["order_counter"])
    order = Order.objects.create(
        shop=shop, shopper=shopper, number=shop.order_counter, client_txn_id=client_txn_id, fulfilment=fulfilment,
        customer_name=shopper.name, customer_phone=shopper.phone,
        delivery_address=address if fulfilment == F.DELIVERY else "", note=(note or "")[:255],
        payment_method=payment_method, subtotal=subtotal, delivery_fee=fee, total=subtotal + fee)
    for sp, master, quantity, line_total in lines:
        OrderItem.objects.create(
            order=order, shop_product=sp, product_name=master.display_name,
            unit=master.unit if master.is_loose else "", ordered_quantity=quantity, quantity=quantity,
            unit_price=sp.selling_price, line_total=line_total)
    _event(order, S.PLACED)
    ShopperShop.objects.get_or_create(shopper=shopper, shop=shop)
    return order


@transaction.atomic
def customer_cancel(order_id, shopper):
    order = Order.objects.select_for_update().get(pk=order_id, shopper=shopper)
    if order.status != S.PLACED:
        raise BusinessRuleError("The shop has already started on this order. Please call the shop to cancel.", "too_late")
    order.status, order.reason = S.CANCELLED, "Cancelled by the customer"
    order.save(update_fields=["status", "reason", "updated_at"])
    _event(order, S.CANCELLED, order.reason)
    return order


# ---------------- the shop works on it ----------------
def _recount(order, items):
    subtotal = sum((i.line_total for i in items), Decimal("0"))
    order.subtotal = subtotal
    order.delivery_fee = delivery_fee_for(order.shop, order.fulfilment, subtotal)
    order.total = subtotal + order.delivery_fee


@transaction.atomic
def accept(order_id, shop, adjustments=None):
    """adjustments: [{'item': id, 'quantity': Decimal}] to lower or remove (0) items the shop cannot supply."""
    order = Order.objects.select_for_update().get(pk=order_id, shop=shop)
    if order.status != S.PLACED:
        raise BusinessRuleError("This order is not waiting for a decision.", "wrong_status")
    items = {i.pk: i for i in order.items.select_for_update()}
    for adj in adjustments or []:
        item = items.get(adj["item"])
        if item is None:
            raise BusinessRuleError("That item is not in this order.", "item_not_found")
        new_qty = qty(adj["quantity"])
        if new_qty < 0 or new_qty > item.ordered_quantity:
            raise BusinessRuleError("You can only lower a quantity.", "invalid_quantity")
        if new_qty == 0:
            #item.delete()
            #del items[item.pk]
            items.pop(item.pk)      # remove from the dict BEFORE delete() clears item.pk
            item.delete()
            changed = True
        else:
            item.quantity, item.line_total = new_qty, money(item.unit_price * new_qty)
            item.save(update_fields=["quantity", "line_total"])
    if not items:
        order.status, order.reason = S.REJECTED, "The shop could not supply any of the items"
        order.save(update_fields=["status", "reason", "updated_at"])
        _event(order, S.REJECTED, order.reason)
        return order
    _recount(order, list(items.values()))
    order.status = S.ACCEPTED
    order.save(update_fields=["status", "subtotal", "delivery_fee", "total", "updated_at"])
    changed = any(i.quantity != i.ordered_quantity for i in items.values()) or len(items) != order.items.count()
    _event(order, S.ACCEPTED, "Some quantities were changed" if changed else "")
    return order


@transaction.atomic
def move(order_id, shop, new_status, reason=""):
    order = Order.objects.select_for_update().get(pk=order_id, shop=shop)
    if new_status not in NEXT_STEPS.get(order.status, set()):
        raise BusinessRuleError(f"An order that is '{order.status}' cannot become '{new_status}'.", "wrong_status")
    if new_status == S.OUT_FOR_DELIVERY and order.fulfilment != F.DELIVERY:
        raise BusinessRuleError("This is a pickup order.", "wrong_fulfilment")
    if new_status == S.READY_FOR_PICKUP and order.fulfilment != F.PICKUP:
        raise BusinessRuleError("This is a delivery order.", "wrong_fulfilment")
    if new_status in (S.REJECTED, S.CANCELLED):
        if not reason.strip():
            raise BusinessRuleError("Give the customer a reason.", "reason_required")
        order.reason = reason.strip()[:255]
    order.status = new_status
    order.save(update_fields=["status", "reason", "updated_at"])
    _event(order, new_status, order.reason if new_status in (S.REJECTED, S.CANCELLED) else "")
    return order


@transaction.atomic
def complete(order_id, shop, user, payment_method):
    """Handed over and paid: this creates the normal bill, so stock and reports update."""
    order = Order.objects.select_for_update().get(pk=order_id, shop=shop)
    if order.status not in (S.OUT_FOR_DELIVERY, S.READY_FOR_PICKUP):
        raise BusinessRuleError("The order must be out for delivery or ready for pickup first.", "wrong_status")
    if payment_method not in ("cash", "upi"):
        raise BusinessRuleError("Choose cash or UPI.", "invalid_payment")
    sale, _ = billing_service.create_sale(
        shop=shop, user=user, client_txn_id=uuid.uuid5(uuid.NAMESPACE_URL, f"order-{order.pk}"),
        items=[{"shop_product": i.shop_product_id, "quantity": i.quantity, "unit_price": i.unit_price, "discount": Decimal("0")}
               for i in order.items.all()],
        payments=[{"method": payment_method, "amount": order.subtotal}],
        customer_id=None, notes=f"Online order #{order.number}", offline=True)
    order.sale, order.payment_method, order.status = sale, payment_method, S.COMPLETED
    order.save(update_fields=["sale", "payment_method", "status", "updated_at"])
    _event(order, S.COMPLETED)
    return order