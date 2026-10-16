from django.conf import settings
from django.db import models


class ShopProduct(models.Model):
    """A shop's own listing of a master product: price, cost and stock live here, never on the master."""
    shop = models.ForeignKey("shops.Shop", on_delete=models.PROTECT, related_name="shop_products")
    master_product = models.ForeignKey("catalog.MasterProduct", on_delete=models.PROTECT)
    selling_price = models.DecimalField(max_digits=10, decimal_places=2)
    purchase_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    stock_qty = models.DecimalField(max_digits=12, decimal_places=3, default=0)  # changed only via inventory_service
    low_stock_threshold = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    is_enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["shop", "master_product"], name="uniq_shopproduct_shop_master"),
            models.CheckConstraint(condition=models.Q(selling_price__gte=0), name="shopproduct_price_gte_0"),
        ]
        indexes = [models.Index(fields=["shop", "is_enabled"])]

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
