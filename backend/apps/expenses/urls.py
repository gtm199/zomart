from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import AgeingView, CashCloseView, ExpenseViewSet, ProfitLossView, SalesAnalysisView

router = SimpleRouter()
router.register("shop/expenses", ExpenseViewSet, basename="shop-expense")

urlpatterns = [
    path("shop/reports/profit-loss/", ProfitLossView.as_view()),
    path("shop/reports/sales-analysis/", SalesAnalysisView.as_view()),
    path("shop/reports/ageing/", AgeingView.as_view()),
    path("shop/cash-close/", CashCloseView.as_view()),
] + router.urls