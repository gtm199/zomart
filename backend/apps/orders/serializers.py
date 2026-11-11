import re
from decimal import Decimal

from rest_framework import serializers

from apps.inventory.models import ShopProduct
from apps.shops.models import Shop

from apps.customers.models import Customer, CustomerLedger
from .models import Order, OrderEvent, OrderItem, Shopper, ShopperCredit, SavedAddress

from core.media import full_url, thumb_url

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
        fields = ["id", "name", "city", "address", "phone", "upi_id", "accepts_delivery", "accepts_pickup",
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
    image_full = serializers.SerializerMethodField()

    class Meta:
        model = ShopProduct
        fields = ["id", "name", "category", "category_name", "unit", "loose", "selling_price", "image", "image_full","in_stock"]

    def get_category_name(self, obj):
        c = obj.master_product.category
        return c.name if c else ""

    def get_image(self, obj):
        return thumb_url(obj.master_product.image, self.context.get("request"))

    def get_image_full(self, obj):
        return full_url(obj.master_product.image, self.context.get("request"))

    #def get_image(self, obj):
     #   image = obj.master_product.image
     #  request = self.context.get("request")
     #  return request.build_absolute_uri(image.url) if image and request else ""

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

class PositionFields(serializers.Serializer):
    """delivery_lat / delivery_lng always come from the saved address when there is one."""
    delivery_lat = serializers.SerializerMethodField()
    delivery_lng = serializers.SerializerMethodField()

    def get_delivery_lat(self, obj):
        p = obj.position()
        return None if p is None else p[0]

    def get_delivery_lng(self, obj):
        p = obj.position()
        return None if p is None else p[1]

class ShopperOrderSerializer(PositionFields, serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    events = OrderEventSerializer(many=True, read_only=True)
    shop_name = serializers.CharField(source="shop.name", read_only=True)
    shop_phone = serializers.CharField(source="shop.phone", read_only=True)

    class Meta:
        model = Order
        fields = ["id", "number", "shop", "shop_name", "shop_phone", "status", "fulfilment", "delivery_address", "delivery_lat", "delivery_lng", "note",
                  "payment_method", "subtotal", "delivery_fee", "total", "reason", "created_at", "items", "events"]


class VendorOrderSerializer(ShopperOrderSerializer):
    rider_name = serializers.SerializerMethodField()

    class Meta(ShopperOrderSerializer.Meta):
        fields = ShopperOrderSerializer.Meta.fields + ["customer_name", "customer_phone", "rider_name"]

    def get_rider_name(self, obj):
        return (obj.rider.first_name or obj.rider.username) if obj.rider_id else ""


class CustomerOrderSerializer(ShopperOrderSerializer):
    """What the customer sees. Only the customer gets the delivery PIN, and only while the order is out for delivery."""
    delivery_pin = serializers.SerializerMethodField()
    can_track = serializers.SerializerMethodField()

    class Meta(ShopperOrderSerializer.Meta):
        fields = ShopperOrderSerializer.Meta.fields + ["delivery_pin", "can_track"]

    def get_delivery_pin(self, obj):
        return obj.delivery_pin if obj.fulfilment == "delivery" and obj.status == "out_for_delivery" else None

    def get_can_track(self, obj):
        return obj.fulfilment == "delivery" and obj.position() is not None and obj.status in ("accepted", "packed", "out_for_delivery")

class PlaceItemSerializer(serializers.Serializer):
    shop_product = serializers.IntegerField()
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3, min_value=Decimal("0.001"))


class PlaceOrderSerializer(serializers.Serializer):
    shop = serializers.IntegerField()
    client_txn_id = serializers.UUIDField()
    fulfilment = serializers.ChoiceField(choices=["delivery", "pickup"])
    address = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")
    note = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    payment_method = serializers.ChoiceField(choices=["cash", "upi", "credit"], default="cash")
    delivery_lat = serializers.FloatField(required=False, allow_null=True, default=None)
    delivery_lng = serializers.FloatField(required=False, allow_null=True, default=None)
    address_id = serializers.IntegerField(required=False, allow_null=True, default=None)
    items = PlaceItemSerializer(many=True, allow_empty=False)

    def validate(self, attrs):
        if (attrs.get("delivery_lat") is None) != (attrs.get("delivery_lng") is None):
            raise serializers.ValidationError("Send both the latitude and the longitude of the delivery location.")
        return attrs


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
                  "min_order", "store_note", "upi_id", "latitude", "longitude", "delivery_radius_km", "store_code"]
        read_only_fields = ["store_code"]

    def validate(self, attrs):
        get = lambda k: attrs.get(k, getattr(self.instance, k))
        if get("store_enabled") and not (get("accepts_delivery") or get("accepts_pickup")):
            raise serializers.ValidationError("Allow delivery, pickup, or both.")
        lat, lng = get("latitude"), get("longitude")
        if (lat is None) != (lng is None):
            raise serializers.ValidationError("Set both the latitude and the longitude of the shop.")
        if lat is not None and not (-90 <= lat <= 90 and -180 <= lng <= 180):
            raise serializers.ValidationError("The shop location is not valid.")
        return attrs

