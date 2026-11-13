"""Data retention. Every link here is PROTECT, so nothing in this app can ever delete a shop, a bill or a customer by cascade."""
from django.db import models


class RetentionPolicy(models.Model):
    """One per shop. Off by default: a shop keeps everything until its owner switches this on."""
    shop = models.OneToOneField("shops.Shop", on_delete=models.PROTECT, related_name="retention_policy")
    enabled = models.BooleanField(default=False)
    keep_months = models.PositiveSmallIntegerField(default=84)    # bill item details older than this are archived (never less than 12)
    notify_days = models.PositiveSmallIntegerField(default=14)    # warning given before anything is archived
    last_run_on = models.DateField(null=True, blank=True)         # makes sure the cleanup runs once a day
    updated_at = models.DateTimeField(auto_now=True)


class RetentionNotice(models.Model):
    """The warning sent to a shop before any of its bills are touched."""

    class Status(models.TextChoices):
        ANNOUNCED = "announced"
        POSTPONED = "postponed"
        DONE = "done"
        CANCELLED = "cancelled"

    shop = models.ForeignKey("shops.Shop", on_delete=models.PROTECT, related_name="retention_notices")
    cutoff_at = models.DateTimeField()           # only bills older than this are covered by the warning
    delete_after = models.DateField()            # nothing happens before this day
    bills_count = models.PositiveIntegerField(default=0)
    items_count = models.PositiveIntegerField(default=0)
    oldest_bill = models.DateField(null=True, blank=True)
    newest_bill = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ANNOUNCED)
    postponed_count = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    done_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]


class BillArchive(models.Model):
    """A complete, compressed copy of bills (header, items and payments), kept before their item details are removed."""
    shop = models.ForeignKey("shops.Shop", on_delete=models.PROTECT, related_name="bill_archives")
    notice = models.ForeignKey(RetentionNotice, null=True, blank=True, on_delete=models.PROTECT, related_name="archives")
    period_from = models.DateField()
    period_to = models.DateField()
    bills_count = models.PositiveIntegerField()
    items_count = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64)
    size_bytes = models.PositiveIntegerField()
    data = models.BinaryField()                  # gzip of one JSON line per bill
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]


class ArchivedBill(models.Model):
    """Marks a bill whose item details were archived. PROTECT: while this exists, the bill itself cannot be deleted."""
    sale = models.OneToOneField("sales.Sale", on_delete=models.PROTECT, related_name="retention_marker")
    archive = models.ForeignKey(BillArchive, on_delete=models.PROTECT, related_name="bills")
    archived_at = models.DateTimeField(auto_now_add=True)


class RetentionLog(models.Model):
    """What every daily run did for a shop."""
    shop = models.ForeignKey("shops.Shop", on_delete=models.PROTECT, related_name="retention_logs")
    run_on = models.DateField()
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)
    outcome = models.CharField(max_length=20, default="running")   # nothing / announced / archived / blocked / error
    announced_bills = models.PositiveIntegerField(default=0)       # bills named in a new warning today
    bills_archived = models.PositiveIntegerField(default=0)        # bills whose item details were archived and removed today
    items_deleted = models.PositiveIntegerField(default=0)         # bill item rows removed today
    notice = models.ForeignKey(RetentionNotice, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    archive = models.ForeignKey(BillArchive, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    message = models.TextField(blank=True)

    class Meta:
        ordering = ["-run_on", "-id"]