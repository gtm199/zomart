from rest_framework.routers import SimpleRouter

from .views import CustomerViewSet

router = SimpleRouter()
router.register("shop/customers", CustomerViewSet, basename="shop-customer")
urlpatterns = router.urls
