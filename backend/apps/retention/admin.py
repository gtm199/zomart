from django.contrib import admin

from .models import ArchivedBill, BillArchive, DataArchive, RetentionLog, RetentionNotice, RetentionPolicy


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
    list_display = ("shop", "enabled", "clean_bills", "keep_months", "clean_notifications", "notification_days",
                    "clean_audit", "audit_months", "clean_orders", "orders_months", "last_run_on")
    list_filter = ("enabled",)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(RetentionLog)
class RetentionLogAdmin(ReadOnly):
    list_display = ("run_on", "shop", "category", "outcome", "announced_bills", "bills_archived", "items_deleted",
                    "rows_archived", "rows_deleted", "finished_at")
    list_filter = ("category", "outcome")


@admin.register(RetentionNotice)
class RetentionNoticeAdmin(ReadOnly):
    list_display = ("shop", "category", "status", "delete_after", "bills_count", "items_count", "oldest_bill", "newest_bill")
    list_filter = ("category", "status")


@admin.register(BillArchive)
class BillArchiveAdmin(ReadOnly):
    list_display = ("shop", "period_from", "period_to", "bills_count", "items_count", "size_bytes", "created_at")
    exclude = ("data",)


@admin.register(DataArchive)
class DataArchiveAdmin(ReadOnly):
    list_display = ("shop", "category", "period_from", "period_to", "rows_count", "detail_count", "size_bytes", "created_at")
    list_filter = ("category",)
    exclude = ("data",)


@admin.register(ArchivedBill)
class ArchivedBillAdmin(ReadOnly):
    list_display = ("sale", "archive", "archived_at")