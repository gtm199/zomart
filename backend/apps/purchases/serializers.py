from decimal import Decimal

from rest_framework import serializers

from apps.suppliers.models import SupplierPayment

from .models import Purchase, PurchaseItem


class PurchaseItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = PurchaseItem
        fields = ["id", "shop_product", "product_name", "quantity", "unit_cost", "line_total", "returned_qty"]


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
                  "total", "amount_paid", "amount_due", "notes", "created_at", "items", "payments"]


class PurchaseItemInputSerializer(serializers.Serializer):
    shop_product = serializers.IntegerField()
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3, min_value=Decimal("0.001"))
    unit_cost = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal("0"))


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


class PurchaseReturnItemSerializer(serializers.Serializer):
    purchase_item = serializers.IntegerField()
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3, min_value=Decimal("0.001"))


class PurchaseReturnSerializer(serializers.Serializer):
    items = PurchaseReturnItemSerializer(many=True, allow_empty=False)
    refund_method = serializers.ChoiceField(choices=["cash", "upi"], default="cash")