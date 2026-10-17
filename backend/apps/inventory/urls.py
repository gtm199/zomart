from django.urls import path
from rest_framework.routers import SimpleRouter

from .sync_views import SyncView
from .views import ShopProductViewSet

router = SimpleRouter()
router.register("shop/products", ShopProductViewSet, basename="shop-product")

urlpatterns = [path("shop/sync/", SyncView.as_view())] + router.urls