"""Retention of old data, built so that accounting and customer credit can not be hurt.

What is cleaned, and how:
  notifications        deleted after a number of days. No archive and no warning: they carry no accounting.
  platform logs        deleted after a number of days (admin log, used password codes ...). Platform-wide.
  audit log            archived, then deleted, after a warning to the shop.
  finished online orders  (delivered, cancelled, rejected) archived, then deleted, after a warning to the shop.
  bill item details    archived, then the item rows are removed, after a warning. The bill itself stays.

Never touched: bills (numbers, dates, totals, payments), customers, the customer ledger and balances, stock movements,
inventory, and any order that is not finished, is on hold, or is linked to a bill that still has money owed on it.

Every removal asks the database first what else would be deleted with it. If anything other than the rows meant to go would
be deleted (a cascade), the removal is cancelled and written to the log. Everything is done in small batches, once a day,
on each shop's own settings.
"""
import csv
import gzip
import hashlib
import io
import json
import logging
import zipfile
from collections import defaultdict
from datetime import timedelta

from django.apps import apps
from django.conf import settings
from django.core.exceptions import FieldDoesNotExist
from django.core.mail import EmailMessage
from django.core.management import call_command
from django.db import router, transaction
from django.db.models import Max, Min
from django.db.models.deletion import Collector, ProtectedError, RestrictedError
from django.utils import timezone

from apps.orders.models import DeliveryTrack, Order, OrderEvent, OrderItem
from apps.retention.models import (ArchivedBill, BillArchive, DataArchive, RetentionLog, RetentionNotice,
                                   RetentionPolicy)
from apps.sales.models import Payment, Sale, SaleItem
from apps.shops.models import ShopMembership

logger = logging.getLogger(__name__)

MIN_KEEP_MONTHS = 12          # bill item details
MIN_AUDIT_MONTHS = 12
MIN_ORDER_MONTHS = 6
MIN_NOTIFICATION_DAYS = 30
BILL_BATCH = 300
MAX_POSTPONES = 3
N = RetentionNotice.Status
FINISHED = (Order.Status.COMPLETED, Order.Status.CANCELLED, Order.Status.REJECTED)

# Platform-wide logs: (model, date column, days to keep). A model that does not exist in your project is skipped.
# To clean a new log table later, add one line here (or set RETENTION_LOG_RULES in the settings).
DEFAULT_LOG_RULES = [
    ("admin.LogEntry", "action_time", 90),               # what the platform admin did in the admin site
    ("accounts.PasswordResetCode", "created_at", 30),    # password reset codes, used or not
]


class Blocked(Exception):
    """A removal was cancelled because it would have deleted more than meant to, or the archive could not be verified."""


def _has(model, name):
    try:
        model._meta.get_field(name)
        return True
    except FieldDoesNotExist:
        return False


def _date_field(model, candidates):
    return next((c for c in candidates if _has(model, c)), None)


def months_ago(now, months):
    total = now.year * 12 + (now.month - 1) - months
    year, month = divmod(total, 12)
    feb = 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28
    day = min(now.day, [31, feb, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month])
    return now.replace(year=year, month=month + 1, day=day)


def days_ago(now, days):
    return now - timedelta(days=days)


def _batch_rows():
    return getattr(settings, "RETENTION_BATCH_ROWS", 1000)


def _max_rows():
    return getattr(settings, "RETENTION_MAX_ROWS_PER_RUN", 5000)


def policy_for(shop):
    policy, _ = RetentionPolicy.objects.get_or_create(shop=shop)
    return policy


def keep_months_of(policy):
    return max(policy.keep_months, MIN_KEEP_MONTHS)


# ---------------- copies, and the safe delete ----------------
def _row(obj):
    return {(f.attname if f.is_relation else f.name): getattr(obj, f.attname) for f in obj._meta.concrete_fields}


def to_json_lines(records):
    return "\n".join(json.dumps(r, default=str, separators=(",", ":")) for r in records).encode()


def _read(data):
    return [json.loads(line) for line in gzip.decompress(bytes(data)).decode().splitlines() if line.strip()]


def from_archive(archive):
    return _read(archive.data)


def from_data_archive(archive):
    return _read(archive.data)


