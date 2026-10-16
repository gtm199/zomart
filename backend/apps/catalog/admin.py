from django.contrib import admin

from .models import Brand, Category, MasterProduct, ProductBarcode, ProductChangeLog, ProductSuggestion


class BarcodeInline(admin.TabularInline):
    model = ProductBarcode
    extra = 1


@admin.register(MasterProduct)
class MasterProductAdmin(admin.ModelAdmin):
    list_display = ("name", "brand", "pack_size", "unit", "category", "status", "mrp")
    list_filter = ("status", "category", "brand")
    search_fields = ("name", "brand__name", "barcodes__code", "search_keywords")
    inlines = [BarcodeInline]


admin.site.register(Brand)
admin.site.register(Category)
admin.site.register(ProductChangeLog)
admin.site.register(ProductSuggestion)
