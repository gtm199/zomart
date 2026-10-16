from django.conf import settings
from django.db import models


class Purchase(models.Model):
    class Status(models.TextChoices):
        RECEIVED = "received"
        PARTIALLY_RETURNED = "partially_returned"
        RETURNED = "returned"

    shop = models.ForeignKey("shops.Shop", on_delete=models.PROTECT, related_name="purchases")
    supplier = models.ForeignKey("suppliers.Supplier", on_delete=models.PROTECT, related_name="purchases")
    invoice_number = models.CharField(max_length=40, blank=True)  # the supplier's own bill number
    client_txn_id = models.UUIDField()  # idempotency key generated on the phone
    purchase_date = models.DateField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.RECEIVED)
    total = models.DecimalField(max_digits=12, decimal_places=2)
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    amount_due = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    due_reversed = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    notes = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-purchase_date", "-id"]
        constraints = [models.UniqueConstraint(fields=["shop", "client_txn_id"], name="uniq_purchase_shop_txn")]
        indexes = [models.Index(fields=["shop", "-purchase_date"])]

    def __str__(self):
        return f"Purchase {self.pk} ({self.shop})"


class PurchaseItem(models.Model):
    purchase = models.ForeignKey(Purchase, on_delete=models.PROTECT, related_name="items")
    shop_product = models.ForeignKey("inventory.ShopProduct", on_delete=models.PROTECT, related_name="+")
    product_name = models.CharField(max_length=300)  # snapshot
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2)
    line_total = models.DecimalField(max_digits=12, decimal_places=2)
    returned_qty = models.DecimalField(max_digits=12, decimal_places=3, default=0)