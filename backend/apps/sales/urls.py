from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import DailySummaryView, GstReportView, SaleViewSet

router = SimpleRouter()
router.register("shop/sales", SaleViewSet, basename="shop-sale")

urlpatterns = [
    path("shop/reports/daily-summary/", DailySummaryView.as_view()),
    path("shop/reports/gst/", GstReportView.as_view()),
] + router.urls
