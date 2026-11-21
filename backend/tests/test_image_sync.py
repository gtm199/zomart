"""Phase C: Sync images from Cloudinary (service, chunked endpoint, run log, management command).
Cloudinary is mocked (HEAD answers) - no internet, no Admin API."""
import io
from unittest import mock

from django.core.management import call_command
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.catalog.models import Brand, Category, ImageSyncRun, MasterProduct, ProductBarcode, ProductChangeLog
from services import cloudinary_image_service as cis
from services import image_sync_service as sync

from .test_catalog_import_images import FakeCloudinary, ean13

CLOUD = "democloud"
URL = "/api/v1/platform/catalog/image-sync/"


def product(name, *codes, image="", category=None, brand=None, primary_first=True):
    p = MasterProduct.objects.create(name=name, image=image, category=category, brand=brand)
    for i, c in enumerate(codes):
        ProductBarcode.objects.create(product=p, code=c, is_primary=(i == 0) == primary_first)
    return p


@override_settings(CLOUDINARY_CLOUD_NAME=CLOUD)
class SyncServiceTests(TestCase):
    def setUp(self):
        self.codes = [ean13(f"89055500{n:04d}") for n in range(1, 30)]

    def run_sync(self, answers, default=404, **opts):
        fake = FakeCloudinary(answers, default)
        with mock.patch.object(cis, "_head", fake):
            r = sync.run_all(**opts)
        return r, fake

    def img(self, p):
        p.refresh_from_db()
        return p.image.name

    def test_attaches_only_to_products_without_image(self):
        c = self.codes
        empty = product("Empty", c[0])
        has = product("Has", c[1], image="catalog/pack_keep1234.png")
        r, fake = self.run_sync({c[0]: 200, c[1]: 200})
        self.assertEqual((self.img(empty), self.img(has)), (c[0], "catalog/pack_keep1234.png"))
        self.assertEqual((r["attached"], r["processed"], r["remaining"], r["finished"]), (1, 1, 0, True))
        self.assertTrue(all(c[1] not in u for u in fake.calls))            # products with an image are not even checked
        log = ProductChangeLog.objects.get(product=empty)
        self.assertIn("image sync, run #", log.new_value)

    def test_replace_mode_replaces_but_never_with_unverified(self):
        c = self.codes
        a = product("A", c[0], image="catalog/old_a.png")
        b = product("B", c[1], image="catalog/old_b.png")
        same = product("Same", c[2], image=c[2])
        r, _ = self.run_sync({c[0]: 200, c[1]: 503, c[2]: 200}, replace=True)
        self.assertEqual((self.img(a), self.img(b), self.img(same)), (c[0], "catalog/old_b.png", c[2]))
        self.assertEqual((r["attached"], r["unverified"], r["skipped"]), (1, 1, 1))

    def test_dry_run_changes_nothing(self):
        c = self.codes
        ps = [product("A", c[0]), product("B", c[1]), product("C", c[2])]
        logs = ProductChangeLog.objects.count()
        r, _ = self.run_sync({c[0]: 200, c[1]: 200}, dry_run=True)
        self.assertEqual([self.img(p) for p in ps], ["", "", ""])
        self.assertEqual(ProductChangeLog.objects.count(), logs)
        self.assertEqual((r["attached"], r["still_missing"], r["dry_run"]), (2, 1, True))
        self.assertEqual(ImageSyncRun.objects.get(pk=r["run"]).missing_barcodes, [c[2]])

    def test_chunked_resumable_and_remaining_is_right(self):
        c = self.codes
        ps = [product(f"P{i}", c[i]) for i in range(7)]
        answers = {code: 200 for code in c[:7]}
        fake = FakeCloudinary(answers)
        with mock.patch.object(cis, "_head", fake):
            run = sync.start()
            r1 = sync.step(run.pk, batch=3)
            self.assertEqual((r1["processed"], r1["attached"], r1["remaining"], r1["finished"]), (3, 3, 4, False))
            again = sync.start()                       # "server stopped": Sync again continues the same run
            self.assertEqual(again.pk, run.pk)
            r2 = sync.step(run.pk, batch=3)
            self.assertEqual((r2["processed"], r2["remaining"]), (6, 1))
            r3 = sync.step(run.pk, batch=3)
            self.assertEqual((r3["processed"], r3["attached"], r3["remaining"], r3["finished"]), (7, 7, 0, True))
            r4 = sync.step(run.pk, batch=3)            # finished: nothing more
        self.assertEqual(r4["processed"], 7)
        self.assertEqual(len(fake.calls), 7)           # each product checked exactly once
        self.assertEqual(ProductChangeLog.objects.count(), 7)
        self.assertTrue(all(self.img(p) for p in ps))
        self.assertNotEqual(sync.start().pk, run.pk)   # a finished run is not reused

    def test_same_chunk_twice_is_not_done_twice(self):
        c = self.codes
        product("A", c[0]), product("B", c[1])
        with mock.patch.object(cis, "_head", FakeCloudinary({c[0]: 200, c[1]: 200})):
            run = sync.start()
            cursor = run.last_product_id
            sync.step(run.pk, batch=1)
            ImageSyncRun.objects.filter(pk=run.pk).update(last_product_id=cursor + 10**9)  # another call got there first
            r = sync.step(run.pk, batch=1)
        self.assertEqual(r["attached"], 1)

    def test_first_existing_barcode_wins_primary_first(self):
        c = self.codes
        p = product("Multi", c[0], c[1], c[2])              # c[0] primary
        q = product("Second ok", c[3], c[4])
        r, fake = self.run_sync({c[0]: 404, c[1]: 200, c[2]: 200, c[3]: 200, c[4]: 200})
        self.assertEqual((self.img(p), self.img(q)), (c[1], c[3]))
        self.assertFalse(any(u.endswith(c[2]) or u.endswith(c[4]) for u in fake.calls))   # stops at the first hit
        primary_last = product("Primary second", c[5], c[6], primary_first=False)        # c[6] is primary
        self.run_sync({c[5]: 200, c[6]: 200})
        self.assertEqual(self.img(primary_last), c[6])

    def test_no_barcode_skipped_and_unverified_unchanged(self):
        c = self.codes
        loose = product("Loose rice")
        flaky = product("Flaky", c[0])
        r, _ = self.run_sync({c[0]: [OSError(), OSError()]})
        self.assertEqual((self.img(loose), self.img(flaky)), ("", ""))
        self.assertEqual((r["skipped"], r["unverified"], r["still_missing"]), (1, 1, 0))
        r2, _ = self.run_sync({c[0]: 200})                   # run again later: now it is found
        self.assertEqual((self.img(flaky), r2["attached"]), (c[0], 1))

    def test_category_and_brand_filters(self):
        c = self.codes
        food = Category.objects.create(name="Food")
        sub = Category.objects.create(name="Biscuits", parent=food)
        other = Category.objects.create(name="Soap")
        br = Brand.objects.create(name="Parle")
        a, b, d = product("A", c[0], category=sub, brand=br), product("B", c[1], category=other), product("D", c[2], category=food)
        self.run_sync({x: 200 for x in c[:3]}, category=food)
        self.assertEqual((self.img(a), self.img(b), self.img(d)), (c[0], "", c[2]))
        self.run_sync({x: 200 for x in c[:3]}, brand=br, replace=True)
        self.assertEqual(self.img(b), "")

    def test_command(self):
        c = self.codes
        ps = [product(f"P{i}", c[i]) for i in range(5)]
        out = io.StringIO()
        with mock.patch.object(cis, "_head", FakeCloudinary({x: 200 for x in c[:4]})):
            call_command("sync_cloudinary_images", "--dry-run", stdout=out)
            self.assertIn("4 would be attached, 1 still missing", out.getvalue())
            self.assertEqual([self.img(p) for p in ps], [""] * 5)
            out = io.StringIO()
            call_command("sync_cloudinary_images", "--limit", "2", stdout=out)
            self.assertIn("paused", out.getvalue())
            out = io.StringIO()
            call_command("sync_cloudinary_images", stdout=out)       # continues the paused run
        self.assertIn("finished", out.getvalue())
        self.assertEqual(sum(1 for p in ps if self.img(p)), 4)
        self.assertEqual(ImageSyncRun.objects.filter(dry_run=False).count(), 1)

    @override_settings(CLOUDINARY_CLOUD_NAME="")
    def test_no_cloud_configured_refuses(self):
        with mock.patch.dict("os.environ", {"CLOUDINARY_URL": ""}):
            with self.assertRaises(sync.BusinessRuleError):
                sync.start()


