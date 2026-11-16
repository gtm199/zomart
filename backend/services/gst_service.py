"""GST maths for shops with GST billing ON. Decimal only; no floats anywhere. No database access except
require_confirmed_rate(), which only reads the product already loaded by the caller.

THE RULES (all tested in tests/test_gst.py):

1. Rounding: every money figure is rounded to the paisa, ROUND_HALF_UP, by round_paise() below. Nothing else rounds.
2. Discount: a line's discount is taken off the line's gross (price x qty) BEFORE tax. The taxable value is worked
   out from the discounted amount. A bill-level discount is first spread over the lines in proportion to their
   gross with allocate_discount() (largest remainder, so the parts add up to the exact discount).
3. Price includes GST (default, Indian MRP style):
       line_total = gross - discount              (what the customer pays for the line)
       tax        = line_total - round(line_total * 100 / (100 + rate))
   Price excludes GST ("tax added on top"):
       taxable    = gross - discount
       tax        = round(taxable * rate / 100)   (intra-state: each half rounded, see 4)
       line_total = taxable + tax
4. Intra-state (shop and customer in the same state, the default for a Delhi counter sale): CGST = SGST =
   round(tax / 2), and the taxable value is line_total - CGST - SGST so the line adds up exactly. This means
   the taxable value may differ from the formula by at most 1 paisa; the line always balances.
   Inter-state: IGST = the full tax. Decided only by place_of_supply().
5. Bill totals are the sums of the line figures. round_off is shown as its own line and is the only difference
   between the sum of lines and the grand total. GRAND_TOTAL_ROUND_TO = 0.01 means no rounding today (round_off
   is 0.00); set it to Decimal("1") to round bills to the nearest rupee, and the round-off line shows the change.
6. Composition scheme: no GST is charged or shown. The document is a "Bill of Supply"; each line's taxable value
   equals what the customer pays and all taxes are 0. "Price excludes GST" is ignored for these shops.
7. Delivery fee: no GST is applied to it in version one (vendor/CA decision, not guessed here).
"""
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from services.exceptions import BusinessRuleError

PAISA = Decimal("0.01")
HUNDRED = Decimal("100")
ZERO = Decimal("0.00")
GRAND_TOTAL_ROUND_TO = PAISA

# Suggestions only - the vendor can type any rate. Rates change; the vendor confirms every product with their CA.
RATE_SUGGESTIONS = [Decimal("0"), Decimal("5"), Decimal("12"), Decimal("18"), Decimal("28"), Decimal("40")]
MAX_RATE = Decimal("100")

INTRA, INTER = "intra_state", "inter_state"
REGULAR, COMPOSITION = "regular", "composition"

DOC_TAX_INVOICE = "tax_invoice"
DOC_BILL_OF_SUPPLY = "bill_of_supply"
DOC_BILL = "bill"
BILL_OF_SUPPLY_NOTE = "Composition taxable person, not eligible to collect tax on supplies"


def round_paise(value):
    """The single rounding rule for every GST figure."""
    return Decimal(value).quantize(PAISA, rounding=ROUND_HALF_UP)


# ---------------- validation helpers (used by serializers too) ----------------
def validate_rate(value):
    rate = Decimal(str(value))
    if rate < 0 or rate > MAX_RATE:
        raise ValueError("GST rate must be between 0 and 100.")
    if rate != rate.quantize(PAISA):
        raise ValueError("GST rate can have at most 2 decimal places.")
    return rate.quantize(PAISA)


def validate_hsn(value):
    code = (value or "").strip().replace(" ", "")
    if code and (not code.isdigit() or len(code) not in (4, 6, 8)):
        raise ValueError("HSN code must be 4, 6 or 8 digits.")
    return code


