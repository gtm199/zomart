from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import PurchaseViewSet, StockValuationView

router = SimpleRouter()
router.register("shop/purchases", PurchaseViewSet, basename="shop-purchase")

urlpatterns = [path("shop/reports/stock-valuation/", StockValuationView.as_view())] + router.urls