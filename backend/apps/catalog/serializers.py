from decimal import Decimal

from rest_framework import serializers

from services import barcode_service, catalog_service

from .models import Brand, Category, MasterProduct, ProductBarcode, ProductSuggestion


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "name", "parent", "sort_order"]


class BrandSerializer(serializers.ModelSerializer):
    class Meta:
        model = Brand
        fields = ["id", "name"]


class MasterProductSerializer(serializers.ModelSerializer):
    """Vendor-facing, read-only view of the central catalogue."""
    display_name = serializers.CharField(read_only=True)
    brand_name = serializers.CharField(source="brand.name", read_only=True, default="")
    category_name = serializers.CharField(source="category.name", read_only=True, default="")
    barcodes = serializers.SlugRelatedField(many=True, read_only=True, slug_field="code")
    my_listing_id = serializers.SerializerMethodField()

    class Meta:
        model = MasterProduct
        fields = ["id", "display_name", "name", "brand_name", "category", "category_name", "pack_size", "unit",
                  "description", "image", "mrp", "tax_rate", "is_loose", "status", "barcodes", "my_listing_id"]

    def get_my_listing_id(self, obj):
        return self.context.get("listing_map", {}).get(obj.id)


class ProductBarcodeSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductBarcode
        fields = ["id", "code", "symbology", "is_primary"]
        read_only_fields = ["symbology"]

    def validate_code(self, value):
        try:
            return barcode_service.validate_barcode(value)[0]
        except ValueError as exc:
            raise serializers.ValidationError(str(exc))


class MasterProductAdminSerializer(serializers.ModelSerializer):
    barcodes = ProductBarcodeSerializer(many=True, required=False)
    display_name = serializers.CharField(read_only=True)
    vendor_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = MasterProduct
        fields = ["id", "display_name", "name", "brand", "category", "pack_size", "unit", "description", "image",
                  "mrp", "tax_rate", "hsn_code", "is_loose", "search_keywords", "status", "barcodes",
                  "vendor_count", "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at"]

    def validate(self, attrs):
        get = lambda k: attrs.get(k, getattr(self.instance, k, None) if self.instance else None)
        brand = get("brand")
        dupes = catalog_service.find_duplicates(
            get("name") or "", brand.pk if brand else None, get("pack_size") or Decimal("1"), get("unit") or "pc",
            exclude_id=self.instance.pk if self.instance else None)
        if dupes.exists():
            raise serializers.ValidationError(f"Possible duplicate of product #{dupes.first().pk}. Review before creating.")
        return attrs

    def create(self, validated_data):
        barcodes = validated_data.pop("barcodes", [])
        product = MasterProduct.objects.create(created_by=self.context["request"].user, **validated_data)
        for i, b in enumerate(barcodes):
            catalog_service.add_barcode(product, b["code"], is_primary=b.get("is_primary", i == 0))
        return product

    def update(self, instance, validated_data):
        validated_data.pop("barcodes", None)  # managed via the add-barcode action
        return super().update(instance, validated_data)


class ProductSuggestionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductSuggestion
        fields = ["id", "name", "brand_name", "barcode", "pack_size", "unit", "notes", "status", "created_at"]
        read_only_fields = ["status", "created_at"]


class ProductSuggestionAdminSerializer(ProductSuggestionSerializer):
    shop_name = serializers.CharField(source="shop.name", read_only=True)

    class Meta(ProductSuggestionSerializer.Meta):
        fields = ProductSuggestionSerializer.Meta.fields + ["shop_name", "resulting_product"]
