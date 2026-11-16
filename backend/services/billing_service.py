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
from services import customer_service, gst_service, inventory_service, invoice_number_service
from services.exceptions import BusinessRuleError
from services.money import money, qty

ALLOWED_METHODS = {"cash", "upi"}
MAX_OFFLINE_AGE = timedelta(days=14)


def create_sale(*, shop, user, client_txn_id, items, payments, customer_id=None, notes="",
                offline=False, client_created_at=None, customer_gstin="", customer_gst_name="",
                gst_strict=True, pay_full_with=None):
    """Idempotent on (shop, client_txn_id). Returns (sale, created).

    offline=True means the bill was made on the phone (maybe without internet): it is always accepted,
    uses the price the cashier charged, and anything unusual is recorded in sale.review_note.

    GST (shops with GST billing ON, for bills made after it was switched on): tax is worked out by gst_service,
    numbers come from invoice_number_service, and the shop's GST details are copied onto the bill.
    gst_strict=True blocks a product with no confirmed GST rate. Phone uploads of bills already made offline
    pass gst_strict=False: the bill is kept, billed at the catalogue's suggested rate, and flagged for review.
    pay_full_with='cash'|'upi' records one payment of exactly the final total (used by online orders)."""
    existing = Sale.objects.filter(shop=shop, client_txn_id=client_txn_id).first()
    if existing:
        return existing, False
    try:
        with transaction.atomic():
            sale = _create_sale(shop, user, client_txn_id, items, payments, customer_id, notes,
                                offline, client_created_at, customer_gstin, customer_gst_name,
                                gst_strict, pay_full_with)
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


def customer_line_total(shop, sp, quantity, price=None, strict=True):
    """What a customer pays for a line at the current shelf price - used by online orders so their totals use the
    same GST rules as counter bills. Never exposes GST details; a GST product without a rate cannot be ordered."""
    gross = money((sp.selling_price if price is None else price) * quantity)
    if not shop.gst_enabled or shop.gst_scheme == gst_service.COMPOSITION:
        return gross
    if sp.gst_rate is None:
        if not strict:
            return gross   # completing the order will ask the shop to confirm the rate
        raise BusinessRuleError(f"{sp.master_product.display_name} can't be ordered online right now. "
                                "Please remove it from your basket.", "item_unavailable")
    return gst_service.compute_line(gross=gross, rate=sp.gst_rate, price_includes_gst=sp.price_includes_gst,
                                    supply=gst_service.place_of_supply(shop.gst_state_code)).line_total


def _gst_rate_for(sp, name, scheme, strict, flags):
    if scheme == gst_service.COMPOSITION:
        return Decimal("0")          # bill of supply: no tax is charged, so no rate is needed
    if sp.gst_rate is not None:
        return sp.gst_rate
    if strict:
        gst_service.require_confirmed_rate(sp, name)
    fallback = sp.master_product.tax_rate or Decimal("0")
    flags.append(f"{name}: no GST rate confirmed, billed at catalogue rate {fallback}% - confirm the rate and check this bill")
    return fallback


