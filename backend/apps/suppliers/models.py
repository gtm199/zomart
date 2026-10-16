from django.conf import settings
from django.db import models
from django.db.models.functions import Lower


class Supplier(models.Model):
    """Owned by exactly one shop. Never shared between vendors."""
    shop = models.ForeignKey("shops.Shop", on_delete=models.PROTECT, related_name="suppliers")
    name = models.CharField(max_length=150)
    phone = models.CharField(max_length=15, blank=True)
    address = models.CharField(max_length=255, blank=True)
    gstin = models.CharField(max_length=15, blank=True)
    notes = models.CharField(max_length=255, blank=True)
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0,
                                  help_text="Positive = the shop owes the supplier")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(Lower("name"), "shop", name="uniq_supplier_shop_name")]

    def __str__(self):
        return f"{self.name} ({self.shop})"


class SupplierLedger(models.Model):
    class EntryType(models.TextChoices):
        PURCHASE = "purchase"
        PAYMENT = "payment"
        RETURN = "return"
        ADJUSTMENT = "adjustment"

    shop = models.ForeignKey("shops.Shop", on_delete=models.PROTECT, related_name="+")
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="ledger")
    entry_type = models.CharField(max_length=12, choices=EntryType.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2)  # signed; + increases what the shop owes
    balance_after = models.DecimalField(max_digits=12, decimal_places=2)
    purchase = models.ForeignKey("purchases.Purchase", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    note = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]


class SupplierPayment(models.Model):
    class Kind(models.TextChoices):
        PURCHASE = "purchase"   # paid at the time of receiving goods
        PAYMENT = "payment"     # later payment against the balance
        REFUND = "refund"       # money received back from supplier (purchase return)

    class Method(models.TextChoices):
        CASH = "cash"
        UPI = "upi"

    shop = models.ForeignKey("shops.Shop", on_delete=models.PROTECT, related_name="supplier_payments")
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="payments")
    purchase = models.ForeignKey("purchases.Purchase", null=True, blank=True, on_delete=models.PROTECT, related_name="payments")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    method = models.CharField(max_length=5, choices=Method.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2)  # + paid out, - refund received
    reference = models.CharField(max_length=60, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["shop", "-created_at"])]