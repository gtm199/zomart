from django.db import models


class SubscriptionPlan(models.Model):
    code = models.SlugField(unique=True)
    name = models.CharField(max_length=60)
    price_monthly = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    max_products = models.PositiveIntegerField(null=True, blank=True, help_text="Blank = unlimited")
    max_employees = models.PositiveIntegerField(null=True, blank=True, help_text="Employees besides the owner. Blank = unlimited")
    whatsapp_monthly_limit = models.PositiveIntegerField(default=0)
    features = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class ShopSubscription(models.Model):
    class Status(models.TextChoices):
        TRIAL = "trial"
        ACTIVE = "active"
        CANCELLED = "cancelled"

    shop = models.ForeignKey("shops.Shop", on_delete=models.PROTECT, related_name="subscriptions")
    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.PROTECT)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.TRIAL)
    starts_on = models.DateField()
    expires_on = models.DateField()
    grace_days = models.PositiveSmallIntegerField(default=7)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.shop} - {self.plan} until {self.expires_on}"