def delete_rows_only(rows, allowed_models=()):
    """Deletes the given rows (and the detail rows of the models in allowed_models that belong to them), after asking the
    database what would be deleted. Raises Blocked if anything else would be deleted or changed, or something protects them.
    Returns (all rows deleted, rows of the main model deleted)."""
    rows = list(rows)
    if not rows:
        return 0, 0
    model = type(rows[0])
    collector = Collector(using=router.db_for_write(model))
    try:
        collector.collect(rows)
    except (ProtectedError, RestrictedError) as exc:
        raise Blocked(f"Cancelled: something depends on these {model._meta.verbose_name_plural} ({exc.__class__.__name__}).")
    allowed = {m._meta.label for m in allowed_models} | {model._meta.label}
    touched = {m._meta.label for m in collector.data} | {q.model._meta.label for q in collector.fast_deletes}
    extra = touched - allowed
    if extra or getattr(collector, "field_updates", None):
        raise Blocked("Cancelled: removing these rows would also delete or change " + ", ".join(sorted(extra or {"other records"})) + ".")
    total, per_model = collector.delete()
    return total, per_model.get(model._meta.label, 0)


def delete_items_only(items_qs):
    return delete_rows_only(list(items_qs), {SaleItem})[0]


def _drain(qs, allowed, budget, batch):
    """Deletes the rows of a queryset in small batches, up to a budget. Returns how many were deleted."""
    model = qs.model
    done = 0
    while done < budget:
        ids = list(qs.order_by("pk").values_list("pk", flat=True)[:min(batch, budget - done)])
        if not ids:
            break
        with transaction.atomic():
            _total, main = delete_rows_only(list(model.objects.filter(pk__in=ids)), allowed)
        done += main
    return done


def store_archive(shop, notice, category, records, dates, detail_count):
    """Saves a compressed copy of records, reads it back and checks it. Returns the archive."""
    gz = gzip.compress(to_json_lines(records), 6)
    archive = DataArchive.objects.create(
        shop=shop, notice=notice, category=category, period_from=min(dates), period_to=max(dates), rows_count=len(records),
        detail_count=detail_count, sha256=hashlib.sha256(gz).hexdigest(), size_bytes=len(gz), data=gz)
    try:
        stored = DataArchive.objects.get(pk=archive.pk)
        back = from_data_archive(stored)
        if (hashlib.sha256(bytes(stored.data)).hexdigest() != archive.sha256 or len(back) != len(records)
                or sum(len(r.get("items", [])) for r in back) != detail_count):
            raise Blocked("Cancelled: the saved copy did not match, so nothing was removed.")
    except Exception:
        archive.delete()
        raise
    return archive


# ---------------- bills ----------------
def eligible(shop, cutoff):
    """Old, settled bills that have not been archived yet. Bills with money still owed, or waiting for review, stay as they are."""
    qs = Sale.objects.filter(shop=shop, created_at__lt=cutoff, retention_marker__isnull=True)
    if _has(Sale, "amount_due"):
        qs = qs.filter(amount_due=0)
    if _has(Sale, "needs_review"):
        qs = qs.filter(needs_review=False)
    return qs


def bill_dicts(sales):
    """Every bill with its items and payments, as plain dictionaries."""
    sales = list(sales)
    ids = [s.pk for s in sales]
    if _has(Sale, "customer"):
        sales = list(Sale.objects.filter(pk__in=ids).select_related("customer").order_by("id"))
    items, payments = defaultdict(list), defaultdict(list)
    for it in SaleItem.objects.filter(sale_id__in=ids).order_by("id"):
        items[it.sale_id].append(_row(it))
    for p in Payment.objects.filter(sale_id__in=ids).order_by("id"):
        payments[p.sale_id].append(_row(p))
    out = []
    for s in sales:
        customer = getattr(s, "customer", None) if _has(Sale, "customer") else None
        out.append({"bill": _row(s),
                    "customer": {"id": customer.pk, "name": customer.name, "phone": customer.phone} if customer else None,
                    "items": items[s.pk], "payments": payments[s.pk]})
    return out


