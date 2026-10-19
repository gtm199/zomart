from django.db.models import Q
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.shops.roles import Cap
from core.tenancy import ShopScopedMixin
from services import customer_service

from .models import Customer
from .serializers import CustomerSerializer, LedgerSerializer, ReceivePaymentSerializer
from rest_framework.exceptions import PermissionDenied


class CustomerViewSet(ShopScopedMixin, mixins.CreateModelMixin, mixins.ListModelMixin,
                      mixins.RetrieveModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    queryset = Customer.objects.all()
    serializer_class = CustomerSerializer
    http_method_names = ["get", "post", "patch", "head", "options"]
    required_caps = {
        "list": Cap.VIEW_CUSTOMERS, "retrieve": Cap.VIEW_CUSTOMERS, "ledger": Cap.VIEW_CUSTOMERS,
        "create": Cap.MANAGE_CUSTOMERS, "partial_update": Cap.MANAGE_CUSTOMERS,
        "receive_payment": Cap.MANAGE_CUSTOMERS,
    }

    def get_queryset(self):
        qs = super().get_queryset()
        term = (self.request.query_params.get("search") or "").strip()
        if term:
            qs = qs.filter(Q(name__icontains=term) | Q(phone__contains=term))
        if self.request.query_params.get("owing") == "true":
            qs = qs.filter(balance__gt=0)
        return qs

    def _only_trusted_may_set_limit(self, request):
        if "credit_limit" in request.data and request.membership.role not in ("owner", "manager"):
            raise PermissionDenied("Only the owner or a manager can set credit limits.")

    def create(self, request, *args, **kwargs):
        self._only_trusted_may_set_limit(request)
        return super().create(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        self._only_trusted_may_set_limit(request)
        return super().partial_update(request, *args, **kwargs)
    
    def perform_create(self, serializer):
        serializer.save(shop=self.request.shop)

    @action(detail=True)
    def ledger(self, request, pk=None):
        customer = self.get_object()
        return Response(LedgerSerializer(customer.ledger.all()[:200], many=True).data)

    @action(detail=True, methods=["post"], url_path="receive-payment")
    def receive_payment(self, request, pk=None):
        customer = self.get_object()
        s = ReceivePaymentSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        updated = customer_service.receive_payment(customer_id=customer.pk, user=request.user, **s.validated_data)
        return Response(CustomerSerializer(updated, context=self.get_serializer_context()).data, status=status.HTTP_200_OK)
