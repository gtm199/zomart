"""Online credit (khata). The shop decides who gets credit and how much; the limit lives on the shop's own Customer record."""
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.customers.models import Customer
from apps.orders.models import Order, ShopperCredit
from apps.shops.models import Shop
from services.exceptions import BusinessRuleError
from services.money import money

C = ShopperCredit.Status
ACTIVE_ORDERS = [Order.Status.PLACED, Order.Status.ACCEPTED, Order.Status.PACKED,
                 Order.Status.OUT_FOR_DELIVERY, Order.Status.READY_FOR_PICKUP]


def snapshot(link):
    """limit, what is owed, what is promised in orders not yet handed over, and what is left to use."""
    customer = link.customer
    limit = money(customer.credit_limit if customer and customer.credit_limit is not None else 0)
    owed = money(customer.balance if customer else 0)
    reserved = money(Order.objects.filter(shopper=link.shopper, shop=link.shop, payment_method=Order.Payment.CREDIT,
                                          status__in=ACTIVE_ORDERS).aggregate(t=Sum("subtotal"))["t"] or 0)
    return {"limit": limit, "owed": owed, "reserved": reserved,
            "available": money(max(Decimal("0"), limit - owed - reserved))}


def request_credit(shopper, shop_id):
    shop = Shop.objects.filter(pk=shop_id, store_enabled=True, is_active=True, is_approved=True).first()
    if shop is None:
        raise BusinessRuleError("This shop is not available.", "shop_closed")
    link, created = ShopperCredit.objects.get_or_create(shopper=shopper, shop=shop)
    if not created and link.status == C.DECLINED:
        link.status, link.decided_at = C.REQUESTED, None  # the customer may ask again
        link.save(update_fields=["status", "decided_at"])
    return link


@transaction.atomic
def approve(*, shop, credit_id, limit, customer_id=None):
    """Approve, or change the limit of an approved customer. Linking to an existing customer must be chosen on purpose,
    because a mobile number in the app is not checked and could belong to somebody else."""
    link = ShopperCredit.objects.select_for_update(of=("self",)).select_related("shopper", "customer").filter(pk=credit_id, shop=shop).first()
    if link is None:
        raise BusinessRuleError("Credit request not found.", "not_found")
    limit = money(limit)
    if limit <= 0:
        raise BusinessRuleError("Give a limit greater than zero.", "invalid_limit")
    if customer_id:
        customer = Customer.objects.filter(shop=shop, pk=customer_id, is_active=True).first()
        if customer is None:
            raise BusinessRuleError("That customer is not in your shop.", "customer_not_found")
    elif link.customer_id:
        customer = link.customer
    else:
        if Customer.objects.filter(shop=shop, phone=link.shopper.phone).exists():
            raise BusinessRuleError(
                "You already have a customer with this phone number. Choose whether to link to them, "
                "after you have checked that it is the same person.", "customer_exists")
        customer = Customer.objects.create(shop=shop, name=link.shopper.name, phone=link.shopper.phone)
    if ShopperCredit.objects.filter(customer=customer).exclude(pk=link.pk).exists():
        raise BusinessRuleError("That customer is already linked to another app account.", "already_linked")
    customer.credit_limit = limit
    customer.save(update_fields=["credit_limit", "updated_at"])
    link.customer, link.status, link.decided_at = customer, C.APPROVED, timezone.now()
    link.save(update_fields=["customer", "status", "decided_at"])
    return link


@transaction.atomic
def decide(*, shop, credit_id, status):
    link = ShopperCredit.objects.select_for_update().filter(pk=credit_id, shop=shop).first()
    if link is None:
        raise BusinessRuleError("Credit request not found.", "not_found")
    if status == C.SUSPENDED and link.status != C.APPROVED:
        raise BusinessRuleError("Only approved credit can be suspended.", "wrong_status")
    if status == C.DECLINED and link.status == C.APPROVED:
        raise BusinessRuleError("Use Suspend for a customer who already has credit.", "wrong_status")
    link.status, link.decided_at = status, timezone.now()
    link.save(update_fields=["status", "decided_at"])
    return link