def require_confirmed_rate(shop_product, name=None):
    """Billing guard for GST shops: a product without a confirmed rate cannot be billed."""
    if shop_product.gst_rate is None:
        label = name or shop_product.master_product.display_name
        raise BusinessRuleError(
            f"{label} has no GST rate yet. Set and confirm its GST rate in Products before billing it.",
            "gst_rate_missing")
    return shop_product.gst_rate


# ---------------- place of supply ----------------
def place_of_supply(shop_state_code, destination_state_code=None):
    """ASSUMPTION (confirm with CA): for goods, the place of supply is where the goods are handed over / where the
    delivery ends. Counter sales and local deliveries are therefore intra-state, even for a business customer whose
    GSTIN is from another state. Pass destination_state_code only for goods delivered to another state; this is
    the single place to extend the rule."""
    if destination_state_code and destination_state_code != shop_state_code:
        return INTER
    return INTRA


def document_type(gst_enabled, scheme):
    if not gst_enabled:
        return DOC_BILL
    return DOC_BILL_OF_SUPPLY if scheme == COMPOSITION else DOC_TAX_INVOICE


# ---------------- discounts ----------------
def allocate_discount(grosses, discount):
    """Spread a bill-level discount over lines in proportion to their gross. Parts always sum to the discount."""
    discount = round_paise(discount)
    total = sum((Decimal(g) for g in grosses), Decimal("0"))
    if discount < 0 or discount > total:
        raise BusinessRuleError("Invalid discount.", "invalid_discount")
    if discount == 0 or total == 0:
        return [ZERO for _ in grosses]
    raw = [Decimal(g) * discount / total for g in grosses]
    parts = [r.quantize(PAISA, rounding="ROUND_DOWN") for r in raw]
    left = int((discount - sum(parts)) / PAISA)
    order = sorted(range(len(raw)), key=lambda i: (raw[i] - parts[i], -i), reverse=True)
    for i in order[:left]:
        parts[i] += PAISA
    return parts


# ---------------- line and bill maths ----------------
@dataclass
class LineTax:
    gross: Decimal
    discount: Decimal
    rate: Decimal
    price_includes_gst: bool
    taxable_value: Decimal
    cgst: Decimal
    sgst: Decimal
    igst: Decimal
    line_total: Decimal

    @property
    def tax(self):
        return self.cgst + self.sgst + self.igst


def compute_line(*, gross, discount=ZERO, rate, price_includes_gst=True, supply=INTRA, scheme=REGULAR):
    gross, discount = round_paise(gross), round_paise(discount)
    if discount < 0 or discount > gross:
        raise BusinessRuleError("Invalid discount.", "invalid_discount")
    rate = Decimal(rate)
    net = gross - discount
    if scheme == COMPOSITION:
        return LineTax(gross, discount, ZERO, True, net, ZERO, ZERO, ZERO, net)
    if price_includes_gst:
        line_total = net
        tax = line_total - round_paise(line_total * HUNDRED / (HUNDRED + rate))
    else:
        tax = round_paise(net * rate / HUNDRED)
        line_total = None
    if supply == INTER:
        igst, cgst, sgst = tax, ZERO, ZERO
    else:
        cgst = sgst = round_paise(tax / 2) if price_includes_gst else round_paise(net * rate / HUNDRED / 2)
        igst = ZERO
    if price_includes_gst:
        taxable = line_total - cgst - sgst - igst
    else:
        taxable = net
        line_total = net + cgst + sgst + igst
    return LineTax(gross, discount, rate, bool(price_includes_gst), taxable, cgst, sgst, igst, line_total)


@dataclass
class BillTax:
    lines: list
    document_type: str
    supply: str
    taxable_total: Decimal = ZERO
    cgst_total: Decimal = ZERO
    sgst_total: Decimal = ZERO
    igst_total: Decimal = ZERO
    lines_total: Decimal = ZERO
    round_off: Decimal = ZERO
    grand_total: Decimal = ZERO
    rate_summary: list = field(default_factory=list)

    @property
    def tax_total(self):
        return self.cgst_total + self.sgst_total + self.igst_total


