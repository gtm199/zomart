"""Customer (Shopper) password reset by a 6-digit code emailed via the normal mail backend (Brevo in production)."""
import hashlib
import hmac
import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.orders.models import Shopper, ShopperPasswordResetCode, ShopperToken
from services.exceptions import BusinessRuleError
from services.password_reset_service import CODE_MINUTES, MAX_CODES_PER_HOUR, MAX_WRONG_TRIES

logger = logging.getLogger(__name__)
MIN_PASSWORD = 6  # same rule as customer registration


def _hash(shopper, code):
    # "shopper:" prefix so a customer code can never match a staff code
    return hmac.new(settings.SECRET_KEY.encode(), f"shopper:{shopper.pk}:{code}".encode(), hashlib.sha256).hexdigest()


def _find(email):
    return Shopper.objects.filter(email__iexact=(email or "").strip(), is_active=True).exclude(email="").first()


def request_code(email):
    """Sends a code if the email belongs to a customer. Says nothing either way."""
    shopper = _find(email)
    if shopper is None:
        return
    now = timezone.now()
    if ShopperPasswordResetCode.objects.filter(shopper=shopper, created_at__gte=now - timedelta(hours=1)).count() >= MAX_CODES_PER_HOUR:
        return
    ShopperPasswordResetCode.objects.filter(shopper=shopper, used_at__isnull=True).update(used_at=now)
    code = f"{secrets.randbelow(10 ** 6):06d}"
    ShopperPasswordResetCode.objects.create(shopper=shopper, code_hash=_hash(shopper, code),
                                            expires_at=now + timedelta(minutes=CODE_MINUTES))
    try:
        send_mail(
            subject="Your password reset code",
            message=(f"Hi {shopper.name},\n\nYour password reset code is {code}\n\n"
                     f"It works for {CODE_MINUTES} minutes. If you did not ask for it, ignore this email: "
                     f"your password has not changed."),
            from_email=None,  # DEFAULT_FROM_EMAIL (Brevo sender)
            recipient_list=[shopper.email],
            fail_silently=False,
        )
    except Exception:
        logger.exception("Could not send the customer password reset email")


def reset_password(email, code, new_password):
    shopper = _find(email)
    entry = None
    if shopper:
        entry = (ShopperPasswordResetCode.objects
                 .filter(shopper=shopper, used_at__isnull=True, expires_at__gt=timezone.now())
                 .order_by("-created_at").first())
    bad = BusinessRuleError("The code is wrong or has expired. Ask for a new one.", "invalid_code")
    if entry is None or entry.attempts >= MAX_WRONG_TRIES:
        raise bad
    if not hmac.compare_digest(entry.code_hash, _hash(shopper, (code or "").strip())):
        entry.attempts += 1
        entry.save(update_fields=["attempts"])
        raise bad
    if len(new_password or "") < MIN_PASSWORD:
        raise ValidationError({"new_password": [f"Use at least {MIN_PASSWORD} characters."]})  # code still usable
    shopper.set_password(new_password)
    shopper.save(update_fields=["password"])
    ShopperToken.objects.filter(shopper=shopper).delete()  # sign out on every phone
    entry.used_at = timezone.now()
    entry.save(update_fields=["used_at"])