class VendorCreditSerializer(serializers.ModelSerializer):
    """What the shop sees about a credit request."""
    shopper_name = serializers.CharField(source="shopper.name", read_only=True)
    shopper_phone = serializers.CharField(source="shopper.phone", read_only=True)
    customer = serializers.SerializerMethodField()
    same_phone_customer = serializers.SerializerMethodField()

    class Meta:
        model = ShopperCredit
        fields = ["id", "status", "requested_at", "shopper_name", "shopper_phone", "customer", "same_phone_customer"]

    def get_customer(self, obj):
        c = obj.customer
        return None if c is None else {"id": c.id, "name": c.name, "owed": str(c.balance),
                                       "limit": None if c.credit_limit is None else str(c.credit_limit)}

    def get_same_phone_customer(self, obj):
        """An existing customer of the shop with the same number. It may or may not be the same person."""
        if obj.customer_id:
            return None
        c = Customer.objects.filter(shop=obj.shop, phone=obj.shopper.phone).first()
        return None if c is None else {"id": c.id, "name": c.name, "owed": str(c.balance)}


class ApproveCreditSerializer(serializers.Serializer):
    limit = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))
    customer = serializers.IntegerField(required=False, allow_null=True, default=None)


class LedgerRowSerializer(serializers.ModelSerializer):
    """The customer sees amounts and dates, and the bill number of credit sales. Never the shop's private notes."""
    note = serializers.SerializerMethodField()

    class Meta:
        model = CustomerLedger
        fields = ["entry_type", "amount", "balance_after", "note", "created_at"]

    def get_note(self, obj):
        return obj.note if obj.entry_type == CustomerLedger.EntryType.CREDIT_SALE else ""

class ReadySerializer(serializers.Serializer):
    rider = serializers.IntegerField(required=False, allow_null=True, default=None)


# ---------------- riders ----------------
class RiderItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderItem
        fields = ["product_name", "unit", "quantity"]


class RiderOrderSerializer(PositionFields, serializers.ModelSerializer):
    """What a rider sees. No delivery PIN, no prices of single items, no customer account details."""
    items = RiderItemSerializer(many=True, read_only=True)
    shop_name = serializers.CharField(source="shop.name", read_only=True)
    shop_phone = serializers.CharField(source="shop.phone", read_only=True)
    shop_lat = serializers.SerializerMethodField()
    shop_lng = serializers.SerializerMethodField()
    on_credit = serializers.SerializerMethodField()
    collect_amount = serializers.SerializerMethodField()
    trip_started = serializers.SerializerMethodField()
    arrived = serializers.SerializerMethodField()
    pin_locked = serializers.SerializerMethodField()
    has_position = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = ["id", "number", "status", "customer_name", "customer_phone", "delivery_address", "has_position", "delivery_lat",
                  "delivery_lng", "note", "payment_method", "on_credit", "collect_amount", "total", "items", "shop_name",
                  "shop_phone", "shop_lat", "shop_lng", "trip_started", "arrived", "pin_locked", "updated_at"]

    def get_shop_lat(self, obj):
        return None if obj.shop.latitude is None else float(obj.shop.latitude)

    def get_shop_lng(self, obj):
        return None if obj.shop.longitude is None else float(obj.shop.longitude)

    def get_on_credit(self, obj):
        return obj.payment_method == "credit"

    def get_collect_amount(self, obj):
        """Cash to collect at the door. On credit, only the delivery fee."""
        return str(obj.delivery_fee if obj.payment_method == "credit" else obj.total)

    def get_trip_started(self, obj):
        t = getattr(obj, "track", None)
        return bool(t and t.started_at)

    def get_arrived(self, obj):
        t = getattr(obj, "track", None)
        return bool(t and t.arrived_at)

    def get_pin_locked(self, obj):
        return obj.pin_attempts >= 5

    def get_has_position(self, obj):
        return obj.position() is not None


class LocationSerializer(serializers.Serializer):
    lat = serializers.FloatField(min_value=-90, max_value=90)
    lng = serializers.FloatField(min_value=-180, max_value=180)
    heading = serializers.FloatField(required=False, allow_null=True, default=None)
    speed = serializers.FloatField(required=False, allow_null=True, default=None)
    accuracy = serializers.FloatField(required=False, allow_null=True, default=None)


class DeliverSerializer(serializers.Serializer):
    pin = serializers.CharField(max_length=8)
    payment_method = serializers.ChoiceField(choices=["cash", "upi"], default="cash")

# ---------------- saved addresses ----------------
class SavedAddressSerializer(serializers.ModelSerializer):
    lat = serializers.FloatField(required=False, allow_null=True, min_value=-90, max_value=90)
    lng = serializers.FloatField(required=False, allow_null=True, min_value=-180, max_value=180)

    class Meta:
        model = SavedAddress
        fields = ["id", "label", "address", "lat", "lng"]

    def validate(self, attrs):
        lat, lng = attrs.get("lat"), attrs.get("lng")
        if (lat is None) != (lng is None):
            raise serializers.ValidationError("Send both the latitude and the longitude.")
        return attrs

    def validate_address(self, value):
        if len(value.strip()) < 8:
            raise serializers.ValidationError("Write the full address (house, street, landmark).")
        return value.strip()