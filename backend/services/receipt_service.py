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


def whatsapp_url(sale, text):
    """Manual-share fallback (wa.me). Official Cloud API sending is listed in FUTURE_FEATURES.txt."""
    number = ""
    if sale.customer_id:
        raw = sale.customer.whatsapp_number or sale.customer.phone
        digits = "".join(c for c in raw if c.isdigit())
        if digits:
            number = digits if len(digits) > 10 else "91" + digits
    return f"https://wa.me/{number}?text={quote(text)}"
