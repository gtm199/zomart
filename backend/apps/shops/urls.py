from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import MemberViewSet, NotificationView, ShopView, SubscriptionView

router = SimpleRouter()
router.register("shop/members", MemberViewSet, basename="shop-member")

urlpatterns = [
    path("shop/", ShopView.as_view()),
    path("shop/subscription/", SubscriptionView.as_view()),
    path("shop/notifications/", NotificationView.as_view()),
] + router.urls
