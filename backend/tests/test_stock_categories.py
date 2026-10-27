from rest_framework.test import APITestCase

from apps.catalog.models import Category

from .helpers import API, EAN_ATTA, EAN_OIL, add_listing, client_for, make_master, make_vendor


class StockCategoryTests(APITestCase):
    def setUp(self):
        self.ua, self.shop_a = make_vendor("sc_a", "Shop A")
        self.ub, self.shop_b = make_vendor("sc_b", "Shop B")
        self.a, self.b = client_for(self.ua, self.shop_a), client_for(self.ub, self.shop_b)
        self.grains = Category.objects.create(name="Grains")
        self.rice = Category.objects.create(name="Rice", parent=self.grains)
        atta, basmati, oil = (make_master("Atta", barcode=EAN_ATTA), make_master("Basmati", barcode=EAN_OIL),
                              make_master("Mystery", barcode=None))
        atta.category, basmati.category = self.grains, self.rice
        atta.save()
        basmati.save()
        for m in (atta, basmati, oil):
            add_listing(self.a, m)
        add_listing(self.b, atta)

    def names(self, client, query):
        return sorted(r["master_product"]["name"] for r in client.get(f"{API}/shop/products/?{query}").data["results"])

    def test_main_category_includes_sub_categories_and_zero_means_no_category(self):
        self.assertEqual(self.names(self.a, f"category={self.grains.id}"), ["Atta", "Basmati"])
        self.assertEqual(self.names(self.a, f"category={self.rice.id}"), ["Basmati"])
        self.assertEqual(self.names(self.a, "category=0"), ["Mystery"])
        self.assertEqual(len(self.names(self.a, "")), 3)

    def test_category_works_with_search_and_stock_filters(self):
        self.assertEqual(self.names(self.a, f"category={self.grains.id}&search=basmati"), ["Basmati"])

    def test_counts_are_the_shops_own(self):
        rows = {r["name"]: r["product_count"] for r in self.a.get(f"{API}/shop/products/categories/").data}
        self.assertEqual((rows["Grains"], rows["Rice"], rows["No category"]), (1, 1, 1))
        other = {r["name"]: r["product_count"] for r in self.b.get(f"{API}/shop/products/categories/").data}
        self.assertEqual((other["Grains"], other["Rice"], "No category" in other), (1, 0, False))
        