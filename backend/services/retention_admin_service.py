"""Permanent deletes in the retention area. Platform admin (superuser) only, from the Django admin - never from the apps.

What can be deleted, and what always stays:
  bill archive        the compressed copy of old bills' item details. The bills themselves (number, date, totals,
                      payments, GST totals) always stay. Each bill keeps its "archived" marker (now without an archive),
                      so the daily cleanup never archives it again and it still cannot be returned.
  one archived bill   that one bill's item details are removed from its archive copy (the copy is rewritten and
                      checked). If nothing is left, the archive itself is deleted.
  data archive        archived online orders or change history (the only copy left).
  notice / log        the warning or the cleanup record. Archives and logs that refer to a notice are kept.
  policy              resets the shop's retention settings to the defaults (switched off).

Never deleted, whatever is asked: bill item details of bills still inside the shop's minimum period - for GST shops
(now or in the past) that is gst_min_months() (default 72), covering tax invoices, bills of supply and bills with
credit notes. Every delete is written to the retention log, with who did it.
"""
import calendar
import gzip
import hashlib
import json
from datetime import date

from django.db import transaction
from django.utils import timezone

from apps.retention.models import ArchivedBill, BillArchive, DataArchive, RetentionLog, RetentionNotice, RetentionPolicy
from apps.sales.models import CreditNote, Sale
from services import retention_service as rs
from services.exceptions import BusinessRuleError

GST_DOCS = ("tax_invoice", "bill_of_supply")


# ---------------- the guard ----------------
def check_bills_may_go(shop, sale_ids, now=None):
    """Raises BusinessRuleError when any of these bills is still inside the period its details must be kept."""
    now = now or timezone.now()
    sales = Sale.objects.filter(pk__in=sale_ids)
    keep = rs.min_keep_months(shop)
    cutoff = rs.months_ago(now, keep)
    young = sales.filter(created_at__gte=cutoff)
    if young.exists():
        newest = timezone.localtime(young.order_by("-created_at").first().created_at).date()
        raise BusinessRuleError(
            f"{young.count()} bill(s) in it are newer than the minimum of {keep} months for this shop "
            f"(newest {newest:%d %b %Y}). They cannot be deleted before {_plus_months(newest, keep):%d %b %Y}.",
            "inside_minimum_period")
    gst_cut = rs.months_ago(now, rs.gst_min_months())
    if sales.filter(document_type__in=GST_DOCS, created_at__gte=gst_cut).exists() or \
            CreditNote.objects.filter(sale__in=sales, created_at__gte=gst_cut).exists():
        raise BusinessRuleError(f"It holds GST invoices or credit notes from the last {rs.gst_min_months()} months, "
                                "which must be kept.", "gst_record_retention")


def _plus_months(day, months):
    total = day.year * 12 + (day.month - 1) + months
    year, month = divmod(total, 12)
    return date(year, month + 1, min(day.day, calendar.monthrange(year, month + 1)[1]))


def _log(shop, user, message, category="admin", rows=0):
    now = timezone.now()
    RetentionLog.objects.create(shop=shop, category=category[:15], run_on=timezone.localdate(), started_at=now,
                                finished_at=now, outcome="admin_deleted", rows_deleted=rows,
                                message=f"{getattr(user, 'username', 'admin')}: {message}"[:2000])


def _require_superuser(user):
    if not (user and user.is_superuser):
        raise BusinessRuleError("Only a platform superuser can delete retention records.", "superuser_only", 403)


# ---------------- deletes ----------------
@transaction.atomic
def delete_bill_archive(archive, user):
    _require_superuser(user)
    archive = BillArchive.objects.select_for_update().get(pk=archive.pk)
    sale_ids = list(ArchivedBill.objects.filter(archive=archive).values_list("sale_id", flat=True))
    check_bills_may_go(archive.shop, sale_ids)
    label = f"bill archive #{archive.pk} ({archive.period_from} to {archive.period_to}, {archive.bills_count} bills, " \
            f"{archive.items_count} item lines)"
    ArchivedBill.objects.filter(archive=archive).update(archive=None, archive_deleted_at=timezone.now())
    RetentionLog.objects.filter(archive=archive).update(archive=None)
    shop = archive.shop
    archive.delete()
    _log(shop, user, f"deleted {label}. The bills themselves are kept.", "bills", len(sale_ids))
    return label


