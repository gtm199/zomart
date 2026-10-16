from decimal import Decimal

from rest_framework import serializers

from apps.customers.serializers import normalize_phone

from .models import Supplier, SupplierLedger


class SupplierSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        fields = ["id", "name", "phone", "address", "gstin", "notes", "balance", "is_active", "created_at"]
        read_only_fields = ["balance", "created_at"]

    def validate_name(self, value):
        qs = Supplier.objects.filter(shop=self.context["shop"], name__iexact=value.strip())
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("You already have a supplier with this name.")
        return value.strip()

    def validate_phone(self, value):
        return normalize_phone(value)


class SupplierLedgerSerializer(serializers.ModelSerializer):
    class Meta:
        model = SupplierLedger
        fields = ["id", "entry_type", "amount", "balance_after", "purchase", "note", "created_at"]


class PaySupplierSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))
    method = serializers.ChoiceField(choices=["cash", "upi"])
    reference = serializers.CharField(max_length=60, required=False, allow_blank=True, default="")
    note = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")