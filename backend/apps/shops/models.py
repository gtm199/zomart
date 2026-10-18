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
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


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