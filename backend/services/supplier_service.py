from django.db import transaction

from apps.suppliers.models import Supplier, SupplierLedger, SupplierPayment
from services.exceptions import BusinessRuleError
from services.money import money


@transaction.atomic
def post_entry(*, supplier_id, entry_type, amount, user=None, purchase=None, note=""):
    """amount > 0 increases what the shop owes the supplier; amount < 0 reduces it."""
    supplier = Supplier.objects.select_for_update().get(pk=supplier_id)
    supplier.balance = supplier.balance + amount
    supplier.save(update_fields=["balance"])
    return SupplierLedger.objects.create(
        shop=supplier.shop, supplier=supplier, entry_type=entry_type, amount=amount,
        balance_after=supplier.balance, purchase=purchase, note=note, created_by=user)


@transaction.atomic
def pay_supplier(*, supplier_id, amount, method, user, reference="", note=""):
    amount = money(amount)
    if amount <= 0:
        raise BusinessRuleError("Amount must be greater than zero.", "invalid_amount")
    supplier = Supplier.objects.select_for_update().get(pk=supplier_id)
    if amount > supplier.balance:
        raise BusinessRuleError("Payment is more than the amount you owe this supplier.", "overpayment")
    post_entry(supplier_id=supplier.pk, entry_type=SupplierLedger.EntryType.PAYMENT, amount=-amount,
               user=user, note=note)
    SupplierPayment.objects.create(shop=supplier.shop, supplier=supplier, kind=SupplierPayment.Kind.PAYMENT,
                                   method=method, amount=amount, reference=reference, created_by=user)
    supplier.refresh_from_db()
    return supplier