def archive_and_compact(shop, notice, sales, log):
    """Save a full copy of the bills, read it back and check it, then remove the item rows of those bills."""
    sales = list(sales)
    bills = bill_dicts(sales)
    gz = gzip.compress(to_json_lines(bills), 6)
    dates = [s.created_at.date() for s in sales]
    archive = BillArchive.objects.create(
        shop=shop, notice=notice, period_from=min(dates), period_to=max(dates), bills_count=len(bills),
        items_count=sum(len(b["items"]) for b in bills), sha256=hashlib.sha256(gz).hexdigest(), size_bytes=len(gz), data=gz)
    try:
        stored = BillArchive.objects.get(pk=archive.pk)          # read the copy back before anything is removed
        back = from_archive(stored)
        if (hashlib.sha256(bytes(stored.data)).hexdigest() != archive.sha256 or len(back) != len(bills)
                or sum(len(b["items"]) for b in back) != archive.items_count):
            raise Blocked("Cancelled: the saved copy of the bills did not match, so nothing was removed.")
        with transaction.atomic():
            deleted = delete_items_only(SaleItem.objects.filter(sale_id__in=[s.pk for s in sales]))
            ArchivedBill.objects.bulk_create([ArchivedBill(sale_id=s.pk, archive=archive) for s in sales])
    except Exception:
        archive.delete()          # nothing refers to it yet, so this removes only the unused copy
        raise
    log.bills_archived += len(bills)
    log.items_deleted += deleted
    log.archive = archive
    return archive


# ---------------- what each warned category does ----------------
class Plan:
    name = ""
    head = "record"
    date_field = "created_at"
    noun = "records"

    def available(self):
        return True

    def months(self, policy):
        raise NotImplementedError

    def cutoff(self, policy, now):
        return months_ago(now, self.months(policy))

    def eligible(self, shop, cutoff):
        raise NotImplementedError

    def detail(self, qs):
        return 0

    def batch_size(self):
        return _batch_rows()

    def max_per_run(self):
        return _max_rows()

    def archive(self, shop, notice, rows, log):
        raise NotImplementedError

    def archives_of(self, notice):
        return notice.data_archives.order_by("id")

    def read(self, archive):
        return from_data_archive(archive)

    def live_records(self, rows):
        raise NotImplementedError

    def csv_shape(self, record):
        return record

    def warning(self, shop, notice, months):
        raise NotImplementedError

    def subject(self, shop, notice):
        return f"{shop.name}: old {self.noun} will be archived on {notice.delete_after:%d %b %Y}"


class BillsPlan(Plan):
    name = "bills"
    head = "bill"
    noun = "bill details"

    def months(self, policy):
        return keep_months_of(policy)

    def eligible(self, shop, cutoff):
        return eligible(shop, cutoff)

    def detail(self, qs):
        return SaleItem.objects.filter(sale__in=qs).count()

    def batch_size(self):
        return BILL_BATCH

    def max_per_run(self):
        return getattr(settings, "RETENTION_MAX_BILLS_PER_RUN", 1000)

    def archive(self, shop, notice, rows, log):
        archive_and_compact(shop, notice, rows, log)
        return len(rows)

    def archives_of(self, notice):
        return notice.archives.order_by("id")

    def read(self, archive):
        return from_archive(archive)

    def live_records(self, rows):
        return bill_dicts(rows)

    def warning(self, shop, notice, months):
        return (
            f"Your data retention setting keeps bill details for {months} months.\n\n"
            f"On {notice.delete_after:%d %B %Y}, the item details of {notice.bills_count} bills dated {notice.oldest_bill:%d %b %Y} to "
            f"{notice.newest_bill:%d %b %Y} will be archived and removed from the live list.\n\n"
            f"What does NOT change: the bills' numbers, dates, totals and payments, your customers and what they owe, your stock "
            f"and your reports' totals. Bills with money still owed are never touched.\n\n"
            f"A full copy is saved first. Open the app: Menu > Data retention, to email yourself the bills, postpone the date, "
            f"or switch it off.")


