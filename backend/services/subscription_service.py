from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from apps.subscriptions.models import ShopSubscription, SubscriptionPlan
from services.exceptions import SubscriptionLimitReached

# Placeholder plans. Prices/limits are illustrative: edit via Django admin, not code.
DEFAULT_PLANS = [
    dict(code="starter", name="Starter", price_monthly=Decimal("0"), max_products=300,
         max_employees=1, whatsapp_monthly_limit=0),
    dict(code="standard", name="Standard", price_monthly=Decimal("499"), max_products=3000,
         max_employees=5, whatsapp_monthly_limit=500),
    dict(code="premium", name="Premium", price_monthly=Decimal("999"), max_products=None,
         max_employees=None, whatsapp_monthly_limit=2000),
]


def seed_default_plans():
    for plan in DEFAULT_PLANS:
        data = dict(plan)
        code = data.pop("code")
        SubscriptionPlan.objects.get_or_create(code=code, defaults=data)


def current_subscription(shop):
    return shop.subscriptions.exclude(status=ShopSubscription.Status.CANCELLED).order_by("-expires_on", "-id").first()


def start_trial(shop, days=30, plan_code="starter"):
    seed_default_plans()
    plan = SubscriptionPlan.objects.get(code=plan_code)
    today = timezone.localdate()
    return ShopSubscription.objects.create(
        shop=shop, plan=plan, status=ShopSubscription.Status.TRIAL,
        starts_on=today, expires_on=today + timedelta(days=days),
    )


def is_write_allowed(shop):
    sub = current_subscription(shop)
    if sub is None:
        return False
    return timezone.localdate() <= sub.expires_on + timedelta(days=sub.grace_days)


def check_limit(shop, resource):
    """resource: 'products' or 'employees'. Raises SubscriptionLimitReached when over the plan limit."""
    from apps.inventory.models import ShopProduct
    from apps.shops.models import ShopMembership

    sub = current_subscription(shop)
    if sub is None:
        raise SubscriptionLimitReached("No active subscription for this shop.")
    if resource == "products":
        limit = sub.plan.max_products
        used = ShopProduct.objects.filter(shop=shop).count()
    else:
        limit = sub.plan.max_employees
        used = ShopMembership.objects.filter(shop=shop, is_active=True).exclude(role="owner").count()
    if limit is not None and used >= limit:
        raise SubscriptionLimitReached(f"Your {sub.plan.name} plan allows {limit} {resource}. Upgrade to add more.")



# ---------------- payment identity, renewals and approval (appended) ----------------
from django.conf import settings
from django.db import transaction

from services.money import money


def ensure_payment_identity(shop):
    """Every shop gets a code to write in the UPI note and a few paise added to its amount, so a payment
    can be matched to the shop even when the note is missing."""
    from apps.shops.models import Shop

    changed = []
    if not shop.payment_code:
        shop.payment_code = f"{getattr(settings, 'PAYMENT_CODE_PREFIX', 'KP')}-{shop.pk:04d}"
        changed.append("payment_code")
    if not shop.pay_paise:
        used = set(Shop.objects.exclude(pk=shop.pk).values_list("pay_paise", flat=True))
        free = [p for p in range(1, 100) if p not in used]
        shop.pay_paise = free[0] if free else (shop.pk % 99) + 1
        changed.append("pay_paise")
    if changed:
        shop.save(update_fields=changed)
    return shop


def amount_for(plan, months, shop):
    """What the shop must pay: plan price x months, plus the shop's own paise."""
    return money(plan.price_monthly * months + Decimal(shop.pay_paise) / 100)


def days_left(subscription):
    return None if subscription is None else (subscription.expires_on - timezone.localdate()).days


def plan_for_manual(shop):
    """Plan used when you confirm a payment by hand: the shop's current plan, else the cheapest paid plan."""
    sub = current_subscription(shop)
    if sub and sub.plan.price_monthly > 0:
        return sub.plan
    return SubscriptionPlan.objects.filter(is_active=True, price_monthly__gt=0).order_by("price_monthly").first()


@transaction.atomic
def renew_shop(shop, plan, months):
    """Adds 30 days per month paid. Unused days of the current period are kept."""
    sub = current_subscription(shop)
    today = timezone.localdate()
    start_from = max(today, sub.expires_on) if sub else today
    new_expiry = start_from + timedelta(days=30 * months)
    if sub and sub.plan_id == plan.id:
        sub.status = ShopSubscription.Status.ACTIVE
        sub.expires_on = new_expiry
        sub.save(update_fields=["status", "expires_on"])
    else:
        if sub:  # plan changed: close the old record and keep its history
            sub.status = ShopSubscription.Status.CANCELLED
            sub.save(update_fields=["status"])
        ShopSubscription.objects.create(shop=shop, plan=plan, status=ShopSubscription.Status.ACTIVE,
                                        starts_on=today, expires_on=new_expiry)
    return new_expiry


@transaction.atomic
def approve_shop(shop):
    """Approval switches the shop on and starts its free trial (the trial does not run while it waits)."""
    shop.is_approved = True
    shop.save(update_fields=["is_approved"])
    ensure_payment_identity(shop)
    if current_subscription(shop) is None:
        start_trial(shop)