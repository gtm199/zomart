"""Customer app sign-in: the customer types their mobile number, username or email in one box.

How the box is read (no guessing between accounts):
  - contains "@"            -> email (any letter case)
  - 10-digit mobile number  -> mobile (spaces, +91 or a leading 0 are fine)
  - anything else           -> username (any letter case; a username always starts with a letter)
"""
import re

from apps.orders.models import Shopper


def _digits(value):
    return re.sub(r"\D", "", value)


def kind_of(login):
    value = (login or "").strip()
    if "@" in value:
        return "email"
    if re.fullmatch(r"[+\d\s\-()]+", value) and len(_digits(value)) >= 10:
        return "phone"
    return "username"


def throttle_key(login):
    """The same account gets the same key however it is typed, so the try limit cannot be dodged."""
    value = (login or "").strip()
    kind = kind_of(value)
    if kind == "phone":
        return f"phone:{_digits(value)[-10:]}"
    return f"{kind}:{value.lower()}" if value else ""


def find_shopper(login, password):
    """The active customer for this login and password, or None (never says which part was wrong)."""
    value = (login or "").strip()
    kind = kind_of(value)
    qs = Shopper.objects.filter(is_active=True)
    if kind == "email":
        shopper = qs.filter(email__iexact=value).first()
    elif kind == "phone":
        shopper = qs.filter(phone=_digits(value)[-10:]).first()
    else:
        shopper = qs.filter(username__iexact=value).first() if value else None
    if shopper is None or not shopper.check_password(password):
        return None
    return shopper