class OrdersPlan(Plan):
    name = "orders"
    head = "order"
    noun = "online orders"
    date_field = "updated_at"

    def months(self, policy):
        return max(policy.orders_months, MIN_ORDER_MONTHS)

    def eligible(self, shop, cutoff):
        """Only finished orders. Never one that is pending, out for delivery, on hold, or linked to a bill with money owed."""
        qs = Order.objects.filter(shop=shop, status__in=FINISHED, updated_at__lt=cutoff, retention_hold=False)
        if _has(Sale, "amount_due"):
            qs = qs.exclude(sale__amount_due__gt=0)
        return qs

    def detail(self, qs):
        return OrderItem.objects.filter(order__in=qs).count()

    def live_records(self, rows):
        ids = [o.pk for o in rows]
        orders = list(Order.objects.filter(pk__in=ids).select_related("sale").order_by("id"))
        items, events = defaultdict(list), defaultdict(list)
        for it in OrderItem.objects.filter(order_id__in=ids).order_by("id"):
            items[it.order_id].append(_row(it))
        for ev in OrderEvent.objects.filter(order_id__in=ids).order_by("id"):
            events[ev.order_id].append(_row(ev))
        tracks = {t.order_id: _row(t) for t in DeliveryTrack.objects.filter(order_id__in=ids)}
        records = []
        for o in orders:
            row = _row(o)
            row.pop("delivery_pin", None)       # a delivery PIN is never copied into an archive
            records.append({"order": row, "sale_invoice": o.sale.invoice_number if o.sale_id else None,
                            "items": items[o.pk], "events": events[o.pk], "track": tracks.get(o.pk)})
        return records

    def archive(self, shop, notice, rows, log):
        rows = list(Order.objects.filter(pk__in=[o.pk for o in rows]).order_by("id"))
        records = self.live_records(rows)
        archive = store_archive(shop, notice, "orders", records, [o.updated_at.date() for o in rows],
                                sum(len(r["items"]) for r in records))
        try:
            with transaction.atomic():
                total, main = delete_rows_only(rows, {Order, OrderItem, OrderEvent, DeliveryTrack})
        except Exception:
            archive.delete()
            raise
        log.rows_archived += len(records)
        log.rows_deleted += main
        log.items_deleted += total - main
        return len(rows)

    def csv_shape(self, record):
        o = record["order"]
        return {"bill": o, "customer": {"name": o.get("customer_name", ""), "phone": o.get("customer_phone", "")},
                "items": record.get("items", []), "payments": []}

    def warning(self, shop, notice, months):
        return (
            f"Your data retention setting keeps finished online orders for {months} months.\n\n"
            f"On {notice.delete_after:%d %B %Y}, {notice.bills_count} delivered, cancelled or declined orders dated "
            f"{notice.oldest_bill:%d %b %Y} to {notice.newest_bill:%d %b %Y} will be archived and removed from the live list. "
            f"Your customers will no longer see these orders in their app.\n\n"
            f"What does NOT change: the bills made from delivered orders, your customers and what they owe, and your stock. "
            f"Orders that are pending, out for delivery, on hold, or linked to a bill with money still owed are never touched.\n\n"
            f"A full copy is saved first. Open the app: Menu > Data retention, to email yourself the orders, postpone the date, "
            f"or switch it off. To keep one order (for example a dispute or refund), open it in Online orders and switch on "
            f"'Keep this order'.")


class AuditPlan(Plan):
    name = "audit"
    head = "entry"
    noun = "change history"

    def model(self):
        try:
            return apps.get_model("shops", "AuditLog")
        except LookupError:
            return None

    def available(self):
        return self.model() is not None

    def months(self, policy):
        return max(policy.audit_months, MIN_AUDIT_MONTHS)

    def eligible(self, shop, cutoff):
        return self.model().objects.filter(shop=shop, created_at__lt=cutoff)

    def live_records(self, rows):
        return [{"row": _row(r)} for r in rows]

    def archive(self, shop, notice, rows, log):
        rows = list(rows)
        model = self.model()
        archive = store_archive(shop, notice, "audit", self.live_records(rows), [r.created_at.date() for r in rows], 0)
        try:
            with transaction.atomic():
                _total, main = delete_rows_only(rows, {model})
        except Exception:
            archive.delete()
            raise
        log.rows_archived += len(rows)
        log.rows_deleted += main
        return len(rows)

    def csv_shape(self, record):
        return {"bill": record["row"], "customer": None, "items": [], "payments": []}

    def warning(self, shop, notice, months):
        return (
            f"Your data retention setting keeps the change history (who changed prices, stock and credit limits) for {months} months.\n\n"
            f"On {notice.delete_after:%d %B %Y}, {notice.bills_count} entries dated {notice.oldest_bill:%d %b %Y} to "
            f"{notice.newest_bill:%d %b %Y} will be archived and removed from the live list. Nothing else changes.\n\n"
            f"A full copy is saved first. Open the app: Menu > Data retention, to email yourself the entries, postpone the date, "
            f"or switch it off.")


