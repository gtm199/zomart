import io
import os
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from PIL import Image as PILImage
from rest_framework.test import APITestCase

from apps.catalog.models import MasterProduct

from .helpers import API, add_listing, client_for, make_master, make_vendor
from .test_orders import register_shopper


def png_upload(name="pack.png", size=(1200, 900)):
    buf = io.BytesIO()
    PILImage.frombytes("RGB", size, os.urandom(size[0] * size[1] * 3)).save(buf, "PNG")  # noise: a big file, like a real photo
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/png")


class ProductImageTests(APITestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._override = override_settings(MEDIA_ROOT=self._tmp.name)
        self._override.enable()
        self.addCleanup(self._override.disable)
        self.addCleanup(self._tmp.cleanup)
        self.user, self.shop = make_vendor("img_owner", "Image Shop")
        self.c = client_for(self.user, self.shop)

    def product_with_image(self):
        p = make_master("Atta", barcode=None)
        p.image = png_upload()
        p.save()
        p.refresh_from_db()
        return p

    def test_a_small_thumbnail_is_made_when_an_image_is_uploaded(self):
        p = self.product_with_image()
        self.assertTrue(p.thumbnail)
        with PILImage.open(p.thumbnail.path) as t:
            self.assertLessEqual(max(t.size), 400)
        self.assertLess(p.thumbnail.size, p.image.size)

    def test_removing_the_image_removes_the_thumbnail(self):
        p = self.product_with_image()
        p.image = ""
        p.save()
        p.refresh_from_db()
        self.assertFalse(p.thumbnail)

    def test_vendor_screens_get_both_urls(self):
        p = self.product_with_image()
        row = self.c.get(f"{API}/catalog/products/").data["results"][0]
        self.assertTrue(row["thumbnail"] and "/thumbs/" in row["thumbnail"])
        self.assertTrue(row["image"])
        sp = add_listing(self.c, p, stock="3")
        self.assertTrue(self.c.get(f"{API}/shop/products/{sp['id']}/").data["master_product"]["thumbnail"])

    def test_customers_get_the_small_picture(self):
        p = self.product_with_image()
        add_listing(self.c, p, stock="3")
        self.c.patch(f"{API}/shop/store-settings/", {"store_enabled": True}, format="json")
        shopper = register_shopper("Img Cust", "9988776655")
        row = shopper.get(f"{API}/store/shops/{self.shop.id}/products/").data["results"][0]
        self.assertIn("/thumbs/", row["image"])
        self.assertTrue(row["image"].startswith("http"))
        self.assertTrue(row["image_full"])
        self.assertNotIn("/thumbs/", row["image_full"])

    def test_products_without_images_still_work(self):
        make_master("Plain", barcode=None)
        row = self.c.get(f"{API}/catalog/products/").data["results"][0]
        self.assertFalse(row["thumbnail"])
        self.assertFalse(MasterProduct.objects.get(name="Plain").thumbnail)

    def test_phone_sync_carries_the_picture_address(self):
        p = self.product_with_image()
        add_listing(self.c, p, stock="3")
        self.assertIn("/thumbs/", self.c.get(f"{API}/shop/sync/").data["products"][0]["image"])