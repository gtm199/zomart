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
    order_counter = models.PositiveIntegerField(default=0)

    is_approved = models.BooleanField(default=True)
    payment_code = models.CharField(max_length=20, blank=True)  # the shop writes this in the UPI note
    pay_paise = models.PositiveSmallIntegerField(default=0)     # extra paise added to this shop's amount
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

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