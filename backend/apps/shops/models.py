from django.conf import settings
from django.db import models

from .roles import ROLE_CAPS


class Shop(models.Model):
    name = models.CharField(max_length=150)
    city = models.CharField(max_length=80, default="Etawah")
    address = models.CharField(max_length=255, blank=True)
    phone = models.CharField(max_length=15, blank=True)
    gstin = models.CharField(max_length=15, blank=True)
    is_active = models.BooleanField(default=True)
    allow_negative_stock = models.BooleanField(default=False)
    invoice_counter = models.PositiveIntegerField(default=0)
    #new fields
    store_enabled = models.BooleanField(default=False)
    store_code = models.CharField(max_length=12, blank=True)   # customers type this to find the shop
    accepts_delivery = models.BooleanField(default=True)
    accepts_pickup = models.BooleanField(default=True)
    delivery_fee = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    free_delivery_above = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    min_order = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    store_note = models.CharField(max_length=255, blank=True)  # hours, delivery area
    upi_id = models.CharField(max_length=80, blank=True)  # shown to customers who owe money, to pay by UPI
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)   # where the shop is
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    delivery_radius_km = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True, default=5)
    order_counter = models.PositiveIntegerField(default=0)

    is_approved = models.BooleanField(default=True)
    payment_code = models.CharField(max_length=20, blank=True)  # the shop writes this in the UPI note
    pay_paise = models.PositiveSmallIntegerField(default=0)     # extra paise added to this shop's amount

    # --- Optional GST billing (owner-only settings; see services/gst_settings_service.py) ---
    class GstScheme(models.TextChoices):
        REGULAR = "regular", "Regular (tax invoice)"
        COMPOSITION = "composition", "Composition (bill of supply)"

    gst_enabled = models.BooleanField(default=False)
    gst_enabled_at = models.DateTimeField(null=True, blank=True)  # last time it was switched on; older bills never change
    gst_legal_name = models.CharField(max_length=150, blank=True)
    gst_trade_name = models.CharField(max_length=150, blank=True)
    gst_address = models.CharField(max_length=300, blank=True)    # address printed on GST invoices
    gst_scheme = models.CharField(max_length=12, choices=GstScheme.choices, default=GstScheme.REGULAR)
    gst_state_code = models.CharField(max_length=2, default="07")  # place of supply of the shop (Delhi)

    class GstPriceMode(models.TextChoices):
        INCLUSIVE = "inclusive", "Prices include GST (MRP style)"
        EXCLUSIVE = "exclusive", "GST is added on top of prices"

    # Shop-wide default for how selling prices are entered. Each product can still differ (ShopProduct.price_includes_gst).
    gst_price_mode = models.CharField(max_length=9, choices=GstPriceMode.choices, default=GstPriceMode.INCLUSIVE)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        # Shop names are NOT unique (two real shops may share one), so every label carries the shop's own number and
        # mobile. Used by the admin's lists and dropdowns. Customer-facing text uses shop.name directly.
        return f"{self.name} (#{self.pk}{' · ' + self.phone if self.phone else ''})"

    class Meta:
            constraints = [models.UniqueConstraint(fields=["store_code"], condition=~models.Q(store_code=""),
                                                   name="uniq_shop_store_code")]
            
class ShopMembership(models.Model):
    class Role(models.TextChoices):
        OWNER = "owner"
        MANAGER = "manager"
        CASHIER = "cashier"
        INVENTORY = "inventory"
        ACCOUNTS = "accounts"
        DELIVERY = "delivery", "Delivery staff"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships")
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=12, choices=Role.choices)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "shop"], name="uniq_membership_user_shop")]

    def has_cap(self, cap):
        return cap in ROLE_CAPS.get(self.role, set())

    def __str__(self):
        return f"{self.user} @ {self.shop} ({self.role})"

class ShopNotification(models.Model):
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name="notifications")
    kind = models.CharField(max_length=30)
    title = models.CharField(max_length=150)
    message = models.CharField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["shop", "read_at"])]


class ShopGstChange(models.Model):
    """Audit trail of GST switch on/off and scheme changes. Stores no GSTIN."""
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name="gst_changes")
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    gst_enabled = models.BooleanField()
    gst_scheme = models.CharField(max_length=12)
    gstin_changed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