PLANS = {"bills": BillsPlan(), "orders": OrdersPlan(), "audit": AuditPlan()}


# ---------------- previews ----------------
def _notification_model():
    try:
        return apps.get_model("shops", "ShopNotification")
    except LookupError:
        return None


def _notification_qs(shop, policy, now):
    model = _notification_model()
    if model is None or not _has(model, "shop"):
        return None, None
    field = _date_field(model, ("created_at", "created", "timestamp", "date"))
    if not field:
        return model, None
    cutoff = days_ago(now, max(policy.notification_days, MIN_NOTIFICATION_DAYS))
    return model, model.objects.filter(shop=shop, **{f"{field}__lt": cutoff})


def preview(shop, now=None):
    """What the next cleanup would touch, without changing anything."""
    now = now or timezone.now()
    policy = policy_for(shop)
    bills = PLANS["bills"]
    cutoff = bills.cutoff(policy, now)
    qs = bills.eligible(shop, cutoff)
    agg = qs.aggregate(oldest=Min("created_at"), newest=Max("created_at"))
    _model, nqs = _notification_qs(shop, policy, now)
    orders, audit = PLANS["orders"], PLANS["audit"]
    return {
        "keep_months": keep_months_of(policy), "cutoff": cutoff, "bills": qs.count(), "items": SaleItem.objects.filter(sale__in=qs).count(),
        "oldest": agg["oldest"], "newest": agg["newest"],
        "notifications": nqs.count() if nqs is not None else 0,
        "audit": audit.eligible(shop, audit.cutoff(policy, now)).count() if audit.available() else None,
        "orders": orders.eligible(shop, orders.cutoff(policy, now)).count(),
    }


# ---------------- warning the shop ----------------
def owner_email(shop):
    owner = ShopMembership.objects.filter(shop=shop, role="owner", is_active=True).select_related("user").first()
    return owner.user.email if owner and owner.user.email else ""


def email_owner(shop, subject, body, attachments=()):
    to = owner_email(shop)
    if not to:
        return False
    try:
        message = EmailMessage(subject, body, to=[to])
        for name, content, mime in attachments:
            message.attach(name, content, mime)
        message.send(fail_silently=False)
        return True
    except Exception:
        logger.exception("Retention email failed")
        return False


def _announce(plan, shop, policy, now, today, log):
    if RetentionNotice.objects.filter(shop=shop, category=plan.name, status__in=[N.ANNOUNCED, N.POSTPONED]).exists():
        return None   # one warning at a time for each kind of data
    cutoff = plan.cutoff(policy, now)
    qs = plan.eligible(shop, cutoff)
    count = qs.count()
    if count == 0:
        return None
    agg = qs.aggregate(oldest=Min(plan.date_field), newest=Max(plan.date_field))
    notice = RetentionNotice.objects.create(
        shop=shop, category=plan.name, cutoff_at=cutoff, delete_after=today + timedelta(days=policy.notify_days),
        bills_count=count, items_count=plan.detail(qs), oldest_bill=agg["oldest"].date(), newest_bill=agg["newest"].date())
    email_owner(shop, plan.subject(shop, notice), plan.warning(shop, notice, plan.months(policy)))
    log.announced_bills += count
    log.notice = notice
    return notice


