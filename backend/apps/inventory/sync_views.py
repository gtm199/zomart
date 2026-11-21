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
from core.media import image_url, thumb_url

def picture(request, product):
    return thumb_url(product.image, request)

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
                "image": picture(request, p.master_product),       # small picture - kept for installed apps
                "image_thumb": image_url(p.master_product.image, "thumb", request),
                "image_medium": image_url(p.master_product.image, "medium", request),
                "unit": p.master_product.unit,
                "loose": p.master_product.is_loose,
                # GST shops only: lets the phone block unrated products and add tax-on-top prices offline
                **({"gst_rate": None if p.gst_rate is None else str(p.gst_rate),
                    "price_includes_gst": p.price_includes_gst} if request.shop.gst_enabled else {}),
            } for p in products],
            "gst": ({"enabled": True, "scheme": request.shop.gst_scheme, "state_code": request.shop.gst_state_code}
                    if request.shop.gst_enabled else {"enabled": False}),
            "customers": [{
                "id": c.id, "name": c.name, "phone": c.phone, "whatsapp_number": c.whatsapp_number,
                "balance": str(c.balance), "is_active": c.is_active,
                "credit_limit": None if c.credit_limit is None else str(c.credit_limit),
            } for c in customers],
        })