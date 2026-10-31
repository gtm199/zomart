import re
from decimal import Decimal

from rest_framework import serializers

from apps.inventory.models import ShopProduct
from apps.shops.models import Shop

from .models import Order, OrderEvent, OrderItem, Shopper


def clean_phone(value):
    digits = re.sub(r"\D", "", value or "")
    return digits[-10:] if len(digits) >= 10 else digits


class RegisterSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=150)
    phone = serializers.CharField(max_length=20)
    password = serializers.CharField(write_only=True, min_length=6)

    def validate_phone(self, value):
        phone = clean_phone(value)
        if not re.fullmatch(r"[6-9]\d{9}", phone):
            raise serializers.ValidationError("Enter a valid 10-digit mobile number.")
        if Shopper.objects.filter(phone=phone).exists():
            raise serializers.ValidationError("This mobile number already has an account. Sign in instead.")
        return phone


class LoginSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=20)
    password = serializers.CharField(write_only=True)


class PublicShopSerializer(serializers.ModelSerializer):
    """Only what a customer may see about a shop."""

    class Meta:
        model = Shop
        fields = ["id", "name", "city", "address", "phone", "accepts_delivery", "accepts_pickup",
                  "delivery_fee", "free_delivery_above", "min_order", "store_note"]


class StoreProductSerializer(serializers.ModelSerializer):
    """No purchase cost and no exact stock: only whether it is in stock."""
    name = serializers.CharField(source="master_product.display_name")
    category = serializers.IntegerField(source="master_product.category_id", allow_null=True)
    category_name = serializers.SerializerMethodField()
    unit = serializers.CharField(source="master_product.unit")
    loose = serializers.BooleanField(source="master_product.is_loose")
    image = serializers.SerializerMethodField()
    in_stock = serializers.SerializerMethodField()

    class Meta:
        model = ShopProduct
        fields = ["id", "name", "category", "category_name", "unit", "loose", "selling_price", "image", "in_stock"]

    def get_category_name(self, obj):
        c = obj.master_product.category
        return c.name if c else ""

    def get_image(self, obj):
        image = obj.master_product.image
        request = self.context.get("request")
        return request.build_absolute_uri(image.url) if image and request else ""

    def get_in_stock(self, obj):
        return obj.stock_qty > 0 or obj.shop.allow_negative_stock


class OrderItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderItem
        fields = ["id", "product_name", "unit", "ordered_quantity", "quantity", "unit_price", "line_total"]


class OrderEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderEvent
        fields = ["status", "note", "created_at"]


class ShopperOrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    events = OrderEventSerializer(many=True, read_only=True)
    shop_name = serializers.CharField(source="shop.name", read_only=True)
    shop_phone = serializers.CharField(source="shop.phone", read_only=True)

    class Meta:
        model = Order
        fields = ["id", "number", "shop", "shop_name", "shop_phone", "status", "fulfilment", "delivery_address", "note",
                  "payment_method", "subtotal", "delivery_fee", "total", "reason", "created_at", "items", "events"]


class VendorOrderSerializer(ShopperOrderSerializer):
    class Meta(ShopperOrderSerializer.Meta):
        fields = ShopperOrderSerializer.Meta.fields + ["customer_name", "customer_phone"]


class PlaceItemSerializer(serializers.Serializer):
    shop_product = serializers.IntegerField()
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3, min_value=Decimal("0.001"))


class PlaceOrderSerializer(serializers.Serializer):
    shop = serializers.IntegerField()
    client_txn_id = serializers.UUIDField()
    fulfilment = serializers.ChoiceField(choices=["delivery", "pickup"])
    address = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")
    note = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    payment_method = serializers.ChoiceField(choices=["cash", "upi"], default="cash")
    items = PlaceItemSerializer(many=True, allow_empty=False)


class AdjustItemSerializer(serializers.Serializer):
    item = serializers.IntegerField()
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3, min_value=Decimal("0"))


class AcceptSerializer(serializers.Serializer):
    items = AdjustItemSerializer(many=True, required=False, default=list)


class ReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class CompleteSerializer(serializers.Serializer):
    payment_method = serializers.ChoiceField(choices=["cash", "upi"], default="cash")


class StoreSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = Shop
        fields = ["store_enabled", "accepts_delivery", "accepts_pickup", "delivery_fee", "free_delivery_above",
                  "min_order", "store_note", "store_code"]
        read_only_fields = ["store_code"]

    def validate(self, attrs):
        get = lambda k: attrs.get(k, getattr(self.instance, k))
        if get("store_enabled") and not (get("accepts_delivery") or get("accepts_pickup")):
            raise serializers.ValidationError("Allow delivery, pickup, or both.")
        return attrs