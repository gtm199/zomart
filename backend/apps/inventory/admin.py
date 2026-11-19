from django.contrib import admin

from .models import ShopProduct, StockBatch, StockMovement

admin.site.register(ShopProduct)
admin.site.register(StockMovement)


@admin.register(StockBatch)
class StockBatchAdmin(admin.ModelAdmin):
    """Read-only: batches change only through services/inventory_service.py (stock must stay in step)."""
    list_display = ("id", "shop", "shop_product", "expiry_date", "batch_no", "quantity_received", "quantity_left",
                    "source", "created_at")
    list_filter = ("source",)
    search_fields = ("batch_no", "shop__name", "shop_product__master_product__name")
    list_select_related = ("shop", "shop_product__master_product")
    date_hierarchy = "expiry_date"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
