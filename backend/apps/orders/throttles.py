from core.throttles import LoginUsernameThrottle


class ShopperLoginThrottle(LoginUsernameThrottle):
    """Limits sign-in tries per phone number."""

    def get_cache_key(self, request, view):
        data = request.data if isinstance(request.data, dict) else {}
        phone = "".join(c for c in str(data.get("phone", "")) if c.isdigit())[-10:]
        if not phone:
            return None
        return self.cache_format % {"scope": self.scope, "ident": f"shopper:{phone}"}