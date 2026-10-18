from datetime import timedelta

from django.contrib import admin, messages
from django.db.models import Count, Max, Q
from django.utils import timezone

from services import subscription_service

from .models import Shop, ShopMembership, ShopNotification


class QuietFilter(admin.SimpleListFilter):
    title = "activity"
    parameter_name = "activity"

    def lookups(self, request, model_admin):
        return [("quiet", "No bills in the last 7 days"), ("never", "Never made a bill")]

    def queryset(self, request, qs):
        if self.value() == "quiet":
            return qs.filter(bills_7d=0)
        if self.value() == "never":
            return qs.filter(last_bill__isnull=True)
        return qs


@admin.register(Shop)
class ShopAdmin(admin.ModelAdmin):
    list_display = ("name", "city", "phone", "is_approved", "plan", "expires", "bills_7d", "last_bill", "payment_code")
    list_filter = ("is_approved", "is_active", QuietFilter)
    search_fields = ("name", "phone", "payment_code")
    actions = ["approve_shops", "switch_off", "switch_on"]

    def get_queryset(self, request):
        week = timezone.now() - timedelta(days=7)
        return super().get_queryset(request).annotate(
            bills_7d=Count("sales", filter=Q(sales__created_at__gte=week), distinct=True),
            last_bill=Max("sales__created_at"),
            expiry=Max("subscriptions__expires_on"),
        )

    @admin.display(ordering="bills_7d", description="Bills (7 days)")
    def bills_7d(self, obj):
        return obj.bills_7d

    @admin.display(ordering="last_bill", description="Last bill")
    def last_bill(self, obj):
        return obj.last_bill.strftime("%d %b %Y") if obj.last_bill else "never"

    @admin.display(description="Plan")
    def plan(self, obj):
        sub = subscription_service.current_subscription(obj)
        return sub.plan.name if sub else "-"

    @admin.display(ordering="expiry", description="Expires")
    def expires(self, obj):
        return obj.expiry

    @admin.action(description="Approve selected shops and start their free trial")
    def approve_shops(self, request, queryset):
        n = 0
        for shop in queryset.filter(is_approved=False):
            subscription_service.approve_shop(shop)
            n += 1
        self.message_user(request, f"{n} shop(s) approved.")

    @admin.action(description="Switch off selected shops (nobody can sign in to them)")
    def switch_off(self, request, queryset):
        self.message_user(request, f"{queryset.update(is_active=False)} shop(s) switched off.", messages.WARNING)

    @admin.action(description="Switch on selected shops")
    def switch_on(self, request, queryset):
        self.message_user(request, f"{queryset.update(is_active=True)} shop(s) switched on.")


@admin.register(ShopMembership)
class ShopMembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "shop", "role", "is_active")
    list_filter = ("role", "is_active")
    search_fields = ("user__username", "shop__name")


admin.site.register(ShopNotification)
