from decimal import Decimal

from rest_framework import serializers

from .models import CashClose, Expense


class ExpenseSerializer(serializers.ModelSerializer):
    category = serializers.CharField(source="category.name", read_only=True)

    class Meta:
        model = Expense
        fields = ["id", "category", "amount", "method", "expense_date", "note", "is_voided", "created_at"]


class ExpenseCreateSerializer(serializers.Serializer):
    category = serializers.CharField(max_length=80)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))
    method = serializers.ChoiceField(choices=["cash", "upi"])
    expense_date = serializers.DateField(required=False, default=None)
    note = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class CashCloseSerializer(serializers.ModelSerializer):
    class Meta:
        model = CashClose
        fields = ["id", "close_date", "opening_cash", "expected_cash", "counted_cash", "difference", "note", "created_at"]


class CashCloseInputSerializer(serializers.Serializer):
    date = serializers.DateField(required=False, default=None)
    counted_cash = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0"))
    opening_cash = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0"), required=False, default=None)
    note = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")