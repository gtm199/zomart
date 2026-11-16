from decimal import Decimal

from rest_framework import serializers

from services import gst_service
from services.gstin import GstinError, validate_gstin

from .models import CreditNote, CreditNoteItem, Payment, Sale, SaleItem

GST_ITEM_FIELDS = ["hsn_code", "price_includes_gst", "taxable_value", "cgst", "sgst", "igst"]
GST_SALE_FIELDS = ["taxable_total", "cgst_total", "sgst_total", "igst_total", "round_off", "seller_gstin",
                   "seller_legal_name", "seller_trade_name", "seller_address", "seller_state_code", "place_of_supply",
                   "customer_gstin", "customer_gst_name"]


class SaleItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = SaleItem
        fields = ["id", "shop_product", "product_name", "unit", "barcode", "quantity", "unit_price", "discount",
                  "tax_rate", "tax_amount", "line_total", "returned_qty"] + GST_ITEM_FIELDS

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if not instance.sale.is_gst_document:
            for f in GST_ITEM_FIELDS:   # plain bills look exactly as before
                data.pop(f, None)
        return data


class CreditNoteItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = CreditNoteItem
        fields = ["product_name", "hsn_code", "quantity", "gst_rate", "taxable_value", "cgst", "sgst", "igst",
                  "line_total"]


class CreditNoteSerializer(serializers.ModelSerializer):
    items = CreditNoteItemSerializer(many=True, read_only=True)

    class Meta:
        model = CreditNote
        fields = ["id", "number", "original_invoice_number", "original_document_type", "taxable_total", "cgst_total",
                  "sgst_total", "igst_total", "total", "seller_gstin", "seller_legal_name", "created_at", "items"]

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
                  "is_offline", "needs_review", "review_note", "items", "payments", "document_type"] + GST_SALE_FIELDS

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if not instance.is_gst_document:
            for f in GST_SALE_FIELDS:
                data.pop(f, None)
            return data
        items = list(instance.items.all())
        data["gst_summary"] = [{k: str(v) for k, v in row.items()} for row in gst_service.summarize_sale_items(items)]
        data["amount_in_words"] = gst_service.amount_in_words(instance.total)
        if instance.document_type == Sale.DocumentType.BILL_OF_SUPPLY:
            data["bill_of_supply_note"] = gst_service.BILL_OF_SUPPLY_NOTE
        data["credit_notes"] = CreditNoteSerializer(instance.credit_notes.all(), many=True).data
        return data


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
    # Optional, for business customers of GST shops. Format check only (cannot confirm registration).
    customer_gstin = serializers.CharField(max_length=20, required=False, allow_blank=True, default="")
    customer_gst_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")

    def validate_customer_gstin(self, value):
        if not (value or "").strip():
            return ""
        try:
            return validate_gstin(value)
        except GstinError as exc:
            raise serializers.ValidationError(str(exc))


class ReturnItemSerializer(serializers.Serializer):
    sale_item = serializers.IntegerField()
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3, min_value=Decimal("0.001"))


class ReturnSerializer(serializers.Serializer):
    items = ReturnItemSerializer(many=True, allow_empty=False)
    refund_method = serializers.ChoiceField(choices=["cash", "upi"], default="cash")
