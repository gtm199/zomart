from datetime import timedelta

from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.models import MasterProduct
from apps.customers.models import Customer
from apps.shops.roles import Cap
from core.tenancy import ShopAccess

from .models import ShopProduct


class SyncView(APIView):
    """What the phone needs for offline billing. Pass ?since=<server_time from the last call> for changes only.
    Products are never deleted (they are switched off), so changes cover everything."""
    permission_classes = [IsAuthenticated, ShopAccess]
    required_caps = {"get": Cap.SELL}

    def get(self, request):
        raw = request.query_params.get("since")
        since = None
        if raw:
            since = parse_datetime(raw)
            if since is None:
                raise ValidationError({"since": "Use an ISO date and time."})
            since = since - timedelta(seconds=5)  # small overlap so nothing is missed
        server_time = timezone.now()  # taken before reading, so the next call cannot miss a change

        products = (ShopProduct.objects.filter(shop=request.shop)
                    .select_related("master_product").prefetch_related("master_product__barcodes"))
        customers = Customer.objects.filter(shop=request.shop)
        if not request.membership.has_cap(Cap.VIEW_CUSTOMERS):
            customers = customers.none()
        if since:
            products = products.filter(updated_at__gte=since)
            customers = customers.filter(updated_at__gte=since)

        return Response({
            "server_time": server_time.isoformat(),
            "full": since is None,
            "products": [{
                "id": p.id,
                "name": p.master_product.display_name,
                "barcodes": [b.code for b in p.master_product.barcodes.all()],
                "selling_price": str(p.selling_price),
                "stock_qty": str(p.stock_qty),
                "is_enabled": p.is_enabled and p.master_product.status == MasterProduct.Status.ACTIVE,
                "whole": p.master_product.unit == MasterProduct.Unit.PIECE,
                "unit": p.master_product.unit,
                "loose": p.master_product.is_loose,
            } for p in products],
            "customers": [{
                "id": c.id, "name": c.name, "phone": c.phone, "whatsapp_number": c.whatsapp_number,
                "balance": str(c.balance), "is_active": c.is_active,
                "credit_limit": None if c.credit_limit is None else str(c.credit_limit),
            } for c in customers],
        })