from django.contrib import admin

from .models import ArchivedBill, BillArchive, RetentionLog, RetentionNotice, RetentionPolicy


class ReadOnly(admin.ModelAdmin):
    """Nothing here is edited or deleted by hand: it is the record of what the daily cleanup did."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(RetentionPolicy)
class RetentionPolicyAdmin(admin.ModelAdmin):
    list_display = ("shop", "enabled", "keep_months", "notify_days", "last_run_on")
    list_filter = ("enabled",)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(RetentionLog)
class RetentionLogAdmin(ReadOnly):
    list_display = ("run_on", "shop", "outcome", "announced_bills", "bills_archived", "items_deleted", "finished_at")
    list_filter = ("outcome",)


@admin.register(RetentionNotice)
class RetentionNoticeAdmin(ReadOnly):
    list_display = ("shop", "status", "delete_after", "bills_count", "items_count", "oldest_bill", "newest_bill")
    list_filter = ("status",)


@admin.register(BillArchive)
class BillArchiveAdmin(ReadOnly):
    list_display = ("shop", "period_from", "period_to", "bills_count", "items_count", "size_bytes", "created_at")
    exclude = ("data",)


@admin.register(ArchivedBill)
class ArchivedBillAdmin(ReadOnly):
    list_display = ("sale", "archive", "archived_at")