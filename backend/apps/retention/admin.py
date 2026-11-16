from django.contrib import admin, messages
from django.template.response import TemplateResponse

from services import retention_admin_service
from services.exceptions import BusinessRuleError

from .models import ArchivedBill, BillArchive, DataArchive, RetentionLog, RetentionNotice, RetentionPolicy

CONFIRM_WORD = "DELETE"


class ReadOnly(admin.ModelAdmin):
    """Nothing here is added or edited by hand: it is the record of what the daily cleanup did.
    Deleting is possible only through the "Delete permanently" action, for platform superusers, with the safety rules
    of services/retention_admin_service.py (never the shops' apps)."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False   # Django's plain delete would skip the safety rules; use the action below


@admin.action(description="Delete permanently (superuser only, with safety checks)")
def delete_permanently(modeladmin, request, queryset):
    if not request.user.is_superuser:
        modeladmin.message_user(request, "Only a platform superuser can delete retention records.", messages.ERROR)
        return None
    model = queryset.model
    objects = list(queryset)
    if request.POST.get("apply") == "1":
        if request.POST.get("confirm_word", "").strip() != CONFIRM_WORD:
            modeladmin.message_user(request, f'Nothing was deleted: type {CONFIRM_WORD} to confirm.', messages.WARNING)
            return None
        done, refused = [], []
        for obj in objects:
            try:
                done.append(retention_admin_service.DELETERS[model](obj, request.user))
            except BusinessRuleError as exc:
                refused.append(f"{retention_admin_service.describe(obj)} - kept: {exc.message}")
        if done:
            modeladmin.message_user(request, f"Deleted {len(done)}: " + "; ".join(done), messages.SUCCESS)
        for line in refused:
            modeladmin.message_user(request, line, messages.ERROR)
        return None
    context = {
        **modeladmin.admin_site.each_context(request),
        "title": "Delete permanently?",
        "objects": [retention_admin_service.describe(o) for o in objects],
        "ids": [o.pk for o in objects],
        "warning": retention_admin_service.WARNINGS.get(model, ""),
        "confirm_word": CONFIRM_WORD,
        "action": "delete_permanently",
        "opts": model._meta,
        "action_checkbox_name": admin.helpers.ACTION_CHECKBOX_NAME,
    }
    return TemplateResponse(request, "admin/retention/confirm_delete.html", context)


class SuperuserDeleteMixin:
    actions = [delete_permanently]

    def get_actions(self, request):
        actions = super().get_actions(request)
        if not request.user.is_superuser:
            actions.pop("delete_permanently", None)
        return actions


@admin.register(RetentionPolicy)
class RetentionPolicyAdmin(SuperuserDeleteMixin, admin.ModelAdmin):
    list_display = ("shop", "enabled", "clean_bills", "keep_months", "clean_notifications", "notification_days",
                    "clean_audit", "audit_months", "clean_orders", "orders_months", "last_run_on")
    list_filter = ("enabled",)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(RetentionLog)
class RetentionLogAdmin(SuperuserDeleteMixin, ReadOnly):
    list_display = ("run_on", "shop", "category", "outcome", "announced_bills", "bills_archived", "items_deleted",
                    "rows_archived", "rows_deleted", "finished_at")
    list_filter = ("category", "outcome")


@admin.register(RetentionNotice)
class RetentionNoticeAdmin(SuperuserDeleteMixin, ReadOnly):
    list_display = ("shop", "category", "status", "delete_after", "bills_count", "items_count", "oldest_bill", "newest_bill")
    list_filter = ("category", "status")


@admin.register(BillArchive)
class BillArchiveAdmin(SuperuserDeleteMixin, ReadOnly):
    list_display = ("id", "shop", "period_from", "period_to", "bills_count", "items_count", "size_bytes", "created_at")
    exclude = ("data",)


@admin.register(DataArchive)
class DataArchiveAdmin(SuperuserDeleteMixin, ReadOnly):
    list_display = ("id", "shop", "category", "period_from", "period_to", "rows_count", "detail_count", "size_bytes", "created_at")
    list_filter = ("category",)
    exclude = ("data",)


@admin.register(ArchivedBill)
class ArchivedBillAdmin(SuperuserDeleteMixin, ReadOnly):
    list_display = ("sale", "archive", "archived_at", "archive_deleted_at")
    list_select_related = ("sale__shop", "archive__shop")