def _execute_due(plan, shop, policy, now, today, log):
    limit = plan.max_per_run()
    done = 0
    cutoff_now = plan.cutoff(policy, now)
    for notice in RetentionNotice.objects.filter(shop=shop, category=plan.name, status__in=[N.ANNOUNCED, N.POSTPONED],
                                                  delete_after__lte=today).order_by("created_at"):
        cutoff = min(notice.cutoff_at, cutoff_now)       # a shop that now keeps data longer is respected
        while done < limit:
            batch = list(plan.eligible(shop, cutoff).order_by("id")[:min(plan.batch_size(), limit - done)])
            if not batch:
                break
            done += plan.archive(shop, notice, batch, log)
            log.notice = notice
        if not plan.eligible(shop, cutoff).exists():
            notice.status, notice.done_at = N.DONE, now
            notice.save(update_fields=["status", "done_at"])


def _run_noticed(plan, shop, policy, now, today):
    """One warned category (bills, orders or audit) for one shop. Returns its log, or None if there is nothing to look at."""
    if not plan.available():
        return None
    log = RetentionLog(shop=shop, category=plan.name, run_on=today, started_at=now)
    try:
        _execute_due(plan, shop, policy, now, today, log)
        _announce(plan, shop, policy, now, today, log)
        archived = log.bills_archived + log.rows_archived
        log.outcome = "archived" if archived else "announced" if log.announced_bills else "nothing"
    except Blocked as exc:
        log.outcome, log.message = "blocked", str(exc)[:2000]
    except Exception as exc:
        logger.exception("Retention (%s) failed for shop %s", plan.name, shop.pk)
        log.outcome, log.message = "error", f"{type(exc).__name__}: {exc}"[:2000]
    log.finished_at = timezone.now()
    if log.outcome != "nothing" or plan.name == "bills":   # a quiet day for orders or audit is not worth a row
        log.save()
    return log


# ---------------- notifications ----------------
def _clean_notifications(shop, policy, now, today):
    """Plain deletion after N days. No archive and no warning."""
    model, qs = _notification_qs(shop, policy, now)
    if model is None:
        return None
    log = RetentionLog(shop=shop, category="notifications", run_on=today, started_at=now)
    if qs is None:
        log.outcome, log.message = "skipped", "The notification table has no date column, so nothing was deleted."
        log.finished_at = timezone.now()
        log.save()
        return log
    try:
        log.rows_deleted = _drain(qs, {model}, _max_rows(), _batch_rows())
        log.outcome = "cleaned" if log.rows_deleted else "nothing"
    except Blocked as exc:
        log.outcome, log.message = "blocked", str(exc)[:2000]
    except Exception as exc:
        logger.exception("Retention (notifications) failed for shop %s", shop.pk)
        log.outcome, log.message = "error", f"{type(exc).__name__}: {exc}"[:2000]
    log.finished_at = timezone.now()
    if log.outcome != "nothing":
        log.save()
    return log


# ---------------- the daily run of one shop, in the order: notifications, audit, orders, bills ----------------
def run_for_shop(shop, now=None, force=False):
    """The daily cleanup of one shop, on that shop's own settings. Does nothing if the shop has not switched retention on,
    or if it already ran today."""
    now = now or timezone.now()
    today = timezone.localdate(now)
    with transaction.atomic():
        policy = RetentionPolicy.objects.select_for_update().filter(shop=shop).first()
        if policy is None or not policy.enabled:
            return {"shop": shop.pk, "outcome": "off"}
        if policy.last_run_on == today and not force:
            return {"shop": shop.pk, "outcome": "already_ran_today"}
        policy.last_run_on = today          # the day is claimed first, so two callers can not both run it
        policy.save(update_fields=["last_run_on"])
    logs = {}
    if policy.clean_notifications:
        logs["notifications"] = _clean_notifications(shop, policy, now, today)
    if policy.clean_audit:
        logs["audit"] = _run_noticed(PLANS["audit"], shop, policy, now, today)
    if policy.clean_orders:
        logs["orders"] = _run_noticed(PLANS["orders"], shop, policy, now, today)
    if policy.clean_bills:
        logs["bills"] = _run_noticed(PLANS["bills"], shop, policy, now, today)
    logs = {k: v for k, v in logs.items() if v is not None}
    main = logs.get("bills") or next(iter(logs.values()), None)
    return {"shop": shop.pk, "outcome": main.outcome if main else "nothing",
            "announced_bills": main.announced_bills if main else 0, "bills_archived": main.bills_archived if main else 0,
            "items_deleted": main.items_deleted if main else 0,
            "categories": {k: {"outcome": v.outcome, "announced": v.announced_bills, "archived": v.bills_archived + v.rows_archived,
                               "deleted": v.rows_deleted} for k, v in logs.items()}}


