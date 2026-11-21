from core.throttles import LoginUsernameThrottle
from services import shopper_login_service


class ShopperLoginThrottle(LoginUsernameThrottle):
    """Limits sign-in tries per customer account (mobile number, username or email)."""

    def get_cache_key(self, request, view):
        data = request.data if isinstance(request.data, dict) else {}
        key = shopper_login_service.throttle_key(str(data.get("login") or data.get("phone") or ""))
        if not key:
            return None
        return self.cache_format % {"scope": self.scope, "ident": f"shopper:{key}"}
