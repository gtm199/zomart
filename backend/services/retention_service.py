"""Retention of old bill detail, built so that accounting and customer credit can not be hurt:

* Only the ITEM rows of old bills are removed. The bill itself (number, date, customer, totals), its payments, the customer
  ledger, customer balances, stock movements and inventory are never touched.
* Bills that still have money owed on them, or are waiting for review, are never touched.
* Nothing is removed before a warning has been given for the number of days the shop chose, and before a full copy of the
  bills has been saved and read back.
* Before every removal the database is asked what else would go with it. If anything other than item rows would be deleted
  (a cascade), the removal is cancelled and written to the log.
* A shop is processed on its own settings, once a day.
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

from django.conf import settings
from django.core.exceptions import FieldDoesNotExist
from django.core.mail import EmailMessage
from django.db import router, transaction
from django.db.models import Max, Min
from django.db.models.deletion import Collector, ProtectedError, RestrictedError
from django.utils import timezone

from apps.retention.models import ArchivedBill, BillArchive, RetentionLog, RetentionNotice, RetentionPolicy
from apps.sales.models import Payment, Sale, SaleItem
from apps.shops.models import ShopMembership

logger = logging.getLogger(__name__)

MIN_KEEP_MONTHS = 12
BATCH = 300
MAX_POSTPONES = 3
N = RetentionNotice.Status


class Blocked(Exception):
    """A removal was cancelled because it would have deleted more than item rows, or the archive could not be verified."""


def _has(model, name):
    try:
        model._meta.get_field(name)
        return True
    except FieldDoesNotExist:
        return False


def months_ago(now, months):
    total = now.year * 12 + (now.month - 1) - months
    year, month = divmod(total, 12)
    feb = 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28
    day = min(now.day, [31, feb, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month])
    return now.replace(year=year, month=month + 1, day=day)


def policy_for(shop):
    policy, _ = RetentionPolicy.objects.get_or_create(shop=shop)
    return policy


def keep_months_of(policy):
    return max(policy.keep_months, MIN_KEEP_MONTHS)


# ---------------- which bills may be touched ----------------
def eligible(shop, cutoff):
    """Old, settled bills that have not been archived yet. Bills with money still owed, or waiting for review, stay as they are."""
    qs = Sale.objects.filter(shop=shop, created_at__lt=cutoff, retention_marker__isnull=True)
    if _has(Sale, "amount_due"):
        qs = qs.filter(amount_due=0)
    if _has(Sale, "needs_review"):
        qs = qs.filter(needs_review=False)
    return qs


def preview(shop, now=None):
    """What the next cleanup would announce, without changing anything."""
    now = now or timezone.now()
    policy = policy_for(shop)
    cutoff = months_ago(now, keep_months_of(policy))
    qs = eligible(shop, cutoff)
    agg = qs.aggregate(oldest=Min("created_at"), newest=Max("created_at"))
    return {"keep_months": keep_months_of(policy), "cutoff": cutoff, "bills": qs.count(),
            "items": SaleItem.objects.filter(sale__in=qs).count(),
            "oldest": agg["oldest"], "newest": agg["newest"]}


# ---------------- a complete copy of the bills ----------------
def _row(obj):
    return {(f.attname if f.is_relation else f.name): getattr(obj, f.attname) for f in obj._meta.concrete_fields}


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


def to_json_lines(bills):
    return "\n".join(json.dumps(b, default=str, separators=(",", ":")) for b in bills).encode()


def from_archive(archive):
    data = gzip.decompress(bytes(archive.data)).decode()
    return [json.loads(line) for line in data.splitlines() if line.strip()]


def csv_zip_bytes(bills):
    """One spreadsheet row per item (or per bill with no items), zipped so that it opens on a phone and stays small."""
    cols, rows = [], []

    def add(row):
        for k in row:
            if k not in cols:
                cols.append(k)
        rows.append(row)

    for b in bills:
        base = {f"bill_{k}": v for k, v in b["bill"].items()}
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
        z.writestr("bills.csv", ("\ufeff" + buf.getvalue()).encode("utf-8"))
    return out.getvalue()


# ---------------- removing item rows, and nothing else ----------------
def delete_items_only(items_qs):
    """Deletes the given SaleItem rows after asking the database what would be deleted with them. Raises Blocked if
    anything else would go (or be changed) because of a cascade, or if something protects these rows."""
    collector = Collector(using=router.db_for_write(SaleItem))
    try:
        collector.collect(list(items_qs))
    except (ProtectedError, RestrictedError) as exc:
        raise Blocked(f"Cancelled: something depends on these bill items ({exc.__class__.__name__}).")
    touched = {m._meta.label for m in collector.data} | {q.model._meta.label for q in collector.fast_deletes}
    touched.discard(SaleItem._meta.label)
    if touched or getattr(collector, "field_updates", None):
        raise Blocked("Cancelled: removing the item rows would also delete or change " + ", ".join(sorted(touched or {"other records"})) + ".")
    total, _per_model = collector.delete()
    return total


def archive_and_compact(shop, notice, sales, log):
    """Save a full copy, read it back and check it, then remove the item rows of those bills."""
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


def _announce(shop, policy, now, today, log):
    if RetentionNotice.objects.filter(shop=shop, status__in=[N.ANNOUNCED, N.POSTPONED]).exists():
        return None   # one warning at a time
    cutoff = months_ago(now, keep_months_of(policy))
    qs = eligible(shop, cutoff)
    count = qs.count()
    if count == 0:
        return None
    agg = qs.aggregate(oldest=Min("created_at"), newest=Max("created_at"))
    notice = RetentionNotice.objects.create(
        shop=shop, cutoff_at=cutoff, delete_after=today + timedelta(days=policy.notify_days), bills_count=count,
        items_count=SaleItem.objects.filter(sale__in=qs).count(), oldest_bill=agg["oldest"].date(), newest_bill=agg["newest"].date())
    email_owner(
        shop, f"{shop.name}: old bill details will be archived on {notice.delete_after:%d %b %Y}",
        f"Your data retention setting keeps bill details for {keep_months_of(policy)} months.\n\n"
        f"On {notice.delete_after:%d %B %Y}, the item details of {count} bills dated {notice.oldest_bill:%d %b %Y} to "
        f"{notice.newest_bill:%d %b %Y} will be archived and removed from the live list.\n\n"
        f"What does NOT change: the bills' numbers, dates, totals and payments, your customers and what they owe, your stock "
        f"and your reports' totals.\n\n"
        f"A full copy is saved first. Open the app: Menu > Data retention, to email yourself the bills, postpone the date, "
        f"or switch retention off.")
    log.announced_bills += count
    log.notice = notice
    return notice


# ---------------- carrying it out ----------------
def _execute_due(shop, policy, now, today, log):
    limit = getattr(settings, "RETENTION_MAX_BILLS_PER_RUN", 1000)
    cutoff_now = months_ago(now, keep_months_of(policy))
    for notice in RetentionNotice.objects.filter(shop=shop, status__in=[N.ANNOUNCED, N.POSTPONED], delete_after__lte=today).order_by("created_at"):
        cutoff = min(notice.cutoff_at, cutoff_now)       # a shop that now keeps bills longer is respected
        while log.bills_archived < limit:
            batch = list(eligible(shop, cutoff).order_by("id")[:min(BATCH, limit - log.bills_archived)])
            if not batch:
                break
            archive_and_compact(shop, notice, batch, log)
            log.notice = notice
        if not eligible(shop, cutoff).exists():
            notice.status, notice.done_at = N.DONE, now
            notice.save(update_fields=["status", "done_at"])


def run_for_shop(shop, now=None, force=False):
    """The daily cleanup of one shop, on that shop's own settings. Does nothing if the shop has not switched it on, or if it
    already ran today."""
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
    log = RetentionLog.objects.create(shop=shop, run_on=today, started_at=now)
    try:
        _execute_due(shop, policy, now, today, log)
        _announce(shop, policy, now, today, log)
        log.outcome = "archived" if log.bills_archived else "announced" if log.announced_bills else "nothing"
    except Blocked as exc:
        log.outcome, log.message = "blocked", str(exc)[:2000]
    except Exception as exc:
        logger.exception("Retention run failed for shop %s", shop.pk)
        log.outcome, log.message = "error", f"{type(exc).__name__}: {exc}"[:2000]
    log.finished_at = timezone.now()
    log.save()
    return {"shop": shop.pk, "outcome": log.outcome, "announced_bills": log.announced_bills,
            "bills_archived": log.bills_archived, "items_deleted": log.items_deleted}


def run_all(now=None, force=False):
    results = []
    for policy in RetentionPolicy.objects.filter(enabled=True).select_related("shop"):
        results.append(run_for_shop(policy.shop, now=now, force=force))
    return results


# ---------------- exports for the owner ----------------
def bills_of_notice(notice):
    """Bills covered by a warning: the ones already archived, and the ones still live."""
    bills = []
    for archive in notice.archives.order_by("id"):
        bills.extend(from_archive(archive))
    cutoff = min(notice.cutoff_at, months_ago(timezone.now(), keep_months_of(policy_for(notice.shop))))
    cap = getattr(settings, "RETENTION_EMAIL_MAX_BILLS", 5000)
    live = list(eligible(notice.shop, cutoff).order_by("id")[:max(0, cap - len(bills))])
    bills.extend(bill_dicts(live))
    return bills