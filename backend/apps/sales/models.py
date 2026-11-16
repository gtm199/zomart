from django.conf import settings
from django.db import models


class Sale(models.Model):
    class Status(models.TextChoices):
        COMPLETED = "completed"
        PARTIALLY_RETURNED = "partially_returned"
        RETURNED = "returned"

    shop = models.ForeignKey("shops.Shop", on_delete=models.PROTECT, related_name="sales")
    invoice_number = models.CharField(max_length=20)
    client_txn_id = models.UUIDField()  # generated on the phone; makes checkout idempotent
    customer = models.ForeignKey("customers.Customer", null=True, blank=True, on_delete=models.PROTECT, related_name="sales")
    cashier = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.COMPLETED)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2)
    discount_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2)
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    amount_due = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    credit_reversed = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    notes = models.CharField(max_length=255, blank=True)
    is_offline = models.BooleanField(default=False)
    needs_review = models.BooleanField(default=False)
    review_note = models.TextField(blank=True, default="")
    client_created_at = models.DateTimeField(null=True, blank=True)  # time the bill was made on the phone

    # --- GST snapshot (frozen at billing time; "bill" = a plain non-GST bill, exactly as before) ---
    class DocumentType(models.TextChoices):
        BILL = "bill", "Bill"
        TAX_INVOICE = "tax_invoice", "Tax invoice"
        BILL_OF_SUPPLY = "bill_of_supply", "Bill of supply"

    document_type = models.CharField(max_length=15, choices=DocumentType.choices, default=DocumentType.BILL)
    taxable_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    cgst_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    sgst_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    igst_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    round_off = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    seller_gstin = models.CharField(max_length=15, blank=True)
    seller_legal_name = models.CharField(max_length=150, blank=True)
    seller_trade_name = models.CharField(max_length=150, blank=True)
    seller_address = models.CharField(max_length=300, blank=True)
    seller_state_code = models.CharField(max_length=2, blank=True)
    place_of_supply = models.CharField(max_length=2, blank=True)      # state code
    customer_gstin = models.CharField(max_length=15, blank=True)      # optional, business customers only
    customer_gst_name = models.CharField(max_length=150, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def is_gst_document(self):
        return self.document_type != self.DocumentType.BILL

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["shop", "client_txn_id"], name="uniq_sale_shop_txn"),
            models.UniqueConstraint(fields=["shop", "invoice_number"], name="uniq_sale_shop_invoice"),
        ]
        indexes = [models.Index(fields=["shop", "-created_at"])]

    def __str__(self):
        return f"{self.invoice_number} ({self.shop})"


class SaleItem(models.Model):
    """Snapshot of what was sold. Later catalogue or price changes never alter these values."""
    sale = models.ForeignKey(Sale, on_delete=models.PROTECT, related_name="items")
    shop_product = models.ForeignKey("inventory.ShopProduct", on_delete=models.PROTECT, related_name="+")
    product_name = models.CharField(max_length=300)
    unit = models.CharField(max_length=3, blank=True, default="")  # kg / g / l / ml for loose items, blank for packs
    barcode = models.CharField(max_length=48, blank=True)
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    line_total = models.DecimalField(max_digits=12, decimal_places=2)
    purchase_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    returned_qty = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    # GST snapshot. On GST documents tax_rate = the GST rate and tax_amount = cgst + sgst + igst.
    hsn_code = models.CharField(max_length=8, blank=True)
    price_includes_gst = models.BooleanField(default=True)
    taxable_value = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    cgst = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    sgst = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    igst = models.DecimalField(max_digits=10, decimal_places=2, default=0)


class Payment(models.Model):
    class Kind(models.TextChoices):
        SALE = "sale"
        REFUND = "refund"
        CUSTOMER_RECEIPT = "customer_receipt"

    class Method(models.TextChoices):
        CASH = "cash"
        UPI = "upi"

    shop = models.ForeignKey("shops.Shop", on_delete=models.PROTECT, related_name="payments")
    sale = models.ForeignKey(Sale, null=True, blank=True, on_delete=models.PROTECT, related_name="payments")
    customer = models.ForeignKey("customers.Customer", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    method = models.CharField(max_length=5, choices=Method.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2)  # negative for refunds
    reference = models.CharField(max_length=60, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["shop", "-created_at"])]


class InvoiceSequence(models.Model):
    """One consecutive number series per shop, per document series, per financial year (1 Apr - 31 Mar).
    Only GST documents use it; plain bills keep Shop.invoice_counter. Always updated under select_for_update."""
    shop = models.ForeignKey("shops.Shop", on_delete=models.PROTECT, related_name="invoice_sequences")
    series = models.CharField(max_length=15)          # tax_invoice / bill_of_supply / credit_note
    fy_start_year = models.PositiveSmallIntegerField()  # 2026 = FY 2026-27
    last_number = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["shop", "series", "fy_start_year"], name="uniq_invoice_sequence")]


class CreditNote(models.Model):
    """Issued when goods on a GST document are returned. Reverses the tax of the returned part and links to the
    original invoice. Stock and money are handled by the normal return in billing_service."""
    shop = models.ForeignKey("shops.Shop", on_delete=models.PROTECT, related_name="credit_notes")
    sale = models.ForeignKey(Sale, on_delete=models.PROTECT, related_name="credit_notes")
    number = models.CharField(max_length=20)
    original_invoice_number = models.CharField(max_length=20)
    original_document_type = models.CharField(max_length=15)
    taxable_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    cgst_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    sgst_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    igst_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    seller_gstin = models.CharField(max_length=15, blank=True)
    seller_legal_name = models.CharField(max_length=150, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [models.UniqueConstraint(fields=["shop", "number"], name="uniq_credit_note_shop_number")]
        indexes = [models.Index(fields=["shop", "-created_at"])]


class CreditNoteItem(models.Model):
    """Snapshot of the returned part of one invoice line (copied, so it survives bill-item archiving)."""
    credit_note = models.ForeignKey(CreditNote, on_delete=models.CASCADE, related_name="items")
    sale_item_id_ref = models.PositiveBigIntegerField()
    product_name = models.CharField(max_length=300)
    hsn_code = models.CharField(max_length=8, blank=True)
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    gst_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    taxable_value = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    cgst = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    sgst = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    igst = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    line_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
