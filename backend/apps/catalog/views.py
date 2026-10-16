from django.db.models import Count, Q
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response

from core.tenancy import ShopScopedMixin, resolve_membership
from apps.inventory.models import ShopProduct
from apps.shops.roles import Cap
from services import barcode_service, catalog_service

from .models import Brand, Category, MasterProduct, ProductSuggestion
from .serializers import (BrandSerializer, CategorySerializer, MasterProductAdminSerializer,
                          MasterProductSerializer, ProductBarcodeSerializer,
                          ProductSuggestionAdminSerializer, ProductSuggestionSerializer)


class CategoryListView(ListAPIView):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    pagination_class = None


class CatalogProductViewSet(viewsets.ReadOnlyModelViewSet):
    """Vendor browsing of ACTIVE master products. Optional X-Shop-ID adds my_listing_id."""
    serializer_class = MasterProductSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = MasterProduct.objects.filter(status=MasterProduct.Status.ACTIVE) \
            .select_related("brand", "category").prefetch_related("barcodes")
        p = self.request.query_params
        term = (p.get("search") or "").strip()
        if term:
            qs = qs.filter(Q(name__icontains=term) | Q(brand__name__icontains=term) |
                           Q(search_keywords__icontains=term) | Q(barcodes__code=term)).distinct()
        cat = p.get("category")
        if cat and cat.isdigit():
            qs = qs.filter(Q(category_id=cat) | Q(category__parent_id=cat))
        return qs

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        membership = resolve_membership(self.request.user, self.request.headers.get("X-Shop-ID"))
        listing = {}
        if membership:
            listing = dict(ShopProduct.objects.filter(shop=membership.shop).values_list("master_product_id", "id"))
        ctx["listing_map"] = listing
        return ctx

    @action(detail=False, url_path=r"by-barcode/(?P<code>[^/.]+)")
    def by_barcode(self, request, code):
        product = barcode_service.find_master_product(code)
        if product is None or product.status != MasterProduct.Status.ACTIVE:
            return Response({"detail": "No product with this barcode in the central catalogue."},
                            status=status.HTTP_404_NOT_FOUND)
        return Response(self.get_serializer(product).data)


class ProductSuggestionViewSet(ShopScopedMixin, mixins.CreateModelMixin, mixins.ListModelMixin,
                               viewsets.GenericViewSet):
    queryset = ProductSuggestion.objects.all()
    serializer_class = ProductSuggestionSerializer
    required_caps = {"*": Cap.MANAGE_PRODUCTS}

    def perform_create(self, serializer):
        serializer.save(shop=self.request.shop, suggested_by=self.request.user)


# ---------------- platform administrator ----------------
class AdminBrandViewSet(viewsets.ModelViewSet):
    queryset = Brand.objects.all()
    serializer_class = BrandSerializer
    permission_classes = [IsAdminUser]


class AdminCategoryViewSet(viewsets.ModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = [IsAdminUser]


class AdminProductViewSet(viewsets.ModelViewSet):
    serializer_class = MasterProductAdminSerializer
    permission_classes = [IsAdminUser]

    def get_queryset(self):
        qs = MasterProduct.objects.select_related("brand", "category").prefetch_related("barcodes") \
            .annotate(vendor_count=Count("shopproduct", distinct=True))
        p = self.request.query_params
        if p.get("status"):
            qs = qs.filter(status=p["status"])
        if p.get("search"):
            qs = qs.filter(Q(name__icontains=p["search"]) | Q(barcodes__code=p["search"])).distinct()
        if p.get("missing_image") == "true":
            qs = qs.filter(image="")
        return qs

    def perform_update(self, serializer):
        before = catalog_service.snapshot(serializer.instance)
        product = serializer.save()
        catalog_service.log_changes(product, before, self.request.user)

    @action(detail=True, methods=["post"], url_path="add-barcode")
    def add_barcode(self, request, pk=None):
        product = self.get_object()
        s = ProductBarcodeSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        barcode = catalog_service.add_barcode(product, s.validated_data["code"],
                                              is_primary=s.validated_data.get("is_primary", False))
        return Response(ProductBarcodeSerializer(barcode).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        return self._set_status(MasterProduct.Status.ACTIVE)

    @action(detail=True, methods=["post"])
    def deactivate(self, request, pk=None):
        return self._set_status(MasterProduct.Status.INACTIVE)

    def _set_status(self, new_status):
        product = self.get_object()
        before = catalog_service.snapshot(product)
        product.status = new_status
        product.save(update_fields=["status", "updated_at"])
        catalog_service.log_changes(product, before, self.request.user)
        return Response(self.get_serializer(product).data)


class AdminSuggestionViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    queryset = ProductSuggestion.objects.select_related("shop")
    serializer_class = ProductSuggestionAdminSerializer
    permission_classes = [IsAdminUser]

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        suggestion = self.get_object()
        existing = None
        if request.data.get("existing_product_id"):
            existing = MasterProduct.objects.get(pk=request.data["existing_product_id"])
        product = catalog_service.approve_suggestion(suggestion, request.user, existing)
        return Response({"product_id": product.pk, "status": product.status})

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        suggestion = self.get_object()
        suggestion.status = ProductSuggestion.Status.REJECTED
        suggestion.reviewed_by = request.user
        suggestion.save(update_fields=["status", "reviewed_by"])
        return Response({"status": suggestion.status})