def compute_bill(line_inputs, *, scheme=REGULAR, supply=INTRA, round_to=None):
    """line_inputs: dicts with gross, discount, rate, price_includes_gst. Returns BillTax with per-rate summary."""
    lines = [compute_line(scheme=scheme, supply=supply, **row) for row in line_inputs]
    bill = BillTax(lines=lines, supply=supply,
                   document_type=DOC_BILL_OF_SUPPLY if scheme == COMPOSITION else DOC_TAX_INVOICE)
    for ln in lines:
        bill.taxable_total += ln.taxable_value
        bill.cgst_total += ln.cgst
        bill.sgst_total += ln.sgst
        bill.igst_total += ln.igst
        bill.lines_total += ln.line_total
    bill.grand_total, bill.round_off = round_grand_total(bill.lines_total, round_to)
    bill.rate_summary = summarize_by_rate(lines)
    return bill


def round_grand_total(lines_total, round_to=None):
    """Returns (grand_total, round_off). round_off is shown on the bill as its own line."""
    step = Decimal(round_to or GRAND_TOTAL_ROUND_TO)
    grand = round_paise((Decimal(lines_total) / step).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * step)
    return grand, grand - lines_total


def summarize_by_rate(lines):
    """[{rate, taxable_value, cgst, sgst, igst, tax}] sorted by rate - used on invoices and in reports."""
    acc = {}
    for ln in lines:
        row = acc.setdefault(ln.rate, {"rate": ln.rate, "taxable_value": ZERO, "cgst": ZERO, "sgst": ZERO,
                                       "igst": ZERO})
        row["taxable_value"] += ln.taxable_value
        row["cgst"] += ln.cgst
        row["sgst"] += ln.sgst
        row["igst"] += ln.igst
    out = []
    for rate in sorted(acc):
        row = acc[rate]
        row["tax"] = row["cgst"] + row["sgst"] + row["igst"]
        out.append(row)
    return out


def summarize_sale_items(items):
    """Per-rate summary from saved SaleItem snapshots (never re-computed from current rates)."""
    acc = {}
    for it in items:
        row = acc.setdefault(it.tax_rate, {"rate": it.tax_rate, "taxable_value": ZERO, "cgst": ZERO, "sgst": ZERO,
                                           "igst": ZERO})
        row["taxable_value"] += it.taxable_value
        row["cgst"] += it.cgst
        row["sgst"] += it.sgst
        row["igst"] += it.igst
    out = []
    for rate in sorted(acc):
        row = acc[rate]
        row["tax"] = row["cgst"] + row["sgst"] + row["igst"]
        out.append(row)
    return out


# ---------------- amount in words (Indian numbering) ----------------
_ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve",
         "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
_TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


def _two(n):
    return _ONES[n] if n < 20 else (_TENS[n // 10] + (" " + _ONES[n % 10] if n % 10 else ""))


def _three(n):
    h, rest = divmod(n, 100)
    return " ".join(p for p in [(_ONES[h] + " Hundred") if h else "", _two(rest) if rest else ""] if p)


def amount_in_words(amount):
    amount = round_paise(amount)
    rupees, paise = int(amount), int((amount - int(amount)) * 100)
    if rupees == 0 and paise == 0:
        return "Rupees Zero Only"
    parts, n = [], rupees
    for size, label in ((10 ** 7, "Crore"), (10 ** 5, "Lakh"), (1000, "Thousand")):
        if n >= size:
            parts.append(f"{amount_in_words_int(n // size)} {label}")
            n %= size
    if n:
        parts.append(_three(n))
    text = "Rupees " + " ".join(parts) if parts else "Rupees Zero"
    if paise:
        text += f" and {_two(paise)} Paise"
    return text + " Only"


def amount_in_words_int(n):
    return amount_in_words(Decimal(n)).removeprefix("Rupees ").removesuffix(" Only")
