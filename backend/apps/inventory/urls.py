from rest_framework.routers import SimpleRouter

from .views import ShopProductViewSet

router = SimpleRouter()
router.register("shop/products", ShopProductViewSet, basename="shop-product")
urlpatterns = router.urls
