from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter()
router.register("catalog/products", views.CatalogProductViewSet, basename="catalog-product")
router.register("shop/product-suggestions", views.ProductSuggestionViewSet, basename="product-suggestion")
router.register("platform/catalog/brands", views.AdminBrandViewSet, basename="admin-brand")
router.register("platform/catalog/categories", views.AdminCategoryViewSet, basename="admin-category")
router.register("platform/catalog/products", views.AdminProductViewSet, basename="admin-product")
router.register("platform/catalog/suggestions", views.AdminSuggestionViewSet, basename="admin-suggestion")

urlpatterns = [path("catalog/categories/", views.CategoryListView.as_view())] + router.urls