@override_settings(CLOUDINARY_CLOUD_NAME=CLOUD)
class SyncEndpointTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("sync_admin", password="Admin#Pass1")
        self.c = APIClient()
        self.c.force_authenticate(self.admin)
        self.codes = [ean13(f"89066600{n:04d}") for n in range(1, 8)]
        self.ps = [product(f"P{i}", code) for i, code in enumerate(self.codes)]

    def test_dashboard_loop_until_remaining_is_zero(self):
        with mock.patch.object(cis, "_head", FakeCloudinary({x: 200 for x in self.codes[:5]})):
            r = self.c.post(URL, {"dry_run": False}, format="json")
            self.assertEqual(r.status_code, 200, r.data)
            run, rounds = r.data["run"], 0
            while not r.data["finished"]:
                r = self.c.post(f"{URL}{run}/step/", {"batch": 3}, format="json")
                rounds += 1
        self.assertEqual(rounds, 3)
        self.assertEqual({k: r.data[k] for k in ("processed", "attached", "still_missing", "remaining")},
                         {"processed": 7, "attached": 5, "still_missing": 2, "remaining": 0})
        log = self.c.get(URL).data[0]
        self.assertEqual((log["run"], log["started_by"], log["attached"]), (run, "sync_admin", 5))
        csv_text = self.c.get(f"{URL}{run}/missing.csv").content.decode()
        self.assertEqual(csv_text.split(), ["barcode", *self.codes[5:]])

    def test_only_catalogue_staff(self):
        vendor = User.objects.create_user("vendor_x", password="x#Pass12345")
        staff_no_perm = User.objects.create_user("staff_x", password="x#Pass12345", is_staff=True)
        for u in (vendor, staff_no_perm):
            c = APIClient()
            c.force_authenticate(u)
            self.assertEqual(c.post(URL, {}, format="json").status_code, 403)
            self.assertEqual(c.get(URL).status_code, 403)
        self.assertIn(APIClient().post(URL, {}, format="json").status_code, (401, 403))
        self.assertFalse(ImageSyncRun.objects.exists())
