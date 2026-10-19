"""Checkout and returns. One atomic transaction updates sale, items, payments, stock and ledger."""
from collections import OrderedDict
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.catalog.models import MasterProduct
from apps.customers.models import Customer, CustomerLedger
from apps.inventory.models import ShopProduct, StockMovement
from apps.sales.models import Payment, Sale, SaleItem
from apps.shops.models import Shop
from services import customer_service, inventory_service
from services.exceptions import BusinessRuleError
from services.money import money, qty

ALLOWED_METHODS = {"cash", "upi"}
MAX_OFFLINE_AGE = timedelta(days=14)


def create_sale(*, shop, user, client_txn_id, items, payments, customer_id=None, notes="",
                offline=False, client_created_at=None):
    """Idempotent on (shop, client_txn_id). Returns (sale, created).

    offline=True means the bill was made on the phone (maybe without internet): it is always accepted,
    uses the price the cashier charged, and anything unusual is recorded in sale.review_note."""
    existing = Sale.objects.filter(shop=shop, client_txn_id=client_txn_id).first()
    if existing:
        return existing, False
    try:
        with transaction.atomic():
            sale = _create_sale(shop, user, client_txn_id, items, payments, customer_id, notes,
                                offline, client_created_at)
    except IntegrityError:
        existing = Sale.objects.filter(shop=shop, client_txn_id=client_txn_id).first()
        if existing:
            return existing, False
        raise
    return sale, True


def _backdate(sale, when):
    """Give the bill and its payments/ledger lines the time it was made on the phone."""
    Sale.objects.filter(pk=sale.pk).update(created_at=when)
    Payment.objects.filter(sale=sale).update(created_at=when)
    CustomerLedger.objects.filter(sale=sale).update(created_at=when)


def _create_sale(shop, user, client_txn_id, items, payments, customer_id, notes, offline, client_created_at):
    locked_shop = Shop.objects.select_for_update().get(pk=shop.pk)  # serialises invoice numbers per shop
    flags = []

    merged = OrderedDict()
    for row in items:
        entry = merged.setdefault(row["shop_product"], {"quantity": Decimal("0"), "discount": Decimal("0"),
                                                        "unit_price": row.get("unit_price")})
        entry["quantity"] += Decimal(row["quantity"])
        entry["discount"] += Decimal(row.get("discount") or 0)
    if not merged:
        raise BusinessRuleError("The cart is empty.", "empty_cart")

    products = {
        p.pk: p
        for p in ShopProduct.objects.select_for_update(of=("self",))
        .select_related("master_product__brand")
        .filter(shop=locked_shop, pk__in=sorted(merged))
    }

    apply_tax = getattr(settings, "APPLY_TAX", True)
    lines = []
    subtotal = discount_total = tax_total = total = Decimal("0")
    for pid, entry in merged.items():
        sp = products.get(pid)
        if sp is None:
            raise BusinessRuleError("A product in the cart does not belong to this shop.", "product_not_found")
        master = sp.master_product
        name = master.display_name
        if not sp.is_enabled or master.status != MasterProduct.Status.ACTIVE:
            if not offline:
                raise BusinessRuleError(f"{name} is not available for sale.", "product_unavailable")
            flags.append(f"{name} was switched off or deactivated")
        quantity = qty(entry["quantity"])
        if quantity <= 0:
            raise BusinessRuleError("Quantity must be greater than zero.", "invalid_quantity")
        if master.unit == MasterProduct.Unit.PIECE and quantity != quantity.to_integral_value():
            raise BusinessRuleError(f"{name} is sold in whole pieces.", "invalid_quantity")

        price = sp.selling_price
        if offline and entry.get("unit_price") is not None:
            charged = money(entry["unit_price"])
            if charged < 0:
                raise BusinessRuleError("Invalid price.", "invalid_price")
            if charged != sp.selling_price:
                flags.append(f"{name}: charged {charged}, shop price is now {sp.selling_price}")
            price = charged  # the customer paid what the cashier saw
        if offline and sp.stock_qty - quantity < 0 and not locked_shop.allow_negative_stock:
            flags.append(f"{name}: stock went below zero (had {sp.stock_qty}, sold {quantity}) - recount")

        gross = money(price * quantity)
        discount = money(entry["discount"])
        if discount < 0 or discount > gross:
            raise BusinessRuleError("Invalid discount.", "invalid_discount")
        line_total = gross - discount
        rate = (master.tax_rate or Decimal("0")) if apply_tax else Decimal("0")
        tax = money(line_total * rate / (Decimal("100") + rate))  # prices are tax-inclusive
        subtotal += gross
        discount_total += discount
        tax_total += tax
        total += line_total
        lines.append((sp, master, quantity, discount, rate, tax, line_total, price))

    customer = None
    if customer_id:
        customer = Customer.objects.filter(shop=locked_shop, pk=customer_id, is_active=True).first()
        if customer is None:
            raise BusinessRuleError("Customer not found in this shop.", "customer_not_found")

    paid = Decimal("0")
    pay_rows = []
    for p in payments:
        amount = money(p["amount"])
        if p["method"] not in ALLOWED_METHODS or amount <= 0:
            raise BusinessRuleError("Invalid payment.", "invalid_payment")
        paid += amount
        pay_rows.append((p["method"], amount, p.get("reference", "")))
    if paid > total:
        raise BusinessRuleError("Payment is more than the bill total.", "overpayment")
    due = total - paid
    if due > 0 and customer is None:
        raise BusinessRuleError("Select a customer to sell on credit.", "customer_required")
    if due > 0 and customer.credit_limit is not None and customer.balance + due > customer.credit_limit:
        note = (f"{customer.name} is over the credit limit (limit {customer.credit_limit}, "
                f"owes {customer.balance}, this bill adds {due})")
        if offline:
            flags.append(note)  # the goods already left the shop: keep the bill, tell the owner
        else:
            raise BusinessRuleError(note, "credit_limit", 409)

    backdate_to = None
    if offline and client_created_at:
        now = timezone.now()
        if now - client_created_at > MAX_OFFLINE_AGE:
            flags.append("Phone clock looks wrong or the bill is very old; recorded at upload time")
        else:
            backdate_to = min(client_created_at, now)

    locked_shop.invoice_counter += 1
    locked_shop.save(update_fields=["invoice_counter"])
    sale = Sale.objects.create(
        shop=locked_shop, invoice_number=f"INV-{locked_shop.invoice_counter:06d}",
        client_txn_id=client_txn_id, customer=customer, cashier=user, notes=notes,
        subtotal=subtotal, discount_total=discount_total, tax_total=tax_total,
        total=total, amount_paid=paid, amount_due=due,
        is_offline=bool(offline), needs_review=bool(flags), review_note="; ".join(flags)[:2000],
        client_created_at=client_created_at if offline else None,
    )
    for sp, master, quantity, discount, rate, tax, line_total, price in lines:
        primary = master.barcodes.order_by("-is_primary", "id").first()
        SaleItem.objects.create(
            sale=sale, shop_product=sp, product_name=master.display_name,
            barcode=primary.code if primary else "", quantity=quantity,
            unit_price=price, discount=discount, tax_rate=rate,
            tax_amount=tax, line_total=line_total, purchase_cost=sp.purchase_cost,
            unit=master.unit if master.is_loose else "",
        )
        inventory_service.apply_movement(
            shop_product_id=sp.pk, delta=-quantity, movement_type=StockMovement.Type.SALE,
            user=user, reference_type="sale", reference_id=sale.pk,
            allow_negative=locked_shop.allow_negative_stock or bool(offline),
        )
    for method, amount, reference in pay_rows:
        Payment.objects.create(shop=locked_shop, sale=sale, customer=customer, kind=Payment.Kind.SALE,
                               method=method, amount=amount, reference=reference, created_by=user)
    if due > 0:
        customer_service.post_entry(customer_id=customer.pk, entry_type=CustomerLedger.EntryType.CREDIT_SALE,
                                    amount=due, user=user, sale=sale, note=sale.invoice_number)
    if backdate_to:
        _backdate(sale, backdate_to)
    return sale


