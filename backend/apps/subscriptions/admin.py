from django.contrib import admin

from .models import ShopSubscription, SubscriptionPlan

admin.site.register(SubscriptionPlan)


@admin.register(ShopSubscription)
class ShopSubscriptionAdmin(admin.ModelAdmin):
    list_display = ("shop", "plan", "status", "starts_on", "expires_on", "grace_days")
    list_filter = ("status", "plan")
