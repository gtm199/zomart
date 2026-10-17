from django.conf import settings
from django.db import models


class Sale(models.Model):
    class Status(models.TextChoices):
        COMPLETED = "completed"
        PARTIALLY_RETURNED = "partially_returned"
        RETURNED = "returned"

    shop = models.ForeignKey("shops.Shop", on_delete=models.PROTECT, related_name="sales")
    invoice_number = models.CharField(max_length=20)
    client_txn_id = models.UUIDField()  # generated on the phone; makes checkout idempotent
    customer = models.ForeignKey("customers.Customer", null=True, blank=True, on_delete=models.PROTECT, related_name="sales")
    cashier = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.COMPLETED)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2)
    discount_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2)
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    amount_due = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    credit_reversed = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    notes = models.CharField(max_length=255, blank=True)
    is_offline = models.BooleanField(default=False)
    needs_review = models.BooleanField(default=False)
    review_note = models.TextField(blank=True, default="")
    client_created_at = models.DateTimeField(null=True, blank=True)  # time the bill was made on the phone
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["shop", "client_txn_id"], name="uniq_sale_shop_txn"),
            models.UniqueConstraint(fields=["shop", "invoice_number"], name="uniq_sale_shop_invoice"),
        ]
        indexes = [models.Index(fields=["shop", "-created_at"])]

    def __str__(self):
        return f"{self.invoice_number} ({self.shop})"


class SaleItem(models.Model):
    """Snapshot of what was sold. Later catalogue or price changes never alter these values."""
    sale = models.ForeignKey(Sale, on_delete=models.PROTECT, related_name="items")
    shop_product = models.ForeignKey("inventory.ShopProduct", on_delete=models.PROTECT, related_name="+")
    product_name = models.CharField(max_length=300)
    barcode = models.CharField(max_length=48, blank=True)
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    line_total = models.DecimalField(max_digits=12, decimal_places=2)
    purchase_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    returned_qty = models.DecimalField(max_digits=12, decimal_places=3, default=0)


class Payment(models.Model):
    class Kind(models.TextChoices):
        SALE = "sale"
        REFUND = "refund"
        CUSTOMER_RECEIPT = "customer_receipt"

    class Method(models.TextChoices):
        CASH = "cash"
        UPI = "upi"

    shop = models.ForeignKey("shops.Shop", on_delete=models.PROTECT, related_name="payments")
    sale = models.ForeignKey(Sale, null=True, blank=True, on_delete=models.PROTECT, related_name="payments")
    customer = models.ForeignKey("customers.Customer", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    method = models.CharField(max_length=5, choices=Method.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2)  # negative for refunds
    reference = models.CharField(max_length=60, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["shop", "-created_at"])]
