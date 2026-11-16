from urllib.parse import quote


def _q(value):
    return f"{value.normalize():f}"


def build_gst_receipt_text(sale):
    """Tax invoice / bill of supply text, built only from the bill's own snapshot (never from current settings)."""
    from services import gst_service
    bos = sale.document_type == "bill_of_supply"
    lines = [f"*{sale.seller_legal_name}*"]
    if sale.seller_trade_name:
        lines.append(sale.seller_trade_name)
    if sale.seller_address:
        lines.append(sale.seller_address)
    lines.append(f"GSTIN: {sale.seller_gstin}")
    lines.append("*BILL OF SUPPLY*" if bos else "*TAX INVOICE*")
    lines.append(f"No: {sale.invoice_number}")
    lines.append("Date: " + sale.created_at.astimezone().strftime("%d-%b-%Y %I:%M %p"))
    if not bos:
        lines.append(f"Place of supply: {sale.place_of_supply}")
    if sale.customer_gstin:
        lines.append(f"Buyer: {sale.customer_gst_name or '-'} (GSTIN {sale.customer_gstin})")
    lines.append("-" * 24)
    items = list(sale.items.all())
    for it in items:
        lines.append(f"{it.product_name}\n  {_q(it.quantity)} x {it.unit_price} = {it.line_total}")
        if not bos:
            lines.append(f"  HSN {it.hsn_code or '-'} | GST {it.tax_rate}% | Taxable {it.taxable_value}")
    lines.append("-" * 24)
    if sale.discount_total:
        lines.append(f"Discount: {sale.discount_total}")
    if not bos:
        for row in gst_service.summarize_sale_items(items):
            if row["igst"]:
                lines.append(f"{row['rate']}%: Taxable {row['taxable_value']} IGST {row['igst']}")
            else:
                lines.append(f"{row['rate']}%: Taxable {row['taxable_value']} CGST {row['cgst']} SGST {row['sgst']}")
        lines.append(f"Total tax: {sale.cgst_total + sale.sgst_total + sale.igst_total}")
    if sale.round_off:
        lines.append(f"Round off: {sale.round_off}")
    lines.append(f"*Total: Rs {sale.total}*")
    lines.append(gst_service.amount_in_words(sale.total))
    lines.append(f"Paid: Rs {sale.amount_paid}")
    if sale.amount_due:
        lines.append(f"Due (credit): Rs {sale.amount_due}")
    if bos:
        lines.append(gst_service.BILL_OF_SUPPLY_NOTE)
    for note in sale.credit_notes.all():
        lines.append(f"Credit note {note.number}: Rs {note.total}")
    lines.append("Thank you! Please visit again.")
    return "\n".join(lines)


def build_receipt_text(sale):
    if sale.is_gst_document:
        return build_gst_receipt_text(sale)
    shop = sale.shop
    lines = [f"*{shop.name}*"]
    if shop.address:
        lines.append(shop.address)
    if shop.gstin:
        lines.append(f"GSTIN: {shop.gstin}")
    lines.append(f"Invoice: {sale.invoice_number}")
    lines.append(sale.created_at.astimezone().strftime("%d-%b-%Y %I:%M %p"))
    lines.append("-" * 24)
    for item in sale.items.all():
        lines.append(f"{item.product_name}\n  {item.quantity.normalize():f} x {item.unit_price} = {item.line_total}")
    lines.append("-" * 24)
    if sale.discount_total:
        lines.append(f"Discount: {sale.discount_total}")
    lines.append(f"*Total: Rs {sale.total}*")
    lines.append(f"Paid: Rs {sale.amount_paid}")
    if sale.amount_due:
        lines.append(f"Due (credit): Rs {sale.amount_due}")
    lines.append("Thank you! Please visit again.")
    return "\n".join(lines)


def clean_number(raw):
    """Digits only. A 10-digit Indian number gets 91 in front; numbers that already carry a country code are kept."""
    digits = "".join(c for c in (raw or "") if c.isdigit())
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) == 10:
        return "91" + digits
    return digits


def whatsapp_url(sale, text, phone=None):
    """Manual-share link. Uses the typed number first, then the customer's saved number."""
    number = clean_number(phone) if phone else ""
    if not number and sale.customer_id:
        number = clean_number(sale.customer.whatsapp_number or sale.customer.phone)
    return f"https://wa.me/{number}?text={quote(text)}"