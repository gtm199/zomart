from django.db.models import F, Q
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.catalog.models import MasterProduct
from apps.shops.roles import Cap
from core.tenancy import ShopScopedMixin
from services import barcode_service, inventory_service

from datetime import timedelta
from django.utils import timezone
from .models import DEFAULT_LOW_STOCK_LEVEL, EXPIRY_ALERT_DAYS, ShopProduct

from .serializers import (ShopProductCreateSerializer, ShopProductSerializer, ShopProductUpdateSerializer,
                          StockAdjustmentSerializer, StockMovementSerializer)


class ShopProductViewSet(ShopScopedMixin, mixins.CreateModelMixin, mixins.ListModelMixin,
                         mixins.RetrieveModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    queryset = ShopProduct.objects.select_related("master_product__brand", "master_product__category") \
        .prefetch_related("master_product__barcodes").order_by("master_product__name")
    http_method_names = ["get", "post", "patch", "head", "options"]
    required_caps = {
        "list": Cap.VIEW_PRODUCTS, "retrieve": Cap.VIEW_PRODUCTS, "by_barcode": Cap.VIEW_PRODUCTS,
        "movements": Cap.VIEW_PRODUCTS, "create": Cap.MANAGE_PRODUCTS,
        "partial_update": Cap.MANAGE_PRODUCTS, "adjust_stock": Cap.MANAGE_PRODUCTS, 
        "expiry_alerts": Cap.VIEW_PRODUCTS,
    }

    def get_serializer_class(self):
        return {"create": ShopProductCreateSerializer, "partial_update": ShopProductUpdateSerializer,
                "adjust_stock": StockAdjustmentSerializer}.get(self.action, ShopProductSerializer)

    def _out(self, sp):
        return ShopProductSerializer(sp, context=self.get_serializer_context()).data

    def get_queryset(self):
        qs = super().get_queryset()
        p = self.request.query_params
        if p.get("search"):
            t = p["search"].strip()
            qs = qs.filter(Q(master_product__name__icontains=t) | Q(master_product__brand__name__icontains=t) |
                           Q(master_product__search_keywords__icontains=t) | Q(master_product__barcodes__code=t)).distinct()
        
        if p.get("low_stock") == "true":
            qs = qs.filter(
                Q(low_stock_threshold__gt=0, stock_qty__lte=F("low_stock_threshold"))
                | Q(low_stock_threshold=0, stock_qty__lte=DEFAULT_LOW_STOCK_LEVEL)
            )

        if p.get("enabled") in ("true", "false"):
            qs = qs.filter(is_enabled=(p["enabled"] == "true"))

        if p.get("expiring") == "true":
            limit = timezone.localdate() + timedelta(days=EXPIRY_ALERT_DAYS)
            qs = qs.filter(stock_qty__gt=0, expiry_date__isnull=False, expiry_date__lte=limit).order_by("expiry_date")
        
        return qs

    def create(self, request, *args, **kwargs):
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        return Response(self._out(s.save()), status=status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        sp = self.get_object()
        s = self.get_serializer(sp, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        s.save()
        return Response(self._out(sp))

    @action(detail=False, url_path=r"by-barcode/(?P<code>[^/.]+)")
    def by_barcode(self, request, code):
        """Scan workflow: returns the master product and this shop's listing (or null)."""
        candidates = barcode_service.lookup_candidates(code)
        listing = self.get_queryset().filter(master_product__barcodes__code__in=candidates).first()
        if listing:
            return Response({"master_product": None, "shop_product": self._out(listing)})
        master = barcode_service.find_master_product(code)
        if master is None or master.status != MasterProduct.Status.ACTIVE:
            return Response({"detail": "Unknown barcode. You can suggest this product to the catalogue."},
                            status=status.HTTP_404_NOT_FOUND)
        from apps.catalog.serializers import MasterProductSerializer
        return Response({"master_product": MasterProductSerializer(master, context=self.get_serializer_context()).data,
                         "shop_product": None})

    @action(detail=True, methods=["post"], url_path="adjust-stock")
    def adjust_stock(self, request, pk=None):
        sp = self.get_object()
        s = StockAdjustmentSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        inventory_service.apply_movement(
            shop_product_id=sp.pk, delta=d["quantity_delta"], movement_type=d["movement_type"],
            user=request.user, note=d["note"], allow_negative=False)
        if d["movement_type"] == "purchase" and "purchase_cost" in d:
            sp.purchase_cost = d["purchase_cost"]
            sp.save(update_fields=["purchase_cost", "updated_at"])
        sp.refresh_from_db()
        return Response(self._out(sp))

    @action(detail=True)
    def movements(self, request, pk=None):
        sp = self.get_object()
        return Response(StockMovementSerializer(sp.movements.all()[:200], many=True).data)

    
    @action(detail=False, url_path="expiry-alerts")
    def expiry_alerts(self, request):
        today = timezone.localdate()
        base = self.get_queryset().filter(stock_qty__gt=0, expiry_date__isnull=False).order_by("expiry_date")
        expired = base.filter(expiry_date__lt=today)
        soon = base.filter(expiry_date__gte=today, expiry_date__lte=today + timedelta(days=EXPIRY_ALERT_DAYS))
        ctx = self.get_serializer_context()
        return Response({
            "alert_days": EXPIRY_ALERT_DAYS,
            "expired_count": expired.count(),
            "expiring_soon_count": soon.count(),
            "expired": ShopProductSerializer(expired[:50], many=True, context=ctx).data,
            "expiring_soon": ShopProductSerializer(soon[:50], many=True, context=ctx).data,
        })