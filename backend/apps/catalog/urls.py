from django.urls import path
from rest_framework.routers import SimpleRouter

from . import image_sync_views, views

router = SimpleRouter()
router.register("catalog/products", views.CatalogProductViewSet, basename="catalog-product")
router.register("shop/product-suggestions", views.ProductSuggestionViewSet, basename="product-suggestion")
router.register("platform/catalog/brands", views.AdminBrandViewSet, basename="admin-brand")
router.register("platform/catalog/categories", views.AdminCategoryViewSet, basename="admin-category")
router.register("platform/catalog/products", views.AdminProductViewSet, basename="admin-product")
router.register("platform/catalog/suggestions", views.AdminSuggestionViewSet, basename="admin-suggestion")

urlpatterns = [
    path("catalog/categories/", views.CategoryListView.as_view()),
    path("platform/catalog/image-sync/", image_sync_views.ImageSyncView.as_view()),
    path("platform/catalog/image-sync/<int:run_id>/step/", image_sync_views.ImageSyncStepView.as_view()),
    path("platform/catalog/image-sync/<int:run_id>/missing.csv", image_sync_views.ImageSyncMissingCsvView.as_view()),
] + router.urls
