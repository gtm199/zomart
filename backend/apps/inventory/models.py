from django.conf import settings
from django.db import models
from decimal import Decimal

DEFAULT_LOW_STOCK_LEVEL = Decimal("2")  # used when a product has no level of its own

from django.utils import timezone

EXPIRY_ALERT_DAYS = 30  # products expiring within this many days are flagged

class ShopProduct(models.Model):
    """A shop's own listing of a master product: price, cost and stock live here, never on the master."""
    shop = models.ForeignKey("shops.Shop", on_delete=models.PROTECT, related_name="shop_products")
    master_product = models.ForeignKey("catalog.MasterProduct", on_delete=models.PROTECT)
    selling_price = models.DecimalField(max_digits=10, decimal_places=2)
    purchase_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    stock_qty = models.DecimalField(max_digits=12, decimal_places=3, default=0)  # changed only via inventory_service
    low_stock_threshold = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    is_enabled = models.BooleanField(default=True)
    online_visible = models.BooleanField(default=True)  # shown in the customer ordering app
    expiry_date = models.DateField(null=True, blank=True, help_text="Earliest expiry date of the stock in hand")
    # GST (used only when the shop has GST billing ON). gst_rate NULL = not confirmed by the vendor yet.
    # The master catalogue only *suggests* a rate/HSN; nothing ever copies it here automatically.
    gst_rate = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    hsn_code = models.CharField(max_length=8, blank=True)
    price_includes_gst = models.BooleanField(default=True)
    gst_confirmed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["shop", "master_product"], name="uniq_shopproduct_shop_master"),
            models.CheckConstraint(condition=models.Q(selling_price__gte=0), name="shopproduct_price_gte_0"),
        ]
        indexes = [models.Index(fields=["shop", "is_enabled"])]

    @property
    def is_low_stock(self):
        level = self.low_stock_threshold if self.low_stock_threshold > 0 else DEFAULT_LOW_STOCK_LEVEL
        return self.stock_qty <= level

    @property
    def days_to_expiry(self):
        if self.expiry_date is None:
            return None
        return (self.expiry_date - timezone.localdate()).days

    @property
    def expiry_status(self):
        """None when there is no date or no stock; otherwise expired / expiring_soon / ok."""
        days = self.days_to_expiry
        if days is None or self.stock_qty <= 0:
            return None
        if days < 0:
            return "expired"
        return "expiring_soon" if days <= EXPIRY_ALERT_DAYS else "ok"

    def __str__(self):
        return f"{self.shop} / {self.master_product}"


class StockMovement(models.Model):
    class Type(models.TextChoices):
        OPENING = "opening"
        PURCHASE = "purchase"
        SALE = "sale"
        RETURN = "return"
        ADJUSTMENT = "adjustment"
        DAMAGE = "damage"
        EXPIRED = "expired"

    shop = models.ForeignKey("shops.Shop", on_delete=models.PROTECT, related_name="stock_movements")
    shop_product = models.ForeignKey(ShopProduct, on_delete=models.PROTECT, related_name="movements")
    movement_type = models.CharField(max_length=12, choices=Type.choices)
    quantity_delta = models.DecimalField(max_digits=12, decimal_places=3)
    balance_after = models.DecimalField(max_digits=12, decimal_places=3)
    reference_type = models.CharField(max_length=20, blank=True)
    reference_id = models.PositiveBigIntegerField(null=True, blank=True)
    note = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["shop_product", "-created_at"])]


class StockBatch(models.Model):
    """One lot of a product with its own expiry date. Changed only by services/inventory_service.py.
    Stock without a known expiry date has no batch ("undated"); the sum of quantity_left never exceeds stock_qty.
    ShopProduct.expiry_date is kept equal to the earliest expiry among batches that still have pieces left."""

    class Source(models.TextChoices):
        PURCHASE = "purchase"
        OPENING = "opening"
        RECEIVED = "received"      # stock added from the stock screen
        MANUAL = "manual"          # date given to stock already on the shelf
        MIGRATED = "migrated"      # created from the old single expiry date

    shop = models.ForeignKey("shops.Shop", on_delete=models.PROTECT, related_name="stock_batches")
    shop_product = models.ForeignKey(ShopProduct, on_delete=models.PROTECT, related_name="batches")
    expiry_date = models.DateField()
    batch_no = models.CharField(max_length=40, blank=True)
    quantity_received = models.DecimalField(max_digits=12, decimal_places=3)
    quantity_left = models.DecimalField(max_digits=12, decimal_places=3)
    source = models.CharField(max_length=10, choices=Source.choices)
    purchase_id = models.PositiveBigIntegerField(null=True, blank=True)   # the purchase it came in with
    note = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["expiry_date", "id"]
        indexes = [models.Index(fields=["shop_product", "expiry_date"]), models.Index(fields=["shop", "expiry_date"])]
        constraints = [models.CheckConstraint(condition=models.Q(quantity_left__gte=0), name="stockbatch_left_gte_0")]

    @property
    def days_to_expiry(self):
        return (self.expiry_date - timezone.localdate()).days

    @property
    def status(self):
        if self.quantity_left <= 0:
            return "finished"
        days = self.days_to_expiry
        return "expired" if days < 0 else "expiring_soon" if days <= EXPIRY_ALERT_DAYS else "ok"

    def __str__(self):
        return f"{self.shop_product} · exp {self.expiry_date} · {self.quantity_left} left"
