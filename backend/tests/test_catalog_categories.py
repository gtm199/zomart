from rest_framework.test import APITestCase

from apps.catalog.models import Category, MasterProduct

from .helpers import API, EAN_ATTA, EAN_OIL, client_for, make_master, make_vendor


class CategoryBrowsingTests(APITestCase):
    def setUp(self):
        self.user, self.shop = make_vendor("cat_owner", "Cat Shop")
        self.c = client_for(self.user, self.shop)
        self.grains = Category.objects.create(name="Grains")
        self.rice = Category.objects.create(name="Rice", parent=self.grains)
        self.atta = make_master("Atta", barcode=EAN_ATTA)
        self.basmati = make_master("Basmati", barcode=EAN_OIL)
        self.oil = make_master("Mystery item", barcode=None)
        self.atta.category, self.basmati.category = self.grains, self.rice
        self.atta.save()
        self.basmati.save()

    def names(self, query):
        return sorted(p["name"] for p in self.c.get(f"{API}/catalog/products/?{query}").data["results"])

    def test_a_main_category_includes_its_sub_categories(self):
        self.assertEqual(self.names(f"category={self.grains.id}"), ["Atta", "Basmati"])
        self.assertEqual(self.names(f"category={self.rice.id}"), ["Basmati"])
        self.assertEqual(len(self.names("")), 3)  # "All" also shows products with no category

    def test_category_search_and_filter_work_together(self):
        self.assertEqual(self.names(f"category={self.grains.id}&search=atta"), ["Atta"])

    def test_counts_only_include_active_products(self):
        MasterProduct.objects.filter(pk=self.basmati.pk).update(status=MasterProduct.Status.INACTIVE)
        rows = {r["name"]: r["product_count"] for r in self.c.get(f"{API}/catalog/categories/").data}
        self.assertEqual((rows["Grains"], rows["Rice"]), (1, 0))