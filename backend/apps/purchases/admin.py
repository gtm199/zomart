from django.contrib import admin

from .models import Purchase, PurchaseItem

admin.site.register(Purchase)
admin.site.register(PurchaseItem)