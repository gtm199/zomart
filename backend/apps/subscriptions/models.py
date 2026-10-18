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

class PaymentSettings(models.Model):
    """One row: your UPI details, QR image and reminder days. Shown to shops in the app."""
    upi_id = models.CharField(max_length=80, blank=True)
    payee_name = models.CharField(max_length=80, blank=True)
    qr_image = models.ImageField(upload_to="platform/", blank=True)
    instructions = models.TextField(blank=True, default="")
    reminder_days = models.PositiveSmallIntegerField(default=7)

    class Meta:
        verbose_name_plural = "payment settings"

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return "Payment settings"


class BankCredit(models.Model):
    """One money-received line from your bank statement. The reference number can only be used once."""

    class Status(models.TextChoices):
        RENEWED = "renewed"
        REVIEW = "needs_review"
        IGNORED = "ignored"

    reference = models.CharField(max_length=80, unique=True)
    credit_date = models.DateField(null=True, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    narration = models.CharField(max_length=500, blank=True)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.REVIEW)
    shop = models.ForeignKey("shops.Shop", null=True, blank=True, on_delete=models.PROTECT, related_name="bank_credits")
    months = models.PositiveSmallIntegerField(default=1)
    matched_by = models.CharField(max_length=20, blank=True)  # code / amount / manual
    review_note = models.CharField(max_length=255, blank=True)
    new_expiry = models.DateField(null=True, blank=True)
    processed_by = models.ForeignKey("accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    processed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-credit_date", "-id"]

    def __str__(self):
        return f"{self.reference} ₹{self.amount}"