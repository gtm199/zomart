from datetime import date

from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.shops.roles import Cap
from core.tenancy import ShopAccess, ShopScopedMixin
from services import purchase_service, valuation_service

from .models import Purchase
from .serializers import PurchaseCreateSerializer, PurchaseReturnSerializer, PurchaseSerializer


class PurchaseViewSet(ShopScopedMixin, mixins.CreateModelMixin, mixins.ListModelMixin,
                      mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    queryset = Purchase.objects.select_related("supplier").prefetch_related("items", "payments")
    serializer_class = PurchaseSerializer
    required_caps = {"list": Cap.VIEW_PURCHASES, "retrieve": Cap.VIEW_PURCHASES,
                     "create": Cap.MANAGE_PURCHASES, "return_items": Cap.MANAGE_PURCHASES}

    def get_queryset(self):
        qs = super().get_queryset()
        p = self.request.query_params
        if p.get("supplier", "").isdigit():
            qs = qs.filter(supplier_id=p["supplier"])
        if p.get("date"):
            try:
                qs = qs.filter(purchase_date=date.fromisoformat(p["date"]))
            except ValueError:
                raise ValidationError({"date": "Use YYYY-MM-DD."})
        return qs

    def create(self, request, *args, **kwargs):
        s = PurchaseCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        purchase, created = purchase_service.create_purchase(
            shop=request.shop, user=request.user, client_txn_id=d["client_txn_id"], supplier_id=d["supplier"],
            items=d["items"], payments=d["payments"], invoice_number=d["invoice_number"],
            purchase_date=d["purchase_date"], notes=d["notes"])
        purchase = self.get_queryset().get(pk=purchase.pk)
        return Response(PurchaseSerializer(purchase).data,
                        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="return")
    def return_items(self, request, pk=None):
        purchase = self.get_object()
        s = PurchaseReturnSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        purchase_service.return_purchase(shop=request.shop, user=request.user, purchase_id=purchase.pk,
                                         **s.validated_data)
        return Response(PurchaseSerializer(self.get_queryset().get(pk=purchase.pk)).data)


class StockValuationView(APIView):
    permission_classes = [IsAuthenticated, ShopAccess]
    required_caps = {"get": Cap.VIEW_REPORTS}

    def get(self, request):
        return Response(valuation_service.stock_valuation(request.shop))