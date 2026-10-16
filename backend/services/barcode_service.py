"""Barcode normalisation, GTIN check-digit validation and master-product lookup."""
from apps.catalog.models import ProductBarcode


def normalize(code):
    return "".join(str(code).split())


def gtin_checksum_ok(code):
    digits = [int(c) for c in code]
    body, check = digits[:-1], digits[-1]
    total = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return (10 - total % 10) % 10 == check


def detect_symbology(code):
    if code.isdigit():
        return {13: "EAN13", 8: "EAN8", 12: "UPCA"}.get(len(code), "OTHER")
    return "CODE128"


def validate_barcode(raw):
    """Return (clean_code, symbology) or raise ValueError."""
    code = normalize(raw)
    if not (3 <= len(code) <= 48):
        raise ValueError("Barcode must be 3 to 48 characters.")
    if code.isdigit() and len(code) in (8, 12, 13, 14) and not gtin_checksum_ok(code):
        raise ValueError("Barcode check digit is invalid.")
    return code, detect_symbology(code)


def lookup_candidates(code):
    """UPC-A scans can arrive as EAN-13 with a leading zero (and vice-versa)."""
    code = normalize(code)
    out = [code]
    if len(code) == 12 and code.isdigit():
        out.append("0" + code)
    if len(code) == 13 and code.startswith("0"):
        out.append(code[1:])
    return out


def find_master_product(code):
    barcode = (
        ProductBarcode.objects.select_related("product__brand", "product__category")
        .filter(code__in=lookup_candidates(code))
        .first()
    )
    return barcode.product if barcode else None
