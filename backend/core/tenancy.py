"""Tenant resolution. Every vendor-owned endpoint goes through ShopAccess + ShopScopedMixin."""
from rest_framework.permissions import SAFE_METHODS, BasePermission, IsAuthenticated
from rest_framework.exceptions import PermissionDenied

from apps.shops.models import ShopMembership
from services import subscription_service


def resolve_membership(user, raw_shop_id):
    """Return the user's active membership for the shop id, or None. Never trusts the id alone."""
    try:
        shop_id = int(raw_shop_id)
    except (TypeError, ValueError):
        return None
    return (
        ShopMembership.objects.select_related("shop")
        .filter(user=user, shop_id=shop_id, is_active=True, shop__is_active=True)
        .first()
    )


def required_cap(view, request):
    caps = getattr(view, "required_caps", {})
    action = getattr(view, "action", None)
    method = request.method.lower()
    return caps.get(action) or caps.get(method) or caps.get("*")


class ShopAccess(BasePermission):
    """Resolves X-Shop-ID to a membership, checks the role capability and subscription."""

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        raw = request.headers.get("X-Shop-ID")
        if not raw:
            raise PermissionDenied("X-Shop-ID header is required.")
        membership = resolve_membership(request.user, raw)
        if membership is None:
            raise PermissionDenied("You do not have access to this shop.")
        if not membership.shop.is_approved:
            raise PermissionDenied("Your shop is waiting for approval by the platform team.")
        cap = required_cap(view, request)
        if cap is None or not membership.has_cap(cap):
            raise PermissionDenied("Your role does not allow this action.")
        if request.method not in SAFE_METHODS and not subscription_service.is_write_allowed(membership.shop):
            raise PermissionDenied("Subscription expired. Renew to continue making changes.")
        request.shop = membership.shop
        request.membership = membership
        return True


class ShopScopedMixin:
    permission_classes = [IsAuthenticated, ShopAccess]

    def get_queryset(self):
        qs = super().get_queryset()
        if getattr(self, "swagger_fake_view", False):
            return qs.none()
        return qs.filter(shop=self.request.shop)

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        request = ctx.get("request")
        ctx["shop"] = getattr(request, "shop", None)
        ctx["membership"] = getattr(request, "membership", None)
        return ctx
