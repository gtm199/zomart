from django.conf import settings
from django.db import models


class Brand(models.Model):
    name = models.CharField(max_length=120, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Category(models.Model):
    name = models.CharField(max_length=120)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="children")
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name_plural = "categories"
        ordering = ["sort_order", "name"]
        constraints = [models.UniqueConstraint(fields=["parent", "name"], name="uniq_category_parent_name")]

    def __str__(self):
        return self.name


class MasterProduct(models.Model):
    """Platform-owned product identity. Holds NO vendor price, cost or stock."""

    class Unit(models.TextChoices):
        GRAM = "g"
        KILOGRAM = "kg"
        MILLILITRE = "ml"
        LITRE = "l"
        PIECE = "pc"

    class Status(models.TextChoices):
        DRAFT = "draft"
        PENDING = "pending_review"
        ACTIVE = "active"
        INACTIVE = "inactive"

    name = models.CharField(max_length=200)
    brand = models.ForeignKey(Brand, null=True, blank=True, on_delete=models.PROTECT, related_name="products")
    category = models.ForeignKey(Category, null=True, blank=True, on_delete=models.PROTECT, related_name="products")
    pack_size = models.DecimalField(max_digits=10, decimal_places=3, default=1)
    unit = models.CharField(max_length=3, choices=Unit.choices, default=Unit.PIECE)
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to="catalog/", blank=True)
    mrp = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)       # governed field
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)   # governed field (GST %)
    hsn_code = models.CharField(max_length=10, blank=True)
    is_loose = models.BooleanField(default=False, help_text="Sold loose / without a barcode")
    search_keywords = models.CharField(max_length=300, blank=True)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.DRAFT)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        indexes = [models.Index(fields=["status", "name"])]

    @property
    def pack_label(self):
        return f"{format(self.pack_size.normalize(), 'f')} {self.unit}"

    @property
    def display_name(self):
        parts = [self.brand.name if self.brand_id else "", self.name, self.pack_label]
        return " ".join(p for p in parts if p)

    def __str__(self):
        return self.display_name


class ProductBarcode(models.Model):
    class Symbology(models.TextChoices):
        EAN13 = "EAN13"
        EAN8 = "EAN8"
        UPCA = "UPCA"
        CODE128 = "CODE128"
        OTHER = "OTHER"

    product = models.ForeignKey(MasterProduct, on_delete=models.CASCADE, related_name="barcodes")
    code = models.CharField(max_length=48, unique=True)  # one code identifies exactly one product variant
    symbology = models.CharField(max_length=8, choices=Symbology.choices, default=Symbology.OTHER)
    is_primary = models.BooleanField(default=False)

    def __str__(self):
        return self.code


class ProductChangeLog(models.Model):
    product = models.ForeignKey(MasterProduct, on_delete=models.CASCADE, related_name="change_logs")
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    field = models.CharField(max_length=40)
    old_value = models.TextField(blank=True)
    new_value = models.TextField(blank=True)
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-changed_at", "-id"]


class ProductSuggestion(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending"
        APPROVED = "approved"
        REJECTED = "rejected"

    shop = models.ForeignKey("shops.Shop", on_delete=models.PROTECT, related_name="product_suggestions")
    suggested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    name = models.CharField(max_length=200)
    brand_name = models.CharField(max_length=120, blank=True)
    barcode = models.CharField(max_length=48, blank=True)
    pack_size = models.DecimalField(max_digits=10, decimal_places=3, default=1)
    unit = models.CharField(max_length=3, choices=MasterProduct.Unit.choices, default=MasterProduct.Unit.PIECE)
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    resulting_product = models.ForeignKey(MasterProduct, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
