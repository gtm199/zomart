from django.conf import settings
from django.db import models


class Customer(models.Model):
    """Owned by exactly one shop. The same person under two shops is two unrelated rows."""
    shop = models.ForeignKey("shops.Shop", on_delete=models.PROTECT, related_name="customers")
    name = models.CharField(max_length=150)
    phone = models.CharField(max_length=15, blank=True)
    whatsapp_number = models.CharField(max_length=15, blank=True)
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text="Positive = customer owes the shop")
    notes = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)  # lets the phone ask "what changed?"

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["shop", "phone"], condition=~models.Q(phone=""), name="uniq_customer_shop_phone"),
        ]

    def __str__(self):
        return f"{self.name} ({self.shop})"


class CustomerLedger(models.Model):
    class EntryType(models.TextChoices):
        CREDIT_SALE = "credit_sale"
        PAYMENT = "payment"
        REFUND = "refund"
        ADJUSTMENT = "adjustment"

    shop = models.ForeignKey("shops.Shop", on_delete=models.PROTECT, related_name="+")
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="ledger")
    entry_type = models.CharField(max_length=12, choices=EntryType.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2)  # signed; + increases amount owed
    balance_after = models.DecimalField(max_digits=12, decimal_places=2)
    sale = models.ForeignKey("sales.Sale", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    note = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
