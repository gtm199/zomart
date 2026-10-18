from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.authtoken.models import Token
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.subscriptions.models import PaymentSettings, SubscriptionPlan

from django.utils import timezone
from rest_framework import generics, mixins, status, viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.tenancy import ShopAccess, ShopScopedMixin
from services import subscription_service

from .models import ShopMembership, ShopNotification
from .roles import Cap
from .serializers import MemberCreateSerializer, MemberSerializer, MemberUpdateSerializer, ShopSerializer


class ShopView(generics.RetrieveUpdateAPIView):
    permission_classes = [IsAuthenticated, ShopAccess]
    required_caps = {"get": Cap.VIEW_SHOP, "patch": Cap.MANAGE_SHOP}
    serializer_class = ShopSerializer
    http_method_names = ["get", "patch", "head", "options"]

    def get_object(self):
        return self.request.shop

class SubscriptionView(APIView):
    permission_classes = [IsAuthenticated, ShopAccess]
    required_caps = {"get": Cap.VIEW_SHOP}

    def get(self, request):
        shop = subscription_service.ensure_payment_identity(request.shop)
        pay = PaymentSettings.load()
        sub = subscription_service.current_subscription(shop)
        days = subscription_service.days_left(sub)
        plans = SubscriptionPlan.objects.filter(is_active=True, price_monthly__gt=0).order_by("price_monthly")
        return Response({
            "active": sub is not None,
            "plan": sub.plan.name if sub else None,
            "status": sub.status if sub else None,
            "expires_on": sub.expires_on if sub else None,
            "days_left": days,
            "grace_days": sub.grace_days if sub else 0,
            "in_grace_period": bool(sub and days < 0 and subscription_service.is_write_allowed(shop)),
            "write_allowed": subscription_service.is_write_allowed(shop),
            "reminder_days": pay.reminder_days,
            "limits": {"products": sub.plan.max_products if sub else None,
                       "employees": sub.plan.max_employees if sub else None},
            "payment": {
                "shop_code": shop.payment_code,
                "upi_id": pay.upi_id,
                "payee_name": pay.payee_name,
                "qr_url": request.build_absolute_uri(pay.qr_image.url) if pay.qr_image else "",
                "instructions": pay.instructions,
            },
            "plans": [{
                "id": p.id, "name": p.name, "price_monthly": str(p.price_monthly),
                "max_products": p.max_products, "max_employees": p.max_employees,
                "options": [{"months": n, "amount": str(subscription_service.amount_for(p, n, shop))} for n in (1, 3, 6, 12)],
            } for p in plans],
        })

class MemberViewSet(ShopScopedMixin, mixins.ListModelMixin, mixins.CreateModelMixin,
                    mixins.UpdateModelMixin, viewsets.GenericViewSet):
    queryset = ShopMembership.objects.select_related("user").order_by("id")
    required_caps = {"*": Cap.MANAGE_MEMBERS}
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_serializer_class(self):
        if self.action == "create":
            return MemberCreateSerializer
        if self.action in ("partial_update", "update"):
            return MemberUpdateSerializer
        return MemberSerializer

    def create(self, request, *args, **kwargs):
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        member = s.save()
        return Response(MemberSerializer(member).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        member = self.get_object()
        if member.role == ShopMembership.Role.OWNER:
            raise PermissionDenied("The owner membership cannot be changed.")
        s = self.get_serializer(member, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        s.save()
        return Response(MemberSerializer(member).data)

    @action(detail=True, methods=["post"], url_path="set-password")
    def set_password(self, request, pk=None):
        member = self.get_object()
        if member.role == ShopMembership.Role.OWNER:
            raise PermissionDenied("The owner's password cannot be changed here.")
        password = request.data.get("password", "")
        try:
            validate_password(password, user=member.user)
        except DjangoValidationError as exc:
            raise ValidationError({"password": list(exc.messages)})
        member.user.set_password(password)
        member.user.save(update_fields=["password"])
        Token.objects.filter(user=member.user).delete()  # signs them out everywhere
        return Response({"ok": True})

class NotificationView(APIView):
    permission_classes = [IsAuthenticated, ShopAccess]
    required_caps = {"get": Cap.VIEW_SHOP, "post": Cap.VIEW_SHOP}

    def get(self, request):
        qs = ShopNotification.objects.filter(shop=request.shop)
        return Response({
            "unread_count": qs.filter(read_at__isnull=True).count(),
            "results": [{"id": n.id, "title": n.title, "message": n.message, "created_at": n.created_at,
                         "read": n.read_at is not None} for n in qs[:50]],
        })

    def post(self, request):
        """Mark every notice as read."""
        n = ShopNotification.objects.filter(shop=request.shop, read_at__isnull=True).update(read_at=timezone.now())
        return Response({"marked_read": n})