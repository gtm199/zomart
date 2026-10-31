from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed

from .models import ShopperToken


class ShopperTokenAuthentication(BaseAuthentication):
    """Header: 'Authorization: Shopper <key>'. A shop's staff token never works here, and this never works on shop screens."""

    def authenticate(self, request):
        parts = get_authorization_header(request).split()
        if len(parts) != 2 or parts[0].lower() != b"shopper":
            return None
        try:
            token = ShopperToken.objects.select_related("shopper").get(key=parts[1].decode())
        except (ShopperToken.DoesNotExist, UnicodeError):
            raise AuthenticationFailed("Invalid token.")
        if not token.shopper.is_active:
            raise AuthenticationFailed("This account is switched off.")
        return token.shopper, token

    def authenticate_header(self, request):
        return "Shopper"