from django.db.models import Q
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.shops.roles import Cap
from core.tenancy import ShopScopedMixin
from services import supplier_service

from .models import Supplier
from .serializers import PaySupplierSerializer, SupplierLedgerSerializer, SupplierSerializer


class SupplierViewSet(ShopScopedMixin, mixins.CreateModelMixin, mixins.ListModelMixin,
                      mixins.RetrieveModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    queryset = Supplier.objects.all()
    serializer_class = SupplierSerializer
    http_method_names = ["get", "post", "patch", "head", "options"]
    required_caps = {
        "list": Cap.VIEW_PURCHASES, "retrieve": Cap.VIEW_PURCHASES, "ledger": Cap.VIEW_PURCHASES,
        "create": Cap.MANAGE_PURCHASES, "partial_update": Cap.MANAGE_PURCHASES, "pay": Cap.MANAGE_PURCHASES,
    }

    def get_queryset(self):
        qs = super().get_queryset()
        term = (self.request.query_params.get("search") or "").strip()
        if term:
            qs = qs.filter(Q(name__icontains=term) | Q(phone__contains=term))
        if self.request.query_params.get("owing") == "true":
            qs = qs.filter(balance__gt=0)
        return qs

    def perform_create(self, serializer):
        serializer.save(shop=self.request.shop)

    @action(detail=True)
    def ledger(self, request, pk=None):
        supplier = self.get_object()
        return Response(SupplierLedgerSerializer(supplier.ledger.all()[:200], many=True).data)

    @action(detail=True, methods=["post"])
    def pay(self, request, pk=None):
        supplier = self.get_object()
        s = PaySupplierSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        updated = supplier_service.pay_supplier(supplier_id=supplier.pk, user=request.user, **s.validated_data)
        return Response(SupplierSerializer(updated, context=self.get_serializer_context()).data)