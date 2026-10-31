from decimal import Decimal

from django.db import transaction
from rest_framework import serializers

from apps.catalog.models import MasterProduct
from apps.catalog.serializers import MasterProductSerializer
from apps.shops.roles import Cap
from services import inventory_service, subscription_service

from .models import ShopProduct, StockMovement


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
        return data

class ShopProductCreateSerializer(serializers.Serializer):
    master_product = serializers.PrimaryKeyRelatedField(queryset=MasterProduct.objects.filter(status=MasterProduct.Status.ACTIVE))
    selling_price = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal("0"))
    purchase_cost = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal("0"), required=False, default=0)
    opening_stock = serializers.DecimalField(max_digits=12, decimal_places=3, min_value=Decimal("0"), required=False, default=0)
    low_stock_threshold = serializers.DecimalField(max_digits=12, decimal_places=3, min_value=Decimal("0"), required=False, default=0)
    is_enabled = serializers.BooleanField(required=False, default=True)
    expiry_date = serializers.DateField(required=False, allow_null=True, default=None)

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
        sp = ShopProduct.objects.create(shop=shop, **data)
        if opening > 0:
            inventory_service.apply_movement(shop_product_id=sp.pk, delta=opening,
                                             movement_type=StockMovement.Type.OPENING, user=user, note="Opening stock")
            sp.refresh_from_db()
        return sp


class ShopProductUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ShopProduct
        fields = ["selling_price", "purchase_cost", "low_stock_threshold", "is_enabled", "expiry_date", "online_visible"]
        extra_kwargs = {"selling_price": {"min_value": Decimal("0")}, "purchase_cost": {"min_value": Decimal("0")}}


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
