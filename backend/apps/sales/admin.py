from django.contrib import admin

from .models import Payment, Sale, SaleItem

admin.site.register(Sale)
admin.site.register(SaleItem)
admin.site.register(Payment)
