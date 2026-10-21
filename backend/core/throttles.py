from rest_framework.throttling import AnonRateThrottle


class LoginUsernameThrottle(AnonRateThrottle):
    """
    Limit login requests based on the submitted username or email.
    One shop's wrong guesses must not lock out other shops on the same mobile network.
    """

    scope = "login_user"  # must match the name in DEFAULT_THROTTLE_RATES in settings/base.py

    def get_cache_key(self, request, view):
        if request.method != "POST":
            return None

        data = request.data if isinstance(request.data, dict) else {}
        username = str(data.get("username", "")).strip().lower()

        if not username:
            return super().get_cache_key(request, view)  # no name sent: limit by visitor address instead

        return self.cache_format % {"scope": self.scope, "ident": username}