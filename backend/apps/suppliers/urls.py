from rest_framework.routers import SimpleRouter

from .views import SupplierViewSet

router = SimpleRouter()
router.register("shop/suppliers", SupplierViewSet, basename="shop-supplier")
urlpatterns = router.urls