def _create_sale(shop, user, client_txn_id, items, payments, customer_id, notes, offline, client_created_at,
                 customer_gstin="", customer_gst_name="", gst_strict=True, pay_full_with=None):
    locked_shop = Shop.objects.select_for_update().get(pk=shop.pk)  # serialises invoice numbers per shop
    flags = []

    now = timezone.now()
    stale_clock, backdate_to = False, None
    if offline and client_created_at:
        if now - client_created_at > MAX_OFFLINE_AGE:
            stale_clock = True
        else:
            backdate_to = min(client_created_at, now)
    bill_time = backdate_to or now
    # Bills made before GST was switched on stay plain bills.
    gst_on = locked_shop.gst_enabled and (locked_shop.gst_enabled_at is None or bill_time >= locked_shop.gst_enabled_at)
    scheme = locked_shop.gst_scheme
    doc_type = gst_service.document_type(gst_on, scheme)
    supply = gst_service.place_of_supply(locked_shop.gst_state_code)

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
    taxable_total = cgst_total = sgst_total = igst_total = Decimal("0")
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
        lt = None
        if gst_on:
            rate = _gst_rate_for(sp, name, scheme, gst_strict, flags)
            lt = gst_service.compute_line(gross=gross, discount=discount, rate=rate,
                                          price_includes_gst=sp.price_includes_gst, supply=supply, scheme=scheme)
            rate, tax, line_total = lt.rate, lt.tax, lt.line_total
            taxable_total += lt.taxable_value
            cgst_total += lt.cgst
            sgst_total += lt.sgst
            igst_total += lt.igst
        else:
            # Non-GST shops: unchanged internal estimate (not printed as tax on the bill).
            rate = (master.tax_rate or Decimal("0")) if apply_tax else Decimal("0")
            tax = money(line_total * rate / (Decimal("100") + rate))  # prices are tax-inclusive
        subtotal += gross
        discount_total += discount
        tax_total += tax
        total += line_total
        lines.append((sp, master, quantity, discount, rate, tax, line_total, price, lt))

    round_off = Decimal("0")
    if gst_on:
        total, round_off = gst_service.round_grand_total(total)

    customer = None
    if customer_id:
        customer = Customer.objects.filter(shop=locked_shop, pk=customer_id, is_active=True).first()
        if customer is None:
            raise BusinessRuleError("Customer not found in this shop.", "customer_not_found")

    if pay_full_with is not None:
        if pay_full_with not in ALLOWED_METHODS:
            raise BusinessRuleError("Invalid payment.", "invalid_payment")
        payments = [{"method": pay_full_with, "amount": total}] if total > 0 else []
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

    if stale_clock:
        flags.append("Phone clock looks wrong or the bill is very old; recorded at upload time")

    if gst_on:
        invoice_number = invoice_number_service.next_number(locked_shop, doc_type, timezone.localtime(bill_time).date())
        gst_snapshot = dict(
            document_type=doc_type, taxable_total=taxable_total, cgst_total=cgst_total, sgst_total=sgst_total,
            igst_total=igst_total, round_off=round_off, seller_gstin=locked_shop.gstin,
            seller_legal_name=locked_shop.gst_legal_name or locked_shop.name,
            seller_trade_name=locked_shop.gst_trade_name,
            seller_address=locked_shop.gst_address or locked_shop.address,
            seller_state_code=locked_shop.gst_state_code, place_of_supply=locked_shop.gst_state_code,
            customer_gstin=customer_gstin or "", customer_gst_name=(customer_gst_name or "")[:150])
    else:
        locked_shop.invoice_counter += 1
        locked_shop.save(update_fields=["invoice_counter"])
        invoice_number = f"INV-{locked_shop.invoice_counter:06d}"
        gst_snapshot = {}
    sale = Sale.objects.create(
        shop=locked_shop, invoice_number=invoice_number,
        client_txn_id=client_txn_id, customer=customer, cashier=user, notes=notes,
        subtotal=subtotal, discount_total=discount_total, tax_total=tax_total,
        total=total, amount_paid=paid, amount_due=due,
        is_offline=bool(offline), needs_review=bool(flags), review_note="; ".join(flags)[:2000],
        client_created_at=client_created_at if offline else None,
        **gst_snapshot,
    )
    for sp, master, quantity, discount, rate, tax, line_total, price, lt in lines:
        primary = master.barcodes.order_by("-is_primary", "id").first()
        SaleItem.objects.create(
            sale=sale, shop_product=sp, product_name=master.display_name,
            barcode=primary.code if primary else "", quantity=quantity,
            unit_price=price, discount=discount, tax_rate=rate,
            tax_amount=tax, line_total=line_total, purchase_cost=sp.purchase_cost,
            unit=master.unit if master.is_loose else "",
            **({"hsn_code": sp.hsn_code, "price_includes_gst": lt.price_includes_gst, "taxable_value": lt.taxable_value,
                "cgst": lt.cgst, "sgst": lt.sgst, "igst": lt.igst} if lt is not None else {}),
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
    if hasattr(sale, "retention_marker"):   # its item details were archived
        raise BusinessRuleError("This bill's item details were archived, so it can no longer be returned here.", "archived_bill")
    sale_items = {i.pk: i for i in SaleItem.objects.select_for_update().filter(sale=sale)}
    refund_total = Decimal("0")
    returned = []
    for row in items:
        item = sale_items.get(row["sale_item"])
        if item is None:
            raise BusinessRuleError("Item does not belong to this sale.", "item_not_found")
        quantity = qty(row["quantity"])
        if quantity <= 0 or quantity > item.quantity - item.returned_qty:
            raise BusinessRuleError(f"Cannot return that quantity of {item.product_name}.", "invalid_quantity")
        line_refund = money(item.line_total * quantity / item.quantity)
        refund_total += line_refund
        returned.append((item, quantity, line_refund))
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
    if sale.is_gst_document:
        _issue_credit_note(shop, user, sale, returned)
    all_back = all(i.returned_qty >= i.quantity for i in sale_items.values())
    sale.status = Sale.Status.RETURNED if all_back else Sale.Status.PARTIALLY_RETURNED
    sale.save(update_fields=["status", "credit_reversed"])
    return sale


def _issue_credit_note(shop, user, sale, returned):
    """Credit note for the returned part of a GST document. Its amounts equal the refund (cash/UPI and credit
    reversal together), with tax reversed in proportion; the last return of a line takes whatever tax is left so
    the credit notes of a line add up exactly to the line's tax."""
    from django.db.models import Sum

    from apps.sales.models import CreditNote, CreditNoteItem

    number = invoice_number_service.next_number(shop, "credit_note", timezone.localdate())
    note = CreditNote.objects.create(
        shop_id=shop.pk, sale=sale, number=number, original_invoice_number=sale.invoice_number,
        original_document_type=sale.document_type, seller_gstin=sale.seller_gstin,
        seller_legal_name=sale.seller_legal_name, created_by=user)
    totals = {"taxable_total": Decimal("0"), "cgst_total": Decimal("0"), "sgst_total": Decimal("0"),
              "igst_total": Decimal("0"), "total": Decimal("0")}
    for item, quantity, amount in returned:
        if item.returned_qty >= item.quantity:   # final return of this line: take the remainder
            prior = CreditNoteItem.objects.filter(credit_note__sale=sale, sale_item_id_ref=item.pk).exclude(
                credit_note=note).aggregate(c=Sum("cgst"), s=Sum("sgst"), i=Sum("igst"))
            cgst = item.cgst - (prior["c"] or 0)
            sgst = item.sgst - (prior["s"] or 0)
            igst = item.igst - (prior["i"] or 0)
        else:
            ratio = quantity / item.quantity
            cgst = gst_service.round_paise(item.cgst * ratio)
            sgst = cgst if item.sgst == item.cgst else gst_service.round_paise(item.sgst * ratio)
            igst = gst_service.round_paise(item.igst * ratio)
        taxable = amount - cgst - sgst - igst
        CreditNoteItem.objects.create(
            credit_note=note, sale_item_id_ref=item.pk, product_name=item.product_name, hsn_code=item.hsn_code,
            quantity=quantity, gst_rate=item.tax_rate, taxable_value=taxable, cgst=cgst, sgst=sgst, igst=igst,
            line_total=amount)
        totals["taxable_total"] += taxable
        totals["cgst_total"] += cgst
        totals["sgst_total"] += sgst
        totals["igst_total"] += igst
        totals["total"] += amount
    for k, v in totals.items():
        setattr(note, k, v)
    note.save(update_fields=list(totals))
    return note
