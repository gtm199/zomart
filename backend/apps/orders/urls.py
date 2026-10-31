from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter()
router.register("shop/orders", views.OrderViewSet, basename="shop-order")
router.register("store/orders", views.ShopperOrderViewSet, basename="store-order")

urlpatterns = [
    path("store/auth/register/", views.ShopperRegisterView.as_view()),
    path("store/auth/login/", views.ShopperLoginView.as_view()),
    path("store/auth/me/", views.ShopperMeView.as_view()),
    path("store/auth/logout/", views.ShopperLogoutView.as_view()),
    path("store/shops/", views.ShopListView.as_view()),
    path("store/shops/<int:pk>/", views.ShopDetailView.as_view()),
    path("store/shops/<int:shop_id>/products/", views.StoreProductsView.as_view()),
    path("store/shops/<int:shop_id>/categories/", views.StoreCategoriesView.as_view()),
    path("store/my-shops/", views.MyShopsView.as_view()),
    path("shop/store-settings/", views.StoreSettingsView.as_view()),
] + router.urls