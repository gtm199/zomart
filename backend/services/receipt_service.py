from urllib.parse import quote


def build_receipt_text(sale):
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