from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from apps.catalog.models import MasterProduct
from apps.catalog.serializers import MasterProductSerializer
from apps.shops.roles import Cap
from services import gst_service, inventory_service, subscription_service

from .models import ShopProduct, StockMovement


GST_FIELDS = ("gst_rate", "hsn_code", "price_includes_gst")


def _customer_price(shop, sp, master):
    """What the customer pays for one unit, and whether that is above the printed MRP (Legal Metrology: MRP includes
    all taxes; packaged goods may not be sold above it). A warning only - many products have no MRP on record."""
    if sp.gst_rate is None or shop.gst_scheme == "composition":
        per_unit = sp.selling_price
    else:
        per_unit = gst_service.compute_line(gross=sp.selling_price, rate=sp.gst_rate,
                                            price_includes_gst=sp.price_includes_gst).line_total
    above = master.mrp is not None and per_unit > master.mrp
    return {"customer_price": str(per_unit), "mrp": None if master.mrp is None else str(master.mrp),
            "above_mrp": above}


def _shop_of(serializer, obj=None):
    return serializer.context.get("shop") or (obj.shop if obj is not None else None)


class GstInputMixin:
    """Shared GST input rules for create/update. Only GST shops may send GST fields."""

    def validate_gst_rate(self, value):
        if value is None:
            return None
        try:
            return gst_service.validate_rate(value)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc))

    def validate_hsn_code(self, value):
        try:
            return gst_service.validate_hsn(value)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc))

    def check_gst_allowed(self, attrs):
        shop = self.context.get("shop")
        if any(f in attrs for f in GST_FIELDS) and not (shop and shop.gst_enabled):
            raise serializers.ValidationError({"gst_rate": "Switch GST billing on in Settings before setting GST details."})
        if "gst_rate" in attrs:
            attrs["gst_confirmed_at"] = timezone.now() if attrs["gst_rate"] is not None else None
        return attrs


class ShopProductSerializer(serializers.ModelSerializer):
    master_product = MasterProductSerializer(read_only=True)
    is_low_stock = serializers.SerializerMethodField()
    master_active = serializers.SerializerMethodField()
    days_to_expiry = serializers.IntegerField(read_only=True)
    expiry_status = serializers.CharField(read_only=True)

    class Meta:
        model = ShopProduct
        fields = ["id", "master_product", "selling_price", "purchase_cost", "stock_qty", "low_stock_threshold",
                  "is_enabled", "is_low_stock", "master_active", "expiry_date", "days_to_expiry",
                  "expiry_status", "online_visible", "updated_at"]

    def get_is_low_stock(self, obj):
        return obj.low_stock_threshold > 0 and obj.stock_qty <= obj.low_stock_threshold

    def get_master_active(self, obj):
        return obj.master_product.status == MasterProduct.Status.ACTIVE

    def to_representation(self, instance):
        data = super().to_representation(instance)
        membership = self.context.get("membership")
        if membership is None or not membership.has_cap(Cap.VIEW_COST):
            data.pop("purchase_cost", None)  # cashiers never see purchase costs
        shop = _shop_of(self, instance)
        if shop is not None and shop.gst_enabled:
            master = instance.master_product
            data.update({
                "gst_rate": None if instance.gst_rate is None else str(instance.gst_rate),
                "hsn_code": instance.hsn_code,
                "price_includes_gst": instance.price_includes_gst,
                "gst_confirmed": instance.gst_rate is not None,
                # catalogue suggestion only: the vendor must confirm it for their shop
                "suggested_gst_rate": None if master.tax_rate is None else str(master.tax_rate),
                "suggested_hsn_code": master.hsn_code,
                **_customer_price(shop, instance, master),
            })
        return data

class ShopProductCreateSerializer(GstInputMixin, serializers.Serializer):
    master_product = serializers.PrimaryKeyRelatedField(queryset=MasterProduct.objects.filter(status=MasterProduct.Status.ACTIVE))
    selling_price = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal("0"))
    purchase_cost = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal("0"), required=False, default=0)
    opening_stock = serializers.DecimalField(max_digits=12, decimal_places=3, min_value=Decimal("0"), required=False, default=0)
    low_stock_threshold = serializers.DecimalField(max_digits=12, decimal_places=3, min_value=Decimal("0"), required=False, default=0)
    is_enabled = serializers.BooleanField(required=False, default=True)
    expiry_date = serializers.DateField(required=False, allow_null=True, default=None)
    gst_rate = serializers.DecimalField(max_digits=5, decimal_places=2, required=False, allow_null=True)
    hsn_code = serializers.CharField(max_length=8, required=False, allow_blank=True)
    price_includes_gst = serializers.BooleanField(required=False)

    def validate(self, attrs):
        return self.check_gst_allowed(attrs)

    def validate_master_product(self, value):
        if ShopProduct.objects.filter(shop=self.context["shop"], master_product=value).exists():
            raise serializers.ValidationError("This product is already in your shop.")
        return value

    @transaction.atomic
    def create(self, data):
        shop = self.context["shop"]
        user = self.context["request"].user
        subscription_service.check_limit(shop, "products")
        opening = data.pop("opening_stock")
        # New listings follow the shop's price mode unless the vendor chose one for this product.
        data.setdefault("price_includes_gst", shop.gst_price_mode != "exclusive")
        sp = ShopProduct.objects.create(shop=shop, **data)
        if opening > 0:
            inventory_service.apply_movement(shop_product_id=sp.pk, delta=opening,
                                             movement_type=StockMovement.Type.OPENING, user=user, note="Opening stock")
            sp.refresh_from_db()
        return sp


class ShopProductUpdateSerializer(GstInputMixin, serializers.ModelSerializer):
    class Meta:
        model = ShopProduct
        fields = ["selling_price", "purchase_cost", "low_stock_threshold", "is_enabled", "expiry_date", "online_visible",
                  "gst_rate", "hsn_code", "price_includes_gst"]
        extra_kwargs = {"selling_price": {"min_value": Decimal("0")}, "purchase_cost": {"min_value": Decimal("0")}}

    def validate(self, attrs):
        return self.check_gst_allowed(attrs)


class StockAdjustmentSerializer(serializers.Serializer):
    T = StockMovement.Type
    quantity_delta = serializers.DecimalField(max_digits=12, decimal_places=3)
    movement_type = serializers.ChoiceField(choices=[T.ADJUSTMENT, T.DAMAGE, T.EXPIRED, T.PURCHASE])
    note = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    purchase_cost = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal("0"), required=False)

    def validate(self, attrs):
        delta, kind = attrs["quantity_delta"], attrs["movement_type"]
        if delta == 0:
            raise serializers.ValidationError("Quantity change cannot be zero.")
        if kind in ("damage", "expired") and delta > 0:
            raise serializers.ValidationError("Damaged or expired stock must be a negative change.")
        if kind == "purchase" and delta < 0:
            raise serializers.ValidationError("Stock received must be a positive change.")
        return attrs


class StockMovementSerializer(serializers.ModelSerializer):
    class Meta:
        model = StockMovement
        fields = ["id", "movement_type", "quantity_delta", "balance_after", "reference_type", "reference_id", "note", "created_at"]
