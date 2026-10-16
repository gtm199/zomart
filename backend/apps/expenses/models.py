from django.conf import settings
from django.db import models
from django.db.models.functions import Lower


class ExpenseCategory(models.Model):
    shop = models.ForeignKey("shops.Shop", on_delete=models.PROTECT, related_name="expense_categories")
    name = models.CharField(max_length=80)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "expense categories"
        constraints = [models.UniqueConstraint(Lower("name"), "shop", name="uniq_expense_cat_shop_name")]

    def __str__(self):
        return self.name


class Expense(models.Model):
    class Method(models.TextChoices):
        CASH = "cash"
        UPI = "upi"

    shop = models.ForeignKey("shops.Shop", on_delete=models.PROTECT, related_name="expenses")
    category = models.ForeignKey(ExpenseCategory, on_delete=models.PROTECT, related_name="expenses")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    method = models.CharField(max_length=5, choices=Method.choices)
    expense_date = models.DateField()
    note = models.CharField(max_length=255, blank=True)
    is_voided = models.BooleanField(default=False)  # expenses are voided, never deleted
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-expense_date", "-id"]
        indexes = [models.Index(fields=["shop", "expense_date"])]
        constraints = [models.CheckConstraint(condition=models.Q(amount__gt=0), name="expense_amount_gt_0")]


class CashClose(models.Model):
    """End-of-day cash count. One per shop per day; never edited afterwards."""
    shop = models.ForeignKey("shops.Shop", on_delete=models.PROTECT, related_name="cash_closes")
    close_date = models.DateField()
    opening_cash = models.DecimalField(max_digits=12, decimal_places=2)
    expected_cash = models.DecimalField(max_digits=12, decimal_places=2)
    counted_cash = models.DecimalField(max_digits=12, decimal_places=2)
    difference = models.DecimalField(max_digits=12, decimal_places=2)  # counted - expected
    note = models.CharField(max_length=255, blank=True)
    closed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-close_date"]
        constraints = [models.UniqueConstraint(fields=["shop", "close_date"], name="uniq_cashclose_shop_date")]