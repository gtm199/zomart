from django.db import transaction

from apps.customers.models import Customer, CustomerLedger
from apps.sales.models import Payment
from services.exceptions import BusinessRuleError
from services.money import money


@transaction.atomic
def post_entry(*, customer_id, entry_type, amount, user=None, sale=None, note=""):
    """amount > 0 increases what the customer owes; amount < 0 reduces it."""
    customer = Customer.objects.select_for_update().get(pk=customer_id)
    customer.balance = customer.balance + amount
    customer.save(update_fields=["balance", "updated_at"])
    return CustomerLedger.objects.create(
        shop=customer.shop, customer=customer, entry_type=entry_type, amount=amount,
        balance_after=customer.balance, sale=sale, note=note, created_by=user,
    )


@transaction.atomic
def receive_payment(*, customer_id, amount, method, user, note="", reference=""):
    amount = money(amount)
    if amount <= 0:
        raise BusinessRuleError("Amount must be greater than zero.", "invalid_amount")
    customer = Customer.objects.select_for_update().get(pk=customer_id)
    if amount > customer.balance:
        raise BusinessRuleError("Payment is more than the outstanding balance.", "overpayment")
    post_entry(customer_id=customer.pk, entry_type=CustomerLedger.EntryType.PAYMENT,
               amount=-amount, user=user, note=note)
    Payment.objects.create(
        shop=customer.shop, customer=customer, kind=Payment.Kind.CUSTOMER_RECEIPT,
        method=method, amount=amount, reference=reference, created_by=user,
    )
    customer.refresh_from_db()
    return customer
