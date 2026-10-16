from django.contrib import admin

from .models import ShopProduct, StockMovement

admin.site.register(ShopProduct)
admin.site.register(StockMovement)
