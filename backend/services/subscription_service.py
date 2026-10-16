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
