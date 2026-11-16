"""Removing a staff member from a shop. Views only call remove_member(); all rules live here.

Why the person's account is not deleted from the database: bills (cashier), stock movements, purchases, expenses, cash
closes and deliveries (rider) point at it. Deleting it would blank "who did this" on every one of those records, which
breaks the shop's audit trail. So "delete" means:
  1. their membership of this shop is deleted (they disappear from the staff list and lose all access to this shop);
  2. if they belong to no other shop: they are signed out everywhere, their account is locked, and their mobile number
     and email are freed, so the owner can add the same person again later as a new staff member;
  3. old bills keep pointing at the locked account, so history still shows who made them.
"""
from django.db import transaction
from rest_framework.authtoken.models import Token

from apps.orders.models import Order
from apps.shops.models import ShopMembership
from services.exceptions import BusinessRuleError

REMOVED_PREFIX = "removed-"


@transaction.atomic
def remove_member(*, shop, actor, membership_id):
    member = (ShopMembership.objects.select_for_update().select_related("user")
              .filter(shop=shop, pk=membership_id).first())
    if member is None:
        raise BusinessRuleError("This staff member was not found in your shop.", "member_not_found", 404)
    if member.role == ShopMembership.Role.OWNER:
        raise BusinessRuleError("The shop owner cannot be removed.", "owner_cannot_be_removed", 403)
    if member.user_id == actor.pk:
        raise BusinessRuleError("You cannot remove yourself.", "cannot_remove_self", 403)
    busy = Order.objects.filter(shop=shop, rider_id=member.user_id, status=Order.Status.OUT_FOR_DELIVERY).count()
    if busy:
        raise BusinessRuleError(f"{member.user.first_name or member.user.username} is delivering {busy} order(s) right now. "
                                "Finish those deliveries or give them to another rider first.", "rider_has_active_deliveries", 409)

    user = member.user
    name = user.first_name or user.username
    member.delete()

    still_staff_elsewhere = ShopMembership.objects.filter(user=user).exists()
    if not still_staff_elsewhere and not user.is_staff and not user.is_superuser:
        Token.objects.filter(user=user).delete()                       # signed out on every phone
        if not user.username.startswith(REMOVED_PREFIX):
            user.username = f"{REMOVED_PREFIX}{user.pk}-{user.username}"[:150]   # frees the mobile number for reuse
        user.email = ""                                                 # frees the email for reuse
        user.is_active = False                                          # can never sign in again
        user.set_unusable_password()
        user.save(update_fields=["username", "email", "is_active", "password"])
    return {"removed": True, "name": name, "account_locked": not still_staff_elsewhere}
