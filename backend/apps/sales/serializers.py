from decimal import Decimal

from rest_framework import serializers

from .models import Payment, Sale, SaleItem


class SaleItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = SaleItem
        fields = ["id", "shop_product", "product_name", "unit", "barcode", "quantity", "unit_price", "discount",
                  "tax_rate", "tax_amount", "line_total", "returned_qty"]

class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = ["id", "kind", "method", "amount", "reference", "created_at"]


class SaleSerializer(serializers.ModelSerializer):
    items = SaleItemSerializer(many=True, read_only=True)
    payments = PaymentSerializer(many=True, read_only=True)
    customer_name = serializers.CharField(source="customer.name", read_only=True, default="")

    class Meta:
        model = Sale
        fields = ["id", "invoice_number", "client_txn_id", "customer", "customer_name", "status", "subtotal",
                  "discount_total", "tax_total", "total", "amount_paid", "amount_due", "notes", "created_at",
                  "is_offline", "needs_review", "review_note", "items", "payments"]


class CheckoutItemSerializer(serializers.Serializer):
    shop_product = serializers.IntegerField()
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3, min_value=Decimal("0.001"))
    discount = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal("0"), required=False, default=0)
    unit_price = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal("0"), required=False, allow_null=True, default=None)


class CheckoutPaymentSerializer(serializers.Serializer):
    method = serializers.ChoiceField(choices=["cash", "upi"])
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))
    reference = serializers.CharField(max_length=60, required=False, allow_blank=True, default="")


class CheckoutSerializer(serializers.Serializer):
    client_txn_id = serializers.UUIDField()
    customer = serializers.IntegerField(required=False, allow_null=True, default=None)
    items = CheckoutItemSerializer(many=True, allow_empty=False)
    payments = CheckoutPaymentSerializer(many=True, required=False, default=list)
    notes = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    offline = serializers.BooleanField(required=False, default=False)
    client_created_at = serializers.DateTimeField(required=False, allow_null=True, default=None)


class ReturnItemSerializer(serializers.Serializer):
    sale_item = serializers.IntegerField()
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3, min_value=Decimal("0.001"))


class ReturnSerializer(serializers.Serializer):
    items = ReturnItemSerializer(many=True, allow_empty=False)
    refund_method = serializers.ChoiceField(choices=["cash", "upi"], default="cash")
