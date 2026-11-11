import secrets

from django.contrib.auth.hashers import check_password, make_password
from django.db import models


class Shopper(models.Model):
    """A customer of the ordering app. Completely separate from shop staff (User) and from a shop's own Customer list."""
    phone = models.CharField(max_length=10, unique=True)
    name = models.CharField(max_length=150)
    password = models.CharField(max_length=128)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # lets Django REST Framework treat a Shopper like a signed-in user
    is_authenticated = True
    is_anonymous = False

    def set_password(self, raw):
        self.password = make_password(raw)

    def check_password(self, raw):
        return check_password(raw, self.password)

    def __str__(self):
        return f"{self.name} ({self.phone})"


class ShopperToken(models.Model):
    key = models.CharField(max_length=40, primary_key=True)
    shopper = models.ForeignKey(Shopper, on_delete=models.CASCADE, related_name="tokens")
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.key:
            self.key = secrets.token_hex(20)
        return super().save(*args, **kwargs)


class ShopperShop(models.Model):
    """The shops a customer has added to their app."""
    shopper = models.ForeignKey(Shopper, on_delete=models.CASCADE, related_name="my_shops")
    shop = models.ForeignKey("shops.Shop", on_delete=models.CASCADE, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["shopper", "shop"], name="uniq_shopper_shop")]


class Order(models.Model):
    class Status(models.TextChoices):
        PLACED = "placed"
        ACCEPTED = "accepted"
        PACKED = "packed"
        OUT_FOR_DELIVERY = "out_for_delivery"
        READY_FOR_PICKUP = "ready_for_pickup"
        COMPLETED = "completed"
        CANCELLED = "cancelled"
        REJECTED = "rejected"

    class Fulfilment(models.TextChoices):
        DELIVERY = "delivery"
        PICKUP = "pickup"

    class Payment(models.TextChoices):
        CASH = "cash"
        UPI = "upi"
        CREDIT = "credit"   # pay later: added to the customer's account (khata) at the shop

    shop = models.ForeignKey("shops.Shop", on_delete=models.PROTECT, related_name="orders")
    shopper = models.ForeignKey(Shopper, on_delete=models.PROTECT, related_name="orders")
    number = models.PositiveIntegerField()  # per shop: #1, #2, ...
    client_txn_id = models.UUIDField()  # makes a double tap on "Place order" harmless
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PLACED)
    fulfilment = models.CharField(max_length=10, choices=Fulfilment.choices)
    customer_name = models.CharField(max_length=150)   # copied at the time of the order
    customer_phone = models.CharField(max_length=10)
    delivery_address = models.CharField(max_length=300, blank=True)
    note = models.CharField(max_length=255, blank=True)
    payment_method = models.CharField(max_length=10, choices=Payment.choices, default=Payment.CASH)  # paid at the door / counter
    subtotal = models.DecimalField(max_digits=12, decimal_places=2)
    delivery_fee = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2)
    reason = models.CharField(max_length=255, blank=True)  # why it was rejected or cancelled
    sale = models.ForeignKey("sales.Sale", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    # delivery tracking
    rider = models.ForeignKey("accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    address = models.ForeignKey("orders.SavedAddress", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    delivery_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)  # a copy, used when there is no saved address
    delivery_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    delivery_pin = models.CharField(max_length=4, blank=True)   # the customer tells it to the rider; never sent to the shop or the rider
    pin_attempts = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["shop", "number"], name="uniq_order_shop_number"),
            models.UniqueConstraint(fields=["shopper", "client_txn_id"], name="uniq_order_shopper_txn"),
        ]
        indexes = [models.Index(fields=["shop", "status"])]

    def position(self):
        """Where to deliver, as (lat, lng) or None. The saved address is the source of truth, so when the customer moves
        the pin on it, every link built from it is right. The copy on the order is used if there is no saved address."""
        a = self.address
        if a is not None and a.lat is not None and a.lng is not None:
            return float(a.lat), float(a.lng)
        if self.delivery_lat is not None and self.delivery_lng is not None:
            return float(self.delivery_lat), float(self.delivery_lng)
        return None


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    shop_product = models.ForeignKey("inventory.ShopProduct", on_delete=models.PROTECT, related_name="+")
    product_name = models.CharField(max_length=300)
    unit = models.CharField(max_length=3, blank=True, default="")  # kg / l for loose items
    ordered_quantity = models.DecimalField(max_digits=12, decimal_places=3)
    quantity = models.DecimalField(max_digits=12, decimal_places=3)  # what the shop will actually send
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    line_total = models.DecimalField(max_digits=12, decimal_places=2)


class OrderEvent(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="events")
    status = models.CharField(max_length=20)
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

class ShopperCredit(models.Model):
    """A customer's request for credit (khata) at one shop, and the shop's answer.
    The shop's own Customer record (with its balance and limit) is linked only when the shop approves."""

    class Status(models.TextChoices):
        REQUESTED = "requested"
        APPROVED = "approved"
        DECLINED = "declined"
        SUSPENDED = "suspended"   # no new credit orders; what is already owed stays on the account

    shopper = models.ForeignKey(Shopper, on_delete=models.CASCADE, related_name="credits")
    shop = models.ForeignKey("shops.Shop", on_delete=models.CASCADE, related_name="+")
    customer = models.ForeignKey("customers.Customer", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.REQUESTED)
    requested_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["shopper", "shop"], name="uniq_shopper_credit")]

# added a new model for tracking delivery status and rider location
class DeliveryTrack(models.Model):
    """Where the rider is right now. One row per delivery, overwritten on every update; the position is erased when
    the order is delivered, so no location history is kept."""
    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name="track")
    started_at = models.DateTimeField(null=True, blank=True)
    arrived_at = models.DateTimeField(null=True, blank=True)
    rider_lat = models.FloatField(null=True, blank=True)
    rider_lng = models.FloatField(null=True, blank=True)
    heading = models.FloatField(null=True, blank=True)
    speed = models.FloatField(null=True, blank=True)       # metres per second
    accuracy = models.FloatField(null=True, blank=True)    # metres
    updated_at = models.DateTimeField(null=True, blank=True)

# added a new model for counting Google API calls, so we never exceed the free allowance
class SavedAddress(models.Model):
    """A delivery address the customer saved. The map position is stored with it, so it is never looked up again."""
    shopper = models.ForeignKey(Shopper, on_delete=models.CASCADE, related_name="addresses")
    label = models.CharField(max_length=30, default="Home")
    address = models.CharField(max_length=300)
    lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]