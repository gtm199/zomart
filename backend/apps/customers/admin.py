from django.contrib import admin

from .models import Customer, CustomerLedger

admin.site.register(Customer)
admin.site.register(CustomerLedger)
