import re
from decimal import Decimal

from rest_framework import serializers

from .models import Customer, CustomerLedger


def normalize_phone(value):
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    if digits and len(digits) != 10:
        raise serializers.ValidationError("Enter a valid 10-digit mobile number.")
    return digits


class CustomerSerializer(serializers.ModelSerializer):
    credit_limit = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0"),
                                            required=False, allow_null=True)
    class Meta:
        model = Customer
        fields = ["id", "name", "phone", "whatsapp_number", "balance", "credit_limit", "notes", "is_active", "created_at"]
        read_only_fields = ["balance", "created_at"]

    def validate_phone(self, value):
        phone = normalize_phone(value)
        if phone:
            qs = Customer.objects.filter(shop=self.context["shop"], phone=phone)
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError("You already have a customer with this phone number.")
        return phone

    def validate_whatsapp_number(self, value):
        return normalize_phone(value)


class LedgerSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerLedger
        fields = ["id", "entry_type", "amount", "balance_after", "sale", "note", "created_at"]


class ReceivePaymentSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))
    method = serializers.ChoiceField(choices=["cash", "upi"])
    reference = serializers.CharField(max_length=60, required=False, allow_blank=True, default="")
    note = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
