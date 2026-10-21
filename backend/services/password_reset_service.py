"""Password reset by a 6-digit code sent to the person's email. No link, so it works inside the app."""
import hashlib
import hmac
import logging
import secrets
from datetime import timedelta
from rest_framework.authtoken.models import Token

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.mail import send_mail
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.accounts.models import PasswordResetCode, User
from services.exceptions import BusinessRuleError

logger = logging.getLogger(__name__)

CODE_MINUTES = 15
MAX_WRONG_TRIES = 5
MAX_CODES_PER_HOUR = 3


def _hash(user, code):
    return hmac.new(settings.SECRET_KEY.encode(), f"{user.pk}:{code}".encode(), hashlib.sha256).hexdigest()


def request_code(email):
    """Sends a code if the email belongs to an account. Says nothing either way, so nobody can test which emails exist."""
    user = User.objects.filter(email__iexact=(email or "").strip(), is_active=True).exclude(email="").first()
    if user is None:
        return
    now = timezone.now()
    if PasswordResetCode.objects.filter(user=user, created_at__gte=now - timedelta(hours=1)).count() >= MAX_CODES_PER_HOUR:
        return
    PasswordResetCode.objects.filter(user=user, used_at__isnull=True).update(used_at=now)  # older codes stop working
    code = f"{secrets.randbelow(10 ** 6):06d}"
    PasswordResetCode.objects.create(user=user, code_hash=_hash(user, code), expires_at=now + timedelta(minutes=CODE_MINUTES))
    try:
        send_mail(
            subject="Your password reset code",
            message=(f"Your password reset code is {code}\n\n"
                     f"It works for {CODE_MINUTES} minutes. If you did not ask for it, ignore this email: "
                     f"your password has not changed."),
            from_email=None,  # DEFAULT_FROM_EMAIL
            recipient_list=[user.email],
            fail_silently=False,
        )
    except Exception:
        logger.exception("Could not send the password reset email")  # the person sees the same message either way


def reset_password(email, code, new_password):
    user = User.objects.filter(email__iexact=(email or "").strip(), is_active=True).exclude(email="").first()
    entry = None
    if user:
        entry = (PasswordResetCode.objects.filter(user=user, used_at__isnull=True, expires_at__gt=timezone.now())
                 .order_by("-created_at").first())
    bad = BusinessRuleError("The code is wrong or has expired. Ask for a new one.", "invalid_code")
    if entry is None or entry.attempts >= MAX_WRONG_TRIES:
        raise bad
    if not hmac.compare_digest(entry.code_hash, _hash(user, (code or "").strip())):
        entry.attempts += 1
        entry.save(update_fields=["attempts"])
        raise bad
    try:
        validate_password(new_password, user=user)
    except DjangoValidationError as exc:
        raise ValidationError({"new_password": list(exc.messages)})  # the code is still usable
    user.set_password(new_password)  # the signal signs every old phone out
    user.must_change_password = False
    user.save()
    Token.objects.filter(user=user).delete()
    entry.used_at = timezone.now()
    entry.save(update_fields=["used_at"])