@transaction.atomic
def return_items(*, shop, user, sale_id, items, refund_method="cash"):
    """items: [{'sale_item': id, 'quantity': Decimal}]. Restocks and refunds proportionally."""
    if refund_method not in ALLOWED_METHODS:
        raise BusinessRuleError("Invalid refund method.", "invalid_payment")
    sale = Sale.objects.select_for_update().get(shop=shop, pk=sale_id)
    sale_items = {i.pk: i for i in SaleItem.objects.select_for_update().filter(sale=sale)}
    refund_total = Decimal("0")
    for row in items:
        item = sale_items.get(row["sale_item"])
        if item is None:
            raise BusinessRuleError("Item does not belong to this sale.", "item_not_found")
        quantity = qty(row["quantity"])
        if quantity <= 0 or quantity > item.quantity - item.returned_qty:
            raise BusinessRuleError(f"Cannot return that quantity of {item.product_name}.", "invalid_quantity")
        refund_total += money(item.line_total * quantity / item.quantity)
        item.returned_qty += quantity
        item.save(update_fields=["returned_qty"])
        inventory_service.apply_movement(
            shop_product_id=item.shop_product_id, delta=quantity, movement_type=StockMovement.Type.RETURN,
            user=user, reference_type="sale", reference_id=sale.pk, allow_negative=True,
        )
    credit_reversal = Decimal("0")
    if sale.customer_id and sale.amount_due > sale.credit_reversed:
        credit_reversal = min(refund_total, sale.amount_due - sale.credit_reversed)
        customer_service.post_entry(customer_id=sale.customer_id, entry_type=CustomerLedger.EntryType.REFUND,
                                    amount=-credit_reversal, user=user, sale=sale, note="Return " + sale.invoice_number)
        sale.credit_reversed += credit_reversal
    cash_refund = refund_total - credit_reversal
    if cash_refund > 0:
        Payment.objects.create(shop=shop, sale=sale, customer=sale.customer, kind=Payment.Kind.REFUND,
                               method=refund_method, amount=-cash_refund, created_by=user)
    all_back = all(i.returned_qty >= i.quantity for i in sale_items.values())
    sale.status = Sale.Status.RETURNED if all_back else Sale.Status.PARTIALLY_RETURNED
    sale.save(update_fields=["status", "credit_reversed"])
    return sale
