from django.contrib import admin

from .models import Supplier, SupplierLedger, SupplierPayment

admin.site.register(Supplier)
admin.site.register(SupplierLedger)
admin.site.register(SupplierPayment)