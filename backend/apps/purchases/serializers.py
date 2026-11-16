from decimal import Decimal

from rest_framework import serializers

from apps.suppliers.models import SupplierPayment
from services.gstin import GstinError, validate_gstin

from .models import Purchase, PurchaseItem


class PurchaseItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = PurchaseItem
        fields = ["id", "shop_product", "product_name", "quantity", "unit_cost", "line_total", "returned_qty",
                  "gst_rate", "gst_amount"]


class SupplierPaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = SupplierPayment
        fields = ["id", "kind", "method", "amount", "reference", "created_at"]


class PurchaseSerializer(serializers.ModelSerializer):
    items = PurchaseItemSerializer(many=True, read_only=True)
    payments = SupplierPaymentSerializer(many=True, read_only=True)
    supplier_name = serializers.CharField(source="supplier.name", read_only=True)

    class Meta:
        model = Purchase
        fields = ["id", "supplier", "supplier_name", "invoice_number", "client_txn_id", "purchase_date", "status",
                  "total", "amount_paid", "amount_due", "notes", "created_at", "items", "payments",
                  "supplier_gstin", "gst_total"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        shop = self.context.get("shop")
        has_gst = instance.gst_total or instance.supplier_gstin or (shop is not None and shop.gst_enabled)
        if not has_gst:   # non-GST shops see purchases exactly as before
            data.pop("supplier_gstin", None)
            data.pop("gst_total", None)
            for item in data.get("items", []):
                item.pop("gst_rate", None)
                item.pop("gst_amount", None)
        return data


class PurchaseItemInputSerializer(serializers.Serializer):
    shop_product = serializers.IntegerField()
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3, min_value=Decimal("0.001"))
    unit_cost = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal("0"))
    expiry_date = serializers.DateField(required=False, allow_null=True, default=None)
    gst_rate = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=Decimal("0"), max_value=Decimal("100"),
                                        required=False, allow_null=True, default=None)
    gst_amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0"), required=False,
                                          allow_null=True, default=None)


class PurchasePaymentInputSerializer(serializers.Serializer):
    method = serializers.ChoiceField(choices=["cash", "upi"])
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))
    reference = serializers.CharField(max_length=60, required=False, allow_blank=True, default="")


class PurchaseCreateSerializer(serializers.Serializer):
    client_txn_id = serializers.UUIDField()
    supplier = serializers.IntegerField()
    invoice_number = serializers.CharField(max_length=40, required=False, allow_blank=True, default="")
    purchase_date = serializers.DateField(required=False, default=None)
    items = PurchaseItemInputSerializer(many=True, allow_empty=False)
    payments = PurchasePaymentInputSerializer(many=True, required=False, default=list)
    notes = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    supplier_gstin = serializers.CharField(max_length=20, required=False, allow_blank=True, default="")

    def validate_supplier_gstin(self, value):
        if not (value or "").strip():
            return ""
        try:
            return validate_gstin(value)   # format only; any state
        except GstinError as exc:
            raise serializers.ValidationError(str(exc))


class PurchaseReturnItemSerializer(serializers.Serializer):
    purchase_item = serializers.IntegerField()
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3, min_value=Decimal("0.001"))


class PurchaseReturnSerializer(serializers.Serializer):
    items = PurchaseReturnItemSerializer(many=True, allow_empty=False)
    refund_method = serializers.ChoiceField(choices=["cash", "upi"], default="cash")