# ---------------- platform-wide logs ----------------
def run_platform(now=None, force=False):
    """Deletes old rows of log tables that belong to no shop, and expired login sessions. Once a day."""
    now = now or timezone.now()
    today = timezone.localdate(now)
    if not force and RetentionLog.objects.filter(shop__isnull=True, category="logs", run_on=today).exists():
        return {"shop": None, "outcome": "already_ran_today"}
    log = RetentionLog.objects.create(shop=None, category="logs", run_on=today, started_at=now)
    notes = []
    try:
        for label, field, days in getattr(settings, "RETENTION_LOG_RULES", DEFAULT_LOG_RULES):
            try:
                model = apps.get_model(label)
            except LookupError:
                notes.append(f"{label}: not in this project, skipped")
                continue
            if not _has(model, field):
                notes.append(f"{label}: no column {field}, skipped")
                continue
            qs = model.objects.filter(**{f"{field}__lt": days_ago(now, days)})
            deleted = _drain(qs, {model}, _max_rows(), _batch_rows())
            log.rows_deleted += deleted
            notes.append(f"{label}: {deleted} older than {days} days deleted")
        try:
            call_command("clearsessions")      # expired login sessions (Django's own cleaner)
        except Exception:
            logger.exception("clearsessions failed")
        log.outcome = "cleaned" if log.rows_deleted else "nothing"
    except Blocked as exc:
        log.outcome = "blocked"
        notes.append(str(exc))
    except Exception as exc:
        logger.exception("Retention (platform logs) failed")
        log.outcome = "error"
        notes.append(f"{type(exc).__name__}: {exc}")
    log.message = "\n".join(notes)[:2000]
    log.finished_at = timezone.now()
    log.save()
    return {"shop": None, "category": "logs", "outcome": log.outcome, "rows_deleted": log.rows_deleted}


def run_all(now=None, force=False):
    results = []
    for policy in RetentionPolicy.objects.filter(enabled=True).select_related("shop"):
        results.append(run_for_shop(policy.shop, now=now, force=force))
    results.append(run_platform(now=now, force=force))
    return results


# ---------------- exports for the owner ----------------
def csv_zip_bytes(records, head="bill"):
    """One spreadsheet row per detail line (or per record with none), zipped so that it opens on a phone and stays small."""
    cols, rows = [], []

    def add(row):
        for k in row:
            if k not in cols:
                cols.append(k)
        rows.append(row)

    for b in records:
        base = {f"{head}_{k}": v for k, v in b["bill"].items()}
        base["customer_name"] = (b.get("customer") or {}).get("name", "")
        base["customer_phone"] = (b.get("customer") or {}).get("phone", "")
        base["payments"] = "; ".join(f"{p.get('method')}={p.get('amount')}" for p in b.get("payments", []))
        for it in b.get("items") or [{}]:
            add({**base, **{f"item_{k}": v for k, v in it.items()}})
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=cols)
    writer.writeheader()
    for r in rows:
        writer.writerow({k: "" if r.get(k) is None else str(r[k]) for k in cols})
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr({"bill": "bills", "order": "orders", "entry": "entries"}.get(head, head + "s") + ".csv",
                   ("\ufeff" + buf.getvalue()).encode("utf-8"))
    return out.getvalue()


def records_of_notice(notice):
    """Everything a warning covers: what is already archived, and what is still live. Returns (records for a spreadsheet, head)."""
    plan = PLANS[notice.category]
    records = []
    for archive in plan.archives_of(notice):
        records.extend(plan.read(archive))
    policy = policy_for(notice.shop)
    cutoff = min(notice.cutoff_at, plan.cutoff(policy, timezone.now()))
    cap = getattr(settings, "RETENTION_EMAIL_MAX_BILLS", 5000)
    live = list(plan.eligible(notice.shop, cutoff).order_by("id")[:max(0, cap - len(records))])
    records.extend(plan.live_records(live))
    return [plan.csv_shape(r) for r in records], plan.head