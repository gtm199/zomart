from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
MILLI = Decimal("0.001")


def money(value):
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def qty(value):
    return Decimal(value).quantize(MILLI, rounding=ROUND_HALF_UP)