@transaction.atomic
def delete_archived_bill(marker, user):
    """Removes one bill's item details from its archive copy; the bill and its marker stay."""
    _require_superuser(user)
    marker = ArchivedBill.objects.select_for_update().select_related("sale", "archive").get(pk=marker.pk)
    shop = marker.sale.shop
    check_bills_may_go(shop, [marker.sale_id])
    label = f"archived details of bill {marker.sale.invoice_number}"
    archive = marker.archive
    marker.archive, marker.archive_deleted_at = None, timezone.now()
    marker.save(update_fields=["archive", "archive_deleted_at"])
    if archive is not None:
        archive = BillArchive.objects.select_for_update().get(pk=archive.pk)
        kept = [b for b in rs.from_archive(archive) if b["bill"]["id"] != marker.sale_id]
        if not kept:
            RetentionLog.objects.filter(archive=archive).update(archive=None)
            archive.delete()
        else:
            gz = gzip.compress(rs.to_json_lines(kept), 6)
            days = [str(b["bill"]["created_at"])[:10] for b in kept]
            archive.data, archive.size_bytes = gz, len(gz)
            archive.sha256 = hashlib.sha256(gz).hexdigest()
            archive.bills_count, archive.items_count = len(kept), sum(len(b["items"]) for b in kept)
            archive.period_from, archive.period_to = date.fromisoformat(min(days)), date.fromisoformat(max(days))
            archive.save()
            back = rs.from_archive(BillArchive.objects.get(pk=archive.pk))   # read the new copy back and check it
            if len(back) != len(kept) or sum(len(b["items"]) for b in back) != archive.items_count:
                raise BusinessRuleError("The rewritten archive did not check out, so nothing was changed.", "archive_check_failed")
    _log(shop, user, f"deleted {label}. The bill itself is kept.", "bills", 1)
    return label


@transaction.atomic
def delete_data_archive(archive, user):
    _require_superuser(user)
    label = f"{archive.category} archive #{archive.pk} ({archive.period_from} to {archive.period_to}, {archive.rows_count} records)"
    shop = archive.shop
    DataArchive.objects.filter(pk=archive.pk).delete()
    _log(shop, user, f"deleted {label}. This was the only copy.", archive.category, archive.rows_count)
    return label


@transaction.atomic
def delete_notice(notice, user):
    _require_superuser(user)
    label = f"{notice.category} warning #{notice.pk} ({notice.status}, {notice.bills_count} records)"
    BillArchive.objects.filter(notice=notice).update(notice=None)      # archives are kept
    DataArchive.objects.filter(notice=notice).update(notice=None)
    RetentionLog.objects.filter(notice=notice).update(notice=None)     # logs are kept
    shop = notice.shop
    RetentionNotice.objects.filter(pk=notice.pk).delete()
    _log(shop, user, f"deleted {label}. A waiting cleanup is simply announced again by the next run.", notice.category)
    return label


@transaction.atomic
def delete_log(log, user):
    _require_superuser(user)
    label = f"log #{log.pk} ({log.run_on}, {log.category}, {log.outcome})"
    RetentionLog.objects.filter(pk=log.pk).delete()
    return label


@transaction.atomic
def reset_policy(policy, user):
    _require_superuser(user)
    shop = policy.shop
    RetentionNotice.objects.filter(shop=shop, status__in=[RetentionNotice.Status.ANNOUNCED, RetentionNotice.Status.POSTPONED]) \
        .update(status=RetentionNotice.Status.CANCELLED)
    RetentionPolicy.objects.filter(pk=policy.pk).delete()
    _log(shop, user, "deleted the retention settings (back to the defaults: switched off). Waiting warnings were cancelled.", "policy")
    return f"retention settings of {shop}"


def describe(obj):
    """One line for the confirmation page."""
    if isinstance(obj, BillArchive):
        return f"Bill archive #{obj.pk}: {obj.shop} · {obj.period_from} to {obj.period_to} · {obj.bills_count} bills, {obj.items_count} item lines"
    if isinstance(obj, ArchivedBill):
        return f"Archived details of bill {obj.sale.invoice_number} ({obj.sale.shop})"
    if isinstance(obj, DataArchive):
        return f"{obj.category.title()} archive #{obj.pk}: {obj.shop} · {obj.period_from} to {obj.period_to} · {obj.rows_count} records"
    if isinstance(obj, RetentionNotice):
        return f"Warning #{obj.pk}: {obj.shop} · {obj.category} · {obj.status}"
    if isinstance(obj, RetentionLog):
        return f"Log #{obj.pk}: {obj.shop or 'platform'} · {obj.run_on} · {obj.category} · {obj.outcome}"
    if isinstance(obj, RetentionPolicy):
        return f"Retention settings of {obj.shop}"
    return str(obj)


DELETERS = {BillArchive: delete_bill_archive, ArchivedBill: delete_archived_bill, DataArchive: delete_data_archive,
            RetentionNotice: delete_notice, RetentionLog: delete_log, RetentionPolicy: reset_policy}

WARNINGS = {
    BillArchive: "The archived item details are the ONLY copy left. Email them to the shop owner first if they may be needed. "
                 "The bills themselves (numbers, totals, payments, GST totals) are kept.",
    ArchivedBill: "The item details of these bills are removed from their archive copy for good. The bills themselves are kept.",
    DataArchive: "These archived orders / change-history entries are the ONLY copy left and cannot be brought back.",
    RetentionNotice: "Archives and logs that belong to these warnings are kept. A waiting cleanup is announced again by the next run.",
    RetentionLog: "Only the record of what the cleanup did is removed.",
    RetentionPolicy: "The shop's retention settings go back to the defaults (switched off). Waiting warnings are cancelled.",
}
