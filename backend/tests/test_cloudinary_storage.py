import os
from unittest import mock

import cloudinary
from django.core.files.base import ContentFile
from django.test import SimpleTestCase

from core.storage import CloudinaryMediaStorage


class CloudinaryStorageTests(SimpleTestCase):
    def setUp(self):
        cloudinary.config(cloud_name="democloud", api_key="key", api_secret="secret", secure=True)
        self.storage = CloudinaryMediaStorage()

    def test_addresses_point_to_cloudinary_and_are_resized(self):
        full = self.storage.url("catalog/pack_ab12cd34.png")
        small = self.storage.thumbnail_url("catalog/pack_ab12cd34.png", 400)
        for url in (full, small):
            self.assertTrue(url.startswith("https://res.cloudinary.com/democloud/image/upload/"), url)
            self.assertTrue(url.endswith("/catalog/pack_ab12cd34"), url)
            self.assertIn("f_auto", url)
        self.assertIn("w_1600", full)
        self.assertIn("w_400", small)
        self.assertIn("h_400", small)
        self.assertIn("c_limit", small)

    def test_every_upload_gets_a_new_name_and_no_network_check(self):
        a = self.storage.get_available_name("catalog/Pack.PNG")
        b = self.storage.get_available_name("catalog/Pack.PNG")
        self.assertNotEqual(a, b)
        self.assertTrue(a.startswith("catalog/Pack_") and a.endswith(".png"))
        self.assertFalse(self.storage.exists(a))
        self.assertLessEqual(len(self.storage.get_available_name("catalog/" + "x" * 200 + ".png", max_length=100)), 100)

    @mock.patch("cloudinary.uploader.upload")
    def test_save_uploads_under_the_same_name_without_the_extension(self, upload):
        name = self.storage.save("catalog/pack.png", ContentFile(b"fake image"))
        self.assertTrue(name.startswith("catalog/pack_") and name.endswith(".png"))
        self.assertEqual(upload.call_args.kwargs["public_id"], os.path.splitext(name)[0])
        self.assertEqual(upload.call_args.kwargs["resource_type"], "image")

    @mock.patch("cloudinary.uploader.destroy")
    def test_delete_removes_the_cloudinary_copy_and_never_raises(self, destroy):
        self.storage.delete("catalog/pack_ab12cd34.png")
        self.assertEqual(destroy.call_args.args[0], "catalog/pack_ab12cd34")
        destroy.side_effect = RuntimeError("network down")
        self.storage.delete("catalog/pack_ab12cd34.png")  # must not raise