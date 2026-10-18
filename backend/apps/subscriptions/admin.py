from datetime import timedelta

from django.contrib import admin, messages
from django.shortcuts import redirect, render
from django.urls import path
from django.utils import timezone

from services import payment_service, subscription_service
from services.exceptions import BusinessRuleError

from .models import BankCredit, PaymentSettings, ShopSubscription, SubscriptionPlan

admin.site.register(SubscriptionPlan)


class ExpiryFilter(admin.SimpleListFilter):
    title = "expiry"
    parameter_name = "expiry"

    def lookups(self, request, model_admin):
        return [("expired", "Already expired"), ("week", "Expires within 7 days"), ("month", "Expires within 30 days")]

    def queryset(self, request, qs):
        today = timezone.localdate()
        if self.value() == "expired":
            return qs.filter(expires_on__lt=today)
        if self.value() == "week":
            return qs.filter(expires_on__gte=today, expires_on__lte=today + timedelta(days=7))
        if self.value() == "month":
            return qs.filter(expires_on__gte=today, expires_on__lte=today + timedelta(days=30))
        return qs


@admin.register(ShopSubscription)
class ShopSubscriptionAdmin(admin.ModelAdmin):
    list_display = ("shop", "plan", "status", "starts_on", "expires_on", "days_left", "grace_days")
    list_filter = (ExpiryFilter, "status", "plan")
    search_fields = ("shop__name", "shop__phone")
    ordering = ("expires_on",)

    @admin.display(description="Days left")
    def days_left(self, obj):
        return subscription_service.days_left(obj)


@admin.register(PaymentSettings)
class PaymentSettingsAdmin(admin.ModelAdmin):
    """One row only: your UPI details and QR image, shown to shops in the app."""
    list_display = ("upi_id", "payee_name", "reminder_days")

    def has_add_permission(self, request):
        return not PaymentSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(BankCredit)
class BankCreditAdmin(admin.ModelAdmin):
    change_list_template = "admin/subscriptions/bankcredit/change_list.html"
    list_display = ("reference", "credit_date", "amount", "status", "shop", "months", "matched_by", "new_expiry", "review_note")
    list_editable = ("shop", "months")
    list_filter = ("status", "matched_by")
    search_fields = ("reference", "narration", "shop__name")
    ordering = ("status", "-credit_date")
    actions = ["confirm_and_renew", "ignore"]

    @admin.action(description="Confirm and renew the shop named on each selected row")
    def confirm_and_renew(self, request, queryset):
        done = 0
        for credit in queryset:
            try:
                payment_service.confirm_manually(credit, request.user)
                done += 1
            except BusinessRuleError as exc:
                self.message_user(request, f"{credit.reference}: {exc.message}", messages.WARNING)
        self.message_user(request, f"{done} shop(s) renewed.")

    @admin.action(description="Ignore (not a subscription payment)")
    def ignore(self, request, queryset):
        n = queryset.filter(status=BankCredit.Status.REVIEW).update(
            status=BankCredit.Status.IGNORED, processed_by=request.user, processed_at=timezone.now())
        self.message_user(request, f"{n} payment(s) ignored.")

    def get_urls(self):
        extra = [path("upload/", self.admin_site.admin_view(self.upload_view), name="subscriptions_upload")]
        return extra + super().get_urls()

    def upload_view(self, request):
        ctx = dict(self.admin_site.each_context(request), title="Upload bank statement")
        rows = request.session.get("bank_rows")
        if request.method == "POST":
            if request.FILES.get("file"):
                try:
                    rows = payment_service.read_rows(request.FILES["file"])
                except ImportError:
                    self.message_user(request, "Excel files need openpyxl: pip install openpyxl", messages.ERROR)
                    return redirect("admin:subscriptions_upload")
                except Exception as exc:
                    self.message_user(request, f"Could not read the file: {exc}", messages.ERROR)
                    return redirect("admin:subscriptions_upload")
                request.session["bank_rows"] = rows
                posted = None
            else:
                posted = {k: request.POST.get(f"map_{k}") for k in payment_service.FIELDS}
            if not rows:
                self.message_user(request, "Upload the statement file first.", messages.ERROR)
                return redirect("admin:subscriptions_upload")
            header_index = payment_service.find_header(rows)
            headers = rows[header_index]
            if posted and all(v is not None for v in posted.values()):
                mapping = {k: (int(v) if v != "" else None) for k, v in posted.items()}
            else:
                mapping = payment_service.guess_columns(headers)
            credits = payment_service.parse_credits(rows, header_index, mapping)
            if request.POST.get("apply"):
                results = payment_service.process(credits, request.user, apply=True)
                renewed = sum(r["outcome"] == "renew" for r in results)
                review = sum(r["outcome"] == "review" for r in results)
                request.session.pop("bank_rows", None)
                self.message_user(request, f"{renewed} shop(s) renewed. {review} payment(s) need your decision.")
                return redirect("admin:subscriptions_bankcredit_changelist")
            results = payment_service.process(credits, request.user, apply=False)
            ctx.update(previewed=True, results=results, header_list=list(enumerate(headers)),
                       choices=[(f, mapping.get(f)) for f in payment_service.FIELDS],
                       counts={"renew": sum(r["outcome"] == "renew" for r in results),
                               "review": sum(r["outcome"] == "review" for r in results),
                               "skipped": sum(r["outcome"] in ("seen", "duplicate_in_file") for r in results)})
        return render(request, "admin/subscriptions/upload.html", ctx)
