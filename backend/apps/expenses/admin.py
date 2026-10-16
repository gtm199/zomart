from django.contrib import admin

from .models import CashClose, Expense, ExpenseCategory

admin.site.register(ExpenseCategory)
admin.site.register(Expense)
admin.site.register(CashClose)