"""GSTIN *format* check. Pure functions, no database.

This only checks that a GSTIN is well formed (length, state code, PAN pattern, check character).
It cannot tell whether the GSTIN is real, registered or active: that needs the GST portal.
"""
import re

FORMAT_ONLY_NOTE = ("Format check only: this confirms the GSTIN is well formed, not that it is registered "
                    "or active. Verify it on the GST portal (services.gst.gov.in > Search Taxpayer).")

# 2-digit state code + PAN (5 letters, 4 digits, 1 letter) + entity number + 'Z' + check character
_PATTERN = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

# ASSUMPTION (confirm with CA if it matters): state codes 01-38 plus 97 (Other Territory) and 99 (Centre Jurisdiction).
VALID_STATE_CODES = {f"{n:02d}" for n in range(1, 39)} | {"97", "99"}
DELHI_STATE_CODE = "07"


class GstinError(ValueError):
    pass


def normalize(value):
    return (value or "").strip().upper().replace(" ", "")


def check_char(first14):
    """GSTIN check character (base-36, alternating weights 1 and 2)."""
    total = 0
    for i, ch in enumerate(first14):
        product = _CHARS.index(ch) * (2 if i % 2 else 1)
        total += product // 36 + product % 36
    return _CHARS[(36 - total % 36) % 36]


def validate_gstin(value, *, state_code=None):
    """Returns the normalised GSTIN or raises GstinError with a message a vendor can act on."""
    g = normalize(value)
    if len(g) != 15:
        raise GstinError("GSTIN must be exactly 15 characters.")
    if not _PATTERN.match(g):
        raise GstinError("GSTIN format is wrong. Expected: 2-digit state code, 10-character PAN, entity number, 'Z', check character.")
    if g[:2] not in VALID_STATE_CODES:
        raise GstinError(f"GSTIN starts with {g[:2]}, which is not a valid state code.")
    if state_code and g[:2] != state_code:
        raise GstinError(f"GSTIN starts with {g[:2]} but the shop's state code is {state_code}.")
    if check_char(g[:14]) != g[14]:
        raise GstinError("GSTIN check character does not match. Please re-check each character.")
    return g


def is_valid_gstin(value, *, state_code=None):
    try:
        validate_gstin(value, state_code=state_code)
        return True
    except GstinError:
        return False


def mask(value):
    """For anything that might end up in logs or messages: 07ABCDE****F1Z5 style."""
    g = normalize(value)
    return f"{g[:7]}****{g[11:]}" if len(g) == 15 else "****"
