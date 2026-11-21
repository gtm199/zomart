"""Phase D: admin dashboard - Sync panel, re-check image (one product and a selection), run log, CSRF on the
session-signed endpoint. Cloudinary is mocked."""
from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.catalog.models import ImageSyncRun, MasterProduct, ProductChangeLog
from services import cloudinary_image_service as cis
from services import image_sync_service as sync

from .test_catalog_import_images import FakeCloudinary, ean13
from .test_image_sync import product

CLOUD = "democloud"
CL = "/admin/catalog/masterproduct/"


@override_settings(CLOUDINARY_CLOUD_NAME=CLOUD)
class ImageAdminTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = User.objects.create_superuser("img_admin", password="Admin#Pass1")
        self.client.force_login(self.admin)
        self.codes = [ean13(f"89077700{n:04d}") for n in range(1, 10)]

    def img(self, p):
        p.refresh_from_db()
        return p.image.name

    def test_dashboard_shows_the_sync_panel_and_run_log(self):
        product("No pic", self.codes[0])
        with mock.patch.object(cis, "_head", FakeCloudinary({}, 404)):
            sync.run_all(dry_run=True)
        r = self.client.get(f"{CL}dashboard/")
        self.assertContains(r, "Sync images from Cloudinary")
        self.assertContains(r, "Preview (changes nothing)")
        self.assertContains(r, "Replace existing images too")
        self.assertContains(r, "/missing.csv")                     # the preview left one barcode missing
        self.assertEqual(r.context["no_image_total"], 1)

    def test_staff_without_catalogue_rights_see_no_sync_panel(self):
        staff = User.objects.create_user("plain_staff", password="x#Pass12345", is_staff=True)
        self.client.force_login(staff)
        r = self.client.get(f"{CL}dashboard/")
        if r.status_code == 200:
            self.assertNotContains(r, "Sync images from Cloudinary")

    def test_recheck_action_attaches_only_where_missing(self):
        c = self.codes
        a, b = product("A", c[0]), product("B", c[1])
        kept = product("Kept", c[2], image="catalog/own_1234.png")
        with mock.patch.object(cis, "_head", FakeCloudinary({c[0]: 200, c[1]: 404, c[2]: 200})):
            r = self.client.post(CL, {"action": "recheck_images", "_selected_action": [a.pk, b.pk, kept.pk]}, follow=True)
        self.assertContains(r, "1 image(s) attached")
        self.assertEqual((self.img(a), self.img(b), self.img(kept)), (c[0], "", "catalog/own_1234.png"))
        self.assertIn("re-check", ProductChangeLog.objects.get(product=a).new_value)

    def test_recheck_one_product_button(self):
        p = product("Single", self.codes[3])
        page = self.client.get(f"{CL}{p.pk}/change/")
        self.assertContains(page, "Re-check image on Cloudinary")
        with mock.patch.object(cis, "_head", FakeCloudinary({self.codes[3]: 200})):
            self.client.get(f"{CL}{p.pk}/recheck-image/")             # GET changes nothing
            self.assertEqual(self.img(p), "")
            r = self.client.post(f"{CL}{p.pk}/recheck-image/", follow=True)
        self.assertContains(r, "1 image(s) attached")
        self.assertEqual(self.img(p), self.codes[3])
        self.assertNotContains(self.client.get(f"{CL}{p.pk}/change/"), "Re-check image on Cloudinary")

    def test_recheck_is_rate_limited(self):
        ps = [product(f"P{i}", self.codes[i]) for i in range(3)]
        with mock.patch.object(sync, "RECHECK_PER_HOUR", 2), mock.patch.object(cis, "_head", FakeCloudinary({}, 200)):
            self.client.post(CL, {"action": "recheck_images", "_selected_action": [p.pk for p in ps]}, follow=True)
            self.assertEqual(sum(1 for p in ps if self.img(p)), 2)
            r = self.client.post(CL, {"action": "recheck_images", "_selected_action": [ps[2].pk]}, follow=True)
        self.assertContains(r, "limit reached")
        self.assertEqual(self.img(ps[2]), "")

    def test_run_log_is_read_only_in_admin(self):
        with mock.patch.object(cis, "_head", FakeCloudinary({}, 404)):
            run = sync.start()
        r = self.client.get("/admin/catalog/imagesyncrun/")
        self.assertContains(r, str(run.pk))
        self.assertNotContains(r, "/admin/catalog/imagesyncrun/add/")

    def test_session_calls_need_the_csrf_token(self):
        c = APIClient(enforce_csrf_checks=True)
        c.force_login(self.admin)
        r = c.post("/api/v1/platform/catalog/image-sync/", {"dry_run": True}, format="json")
        self.assertEqual(r.status_code, 403)
        self.assertFalse(ImageSyncRun.objects.exists())
