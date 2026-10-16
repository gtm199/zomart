"""Goods receipt and purchase returns. Stock always changes through inventory_service (ledgered)."""
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.catalog.models import MasterProduct
from apps.inventory.models import ShopProduct, StockMovement
from apps.purchases.models import Purchase, PurchaseItem
from apps.suppliers.models import Supplier, SupplierLedger, SupplierPayment
from services import inventory_service, supplier_service
from services.exceptions import BusinessRuleError
from services.money import money, qty

ALLOWED_METHODS = {"cash", "upi"}


def create_purchase(*, shop, user, client_txn_id, supplier_id, items, payments, invoice_number="",
                    purchase_date=None, notes=""):
    """Idempotent on (shop, client_txn_id). Returns (purchase, created)."""
    existing = Purchase.objects.filter(shop=shop, client_txn_id=client_txn_id).first()
    if existing:
        return existing, False
    try:
        with transaction.atomic():
            purchase = _create(shop, user, client_txn_id, supplier_id, items, payments, invoice_number,
                               purchase_date, notes)
    except IntegrityError:
        existing = Purchase.objects.filter(shop=shop, client_txn_id=client_txn_id).first()
        if existing:
            return existing, False
        raise
    return purchase, True


def _create(shop, user, client_txn_id, supplier_id, items, payments, invoice_number, purchase_date, notes):
    supplier = Supplier.objects.select_for_update().filter(shop=shop, pk=supplier_id, is_active=True).first()
    if supplier is None:
        raise BusinessRuleError("Supplier not found in this shop.", "supplier_not_found")
    if not items:
        raise BusinessRuleError("Add at least one product.", "empty_purchase")
    ids = [row["shop_product"] for row in items]
    if len(set(ids)) != len(ids):
        raise BusinessRuleError("Each product can appear only once per purchase.", "duplicate_product")

    products = {
        p.pk: p
        for p in ShopProduct.objects.select_for_update(of=("self",)).select_related("master_product__brand")
        .filter(shop=shop, pk__in=sorted(ids))
    }
    lines, total = [], Decimal("0")
    for row in items:
        sp = products.get(row["shop_product"])
        if sp is None:
            raise BusinessRuleError("A product does not belong to this shop.", "product_not_found")
        quantity = qty(row["quantity"])
        unit_cost = money(row["unit_cost"])
        if quantity <= 0 or unit_cost < 0:
            raise BusinessRuleError("Invalid quantity or cost.", "invalid_quantity")
        if sp.master_product.unit == MasterProduct.Unit.PIECE and quantity != quantity.to_integral_value():
            raise BusinessRuleError(f"{sp.master_product.display_name} is counted in whole pieces.", "invalid_quantity")
        line_total = money(quantity * unit_cost)
        total += line_total
        lines.append((sp, quantity, unit_cost, line_total, row.get("expiry_date")))

    paid, pay_rows = Decimal("0"), []
    for p in payments:
        amount = money(p["amount"])
        if p["method"] not in ALLOWED_METHODS or amount <= 0:
            raise BusinessRuleError("Invalid payment.", "invalid_payment")
        paid += amount
        pay_rows.append((p["method"], amount, p.get("reference", "")))
    if paid > total:
        raise BusinessRuleError("Payment is more than the purchase total.", "overpayment")
    due = total - paid

    purchase = Purchase.objects.create(
        shop=shop, supplier=supplier, invoice_number=invoice_number, client_txn_id=client_txn_id,
        purchase_date=purchase_date or timezone.localdate(), total=total, amount_paid=paid, amount_due=due,
        notes=notes, created_by=user)
    for sp, quantity, unit_cost, line_total, expiry in lines:
        PurchaseItem.objects.create(purchase=purchase, shop_product=sp, product_name=sp.master_product.display_name,
                                    quantity=quantity, unit_cost=unit_cost, line_total=line_total)
        inventory_service.apply_movement(
            shop_product_id=sp.pk, delta=quantity, movement_type=StockMovement.Type.PURCHASE, user=user,
            reference_type="purchase", reference_id=purchase.pk,
            note=f"Supplier invoice {invoice_number}".strip())
        # latest purchase cost; queryset update so we never overwrite the stock balance with a stale copy
        ShopProduct.objects.filter(pk=sp.pk).update(purchase_cost=unit_cost, updated_at=timezone.now())
        if expiry:
            # keep the older date if old stock is still on the shelf; otherwise use the new lot's date
            keep_old = sp.expiry_date and sp.stock_qty > 0 and sp.expiry_date < expiry
            if not keep_old:
                ShopProduct.objects.filter(pk=sp.pk).update(expiry_date=expiry)
                
    for method, amount, reference in pay_rows:
        SupplierPayment.objects.create(shop=shop, supplier=supplier, purchase=purchase,
                                       kind=SupplierPayment.Kind.PURCHASE, method=method, amount=amount,
                                       reference=reference, created_by=user)
    if due > 0:
        supplier_service.post_entry(supplier_id=supplier.pk, entry_type=SupplierLedger.EntryType.PURCHASE,
                                    amount=due, user=user, purchase=purchase,
                                    note=invoice_number or f"Purchase {purchase.pk}")
    return purchase


@transaction.atomic
def return_purchase(*, shop, user, purchase_id, items, refund_method="cash"):
    """Send goods back to the supplier: stock goes down, payable goes down first, any rest is a cash refund."""
    if refund_method not in ALLOWED_METHODS:
        raise BusinessRuleError("Invalid refund method.", "invalid_payment")
    purchase = Purchase.objects.select_for_update().get(shop=shop, pk=purchase_id)
    purchase_items = {i.pk: i for i in PurchaseItem.objects.select_for_update().filter(purchase=purchase)}
    value_total = Decimal("0")
    for row in items:
        item = purchase_items.get(row["purchase_item"])
        if item is None:
            raise BusinessRuleError("Item does not belong to this purchase.", "item_not_found")
        quantity = qty(row["quantity"])
        if quantity <= 0 or quantity > item.quantity - item.returned_qty:
            raise BusinessRuleError(f"Cannot return that quantity of {item.product_name}.", "invalid_quantity")
        value_total += money(item.line_total * quantity / item.quantity)
        item.returned_qty += quantity
        item.save(update_fields=["returned_qty"])
        inventory_service.apply_movement(  # raises InsufficientStock if the goods were already sold
            shop_product_id=item.shop_product_id, delta=-quantity, movement_type=StockMovement.Type.ADJUSTMENT,
            user=user, reference_type="purchase_return", reference_id=purchase.pk,
            note="Returned to supplier", allow_negative=False)
    reversal = min(value_total, purchase.amount_due - purchase.due_reversed)
    if reversal > 0:
        supplier_service.post_entry(supplier_id=purchase.supplier_id, entry_type=SupplierLedger.EntryType.RETURN,
                                    amount=-reversal, user=user, purchase=purchase,
                                    note=f"Return on purchase {purchase.pk}")
        purchase.due_reversed += reversal
    cash_back = value_total - reversal
    if cash_back > 0:
        SupplierPayment.objects.create(shop=shop, supplier=purchase.supplier, purchase=purchase,
                                       kind=SupplierPayment.Kind.REFUND, method=refund_method,
                                       amount=-cash_back, created_by=user)
    all_back = all(i.returned_qty >= i.quantity for i in purchase_items.values())
    purchase.status = Purchase.Status.RETURNED if all_back else Purchase.Status.PARTIALLY_RETURNED
    purchase.save(update_fields=["status", "due_reversed"])
    return purchase