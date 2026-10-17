from datetime import date

from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.shops.roles import Cap
from core.tenancy import ShopAccess, ShopScopedMixin
from services import billing_service, receipt_service, report_service

from .models import Sale
from .serializers import CheckoutSerializer, ReturnSerializer, SaleSerializer


class SaleViewSet(ShopScopedMixin, mixins.CreateModelMixin, mixins.ListModelMixin,
                  mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    queryset = Sale.objects.select_related("customer", "shop").prefetch_related("items", "payments")
    serializer_class = SaleSerializer
    required_caps = {"list": Cap.VIEW_SALES, "retrieve": Cap.VIEW_SALES, "receipt": Cap.VIEW_SALES,
                     "create": Cap.SELL, "return_items": Cap.REFUND}

    def get_queryset(self):
        qs = super().get_queryset()
        p = self.request.query_params
        if p.get("customer", "").isdigit():
            qs = qs.filter(customer_id=p["customer"])
        day = p.get("date")
        if day:
            try:
                qs = qs.filter(created_at__date=date.fromisoformat(day))
            except ValueError:
                raise ValidationError({"date": "Use YYYY-MM-DD."})
        return qs

    def create(self, request, *args, **kwargs):
        s = CheckoutSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        sale, created = billing_service.create_sale(
            shop=request.shop, user=request.user, client_txn_id=d["client_txn_id"], items=d["items"],
            payments=d["payments"], customer_id=d["customer"], notes=d["notes"])
        sale = self.get_queryset().get(pk=sale.pk)
        # 201 for a new sale, 200 when this exact client_txn_id was already processed (safe retry)
        return Response(SaleSerializer(sale).data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="return")
    def return_items(self, request, pk=None):
        sale = self.get_object()
        s = ReturnSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        billing_service.return_items(shop=request.shop, user=request.user, sale_id=sale.pk, **s.validated_data)
        return Response(SaleSerializer(self.get_queryset().get(pk=sale.pk)).data)

    @action(detail=True)
    def receipt(self, request, pk=None):
        sale = self.get_object()
        text = receipt_service.build_receipt_text(sale)
        phone = request.query_params.get("phone")
        return Response({"text": text, "whatsapp_url": receipt_service.whatsapp_url(sale, text, phone)})


class DailySummaryView(APIView):
    permission_classes = [IsAuthenticated, ShopAccess]
    required_caps = {"get": Cap.VIEW_REPORTS}

    def get(self, request):
        raw = request.query_params.get("date")
        try:
            day = date.fromisoformat(raw) if raw else timezone.localdate()
        except ValueError:
            raise ValidationError({"date": "Use YYYY-MM-DD."})
        return Response(report_service.daily_summary(request.shop, day))
