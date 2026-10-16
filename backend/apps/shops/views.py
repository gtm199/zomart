from django.utils import timezone
from rest_framework import generics, mixins, status, viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.tenancy import ShopAccess, ShopScopedMixin
from services import subscription_service

from .models import ShopMembership
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
        shop = request.shop
        sub = subscription_service.current_subscription(shop)
        if sub is None:
            return Response({"active": False, "write_allowed": False})
        today = timezone.localdate()
        return Response({
            "plan": sub.plan.name, "status": sub.status,
            "expires_on": sub.expires_on, "grace_days": sub.grace_days,
            "in_grace_period": sub.expires_on < today,
            "write_allowed": subscription_service.is_write_allowed(shop),
            "limits": {"products": sub.plan.max_products, "employees": sub.plan.max_employees,
                       "whatsapp_monthly": sub.plan.whatsapp_monthly_limit},
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
