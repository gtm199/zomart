"""Phase A: one helper turns a stored image (Cloudinary public ID) into thumb / medium / tiny / full addresses, and every
product serializer returns image_thumb / image_medium / image_tiny (null when there is no image).
No network: addresses are only built, never fetched."""
import os
from unittest import mock

from django.test import SimpleTestCase, override_settings
from rest_framework.test import APITestCase

from apps.catalog.models import MasterProduct
from core import media

from .helpers import API, add_listing, client_for, make_master, make_vendor
from .test_orders import register_shopper

CLOUD = "democloud"
BASE = f"https://res.cloudinary.com/{CLOUD}/image/upload"
T, M, TINY = "w_300,c_limit,q_auto,f_auto", "w_800,c_limit,q_auto,f_auto", "w_120,c_limit,q_auto,f_auto"


class FakeCloudStorage:
    """Stands in for core.storage.CloudinaryMediaStorage (it has thumbnail_url); never called."""
    def thumbnail_url(self, name, size=400):
        raise AssertionError("the helper builds addresses itself")


class FakeFile:
    def __init__(self, name, storage=None, url=""):
        self.name, self.storage, self._url = name, storage, url

    @property
    def url(self):
        return self._url

    def __bool__(self):
        return bool(self.name)


@override_settings(CLOUDINARY_CLOUD_NAME=CLOUD)
class HelperTests(SimpleTestCase):
    def test_barcode_public_id_gets_each_size(self):
        f = FakeFile("690225305747")
        self.assertEqual(media.image_url(f, "thumb"), f"{BASE}/{T}/690225305747")
        self.assertEqual(media.image_url(f, "medium"), f"{BASE}/{M}/690225305747")
        self.assertEqual(media.image_url(f, "tiny"), f"{BASE}/{TINY}/690225305747")
        self.assertEqual(media.image_fields(f), {"image_thumb": f"{BASE}/{T}/690225305747",
                                                 "image_medium": f"{BASE}/{M}/690225305747",
                                                 "image_tiny": f"{BASE}/{TINY}/690225305747"})
        self.assertEqual(media.thumb_url(f), f"{BASE}/{T}/690225305747")      # old helper, same address
        self.assertIn("w_1600", media.full_url(f))

    def test_admin_upload_on_cloudinary_uses_the_name_without_extension(self):
        f = FakeFile("catalog/pack_ab12cd34.png", storage=FakeCloudStorage())
        self.assertEqual(media.image_url(f, "thumb"), f"{BASE}/{T}/catalog/pack_ab12cd34")

    def test_local_development_upload_keeps_its_file_address(self):
        f = FakeFile("catalog/pack.png", storage=object(), url="/media/catalog/pack.png")
        self.assertEqual(media.image_url(f, "thumb"), "/media/catalog/pack.png")

    def test_no_image_gives_null_and_old_helpers_give_blank(self):
        for empty in (FakeFile(""), None):
            self.assertIsNone(media.image_url(empty))
            self.assertEqual(media.image_fields(empty), {"image_thumb": None, "image_medium": None, "image_tiny": None})
            self.assertEqual((media.thumb_url(empty), media.full_url(empty)), ("", ""))

    @override_settings(CLOUDINARY_CLOUD_NAME="")
    def test_cloud_name_from_cloudinary_url_and_secret_never_used(self):
        with mock.patch.dict(os.environ, {"CLOUDINARY_URL": "cloudinary://1234:TOPSECRET@fromenv"}):
            url = media.image_url(FakeFile("690225305747"))
        self.assertEqual(url, f"https://res.cloudinary.com/fromenv/image/upload/{T}/690225305747")
        self.assertNotIn("TOPSECRET", url)
        self.assertNotIn("1234", url)
        with mock.patch.dict(os.environ, {"CLOUDINARY_URL": ""}):
            self.assertIsNone(media.image_url(FakeFile("690225305747")))    # no cloud known: no broken address

    def test_odd_characters_are_escaped(self):
        self.assertEqual(media.image_url(FakeFile("ab cd#1")), f"{BASE}/{T}/ab%20cd%231")


@override_settings(CLOUDINARY_CLOUD_NAME=CLOUD)
class SerializerImageTests(APITestCase):
    def setUp(self):
        self.user, self.shop = make_vendor("imgurl_owner", "Img Url Shop")
        self.c = client_for(self.user, self.shop)
        self.with_img = make_master("Biscuit", barcode="690225305747")
        MasterProduct.objects.filter(pk=self.with_img.pk).update(image="690225305747")   # as the import/sync stores it
        self.plain = make_master("Plain Salt", barcode=None)

    def rows(self):
        return {r["name"]: r for r in self.c.get(f"{API}/catalog/products/").data["results"]}

    def test_vendor_catalogue_returns_thumb_medium_tiny_and_old_fields(self):
        r = self.rows()
        b, p = r["Biscuit"], r["Plain Salt"]
        self.assertEqual((b["image_thumb"], b["image_medium"], b["image_tiny"]),
                         (f"{BASE}/{T}/690225305747", f"{BASE}/{M}/690225305747", f"{BASE}/{TINY}/690225305747"))
        self.assertEqual(b["thumbnail"], f"{BASE}/{T}/690225305747")       # installed apps keep working
        self.assertIn("w_1600", b["image"])
        self.assertEqual((p["image_thumb"], p["image_medium"], p["image_tiny"], p["image"], p["thumbnail"]),
                         (None, None, None, None, ""))

    def test_customer_and_phone_sync_get_the_new_fields(self):
        add_listing(self.c, self.with_img, stock="3")
        add_listing(self.c, self.plain, stock="3")
        self.c.patch(f"{API}/shop/store-settings/", {"store_enabled": True}, format="json")
        shopper = register_shopper("Img Url Cust", "9988776600")
        rows = {r["name"]: r for r in shopper.get(f"{API}/store/shops/{self.shop.id}/products/").data["results"]}
        b = next(v for k, v in rows.items() if "Biscuit" in k)
        p = next(v for k, v in rows.items() if "Plain" in k)
        self.assertEqual((b["image"], b["image_thumb"], b["image_medium"]),
                         (f"{BASE}/{T}/690225305747", f"{BASE}/{T}/690225305747", f"{BASE}/{M}/690225305747"))
        self.assertIn("w_1600", b["image_full"])
        self.assertEqual((p["image"], p["image_thumb"], p["image_medium"]), ("", None, None))
        sync = {x["name"]: x for x in self.c.get(f"{API}/shop/sync/").data["products"]}
        sb = next(v for k, v in sync.items() if "Biscuit" in k)
        self.assertEqual((sb["image"], sb["image_thumb"], sb["image_medium"]),
                         (f"{BASE}/{T}/690225305747", f"{BASE}/{T}/690225305747", f"{BASE}/{M}/690225305747"))

    def test_no_private_fields_leak(self):
        b = self.rows()["Biscuit"]
        for secret in ("api_key", "api_secret", "CLOUDINARY_URL"):
            self.assertNotIn(secret, str(b))
