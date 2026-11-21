"""Phase B: the catalogue import finds each product's image on Cloudinary by barcode (or the "image" column).
All HEAD requests are mocked - no internet, no Cloudinary Admin API."""
from unittest import mock

from django.test import TestCase, override_settings

from apps.accounts.models import User
from apps.catalog.models import MasterProduct, ProductBarcode, ProductChangeLog
from services import catalog_import_service as imp
from services import cloudinary_image_service as cis

CLOUD = "democloud"


def ean13(first12):
    total = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(first12))
    return first12 + str((10 - total % 10) % 10)


A, B, C, D, E = (ean13(f"89012345{n:04d}") for n in range(1, 6))


def row(name, barcode="", image="", brand="Test", pack="1"):
    return {"name": name, "brand": brand, "category": "Snacks", "pack_size": pack, "unit": "pc",
            "barcode": barcode, "mrp": "10", "tax_rate": "5", "description": "", "image": image}


class FakeCloudinary:
    """Answers HEAD requests: {public_id: status code or an exception}. Records every address asked."""

    def __init__(self, answers, default=404):
        self.answers, self.default, self.calls = answers, default, []

    def __call__(self, url):
        self.calls.append(url)
        pid = url.rsplit("/", 1)[-1]
        value = self.answers.get(pid, self.default)
        if isinstance(value, list):            # a sequence of answers, one per try
            value = value.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


@override_settings(CLOUDINARY_CLOUD_NAME=CLOUD)
class ImportImageTests(TestCase):
    def run_import(self, rows, answers=None, replace=False, default=404):
        fake = FakeCloudinary(answers or {}, default)
        with mock.patch.object(cis, "_head", fake):
            p = imp.plan(rows, replace_images=replace)
            report = imp.commit_plan(p)
        return p, report, fake

    def image_of(self, code):
        return ProductBarcode.objects.get(code=code).product.image.name

    def test_barcode_is_the_public_id_when_image_is_blank(self):
        p, r, fake = self.run_import([row("Chips", A)], {A: 200})
        self.assertEqual(self.image_of(A), A)
        self.assertEqual(fake.calls, [f"https://res.cloudinary.com/{CLOUD}/image/upload/{A}"])
        self.assertEqual((r["created"], r["images_found"]), (1, 1))
        log = ProductChangeLog.objects.get(field="image")
        self.assertIn("catalogue import", log.new_value)

    def test_image_column_overrides_the_barcode(self):
        own = f"https://res.cloudinary.com/{CLOUD}/image/upload/w_300,c_limit/v1712345/chips_front.webp"
        self.run_import([row("Chips", A, image="chips_main"), row("Nuts", B, image=own)],
                        {"chips_main": 200, "chips_front": 200})
        self.assertEqual((self.image_of(A), self.image_of(B)), ("chips_main", "chips_front"))

    def test_found_missing_unverified_and_totals(self):
        rows = [row("One", A), row("Two", B), row("Three", C), row("Loose rice")]
        p, r, _ = self.run_import(rows, {A: 200, B: 404, C: 503})
        self.assertEqual(MasterProduct.objects.count(), 4)                  # a missing image never blocks a product
        self.assertEqual((self.image_of(A), self.image_of(B), self.image_of(C)), (A, "", ""))
        t = p["totals"]
        self.assertEqual((t["products"], t["images_found"], t["images_missing"], t["images_unverified"], t["no_barcode"]),
                         (4, 1, 1, 1, 1))
        self.assertEqual(p["missing"], [B])
        for k in ("images_found", "images_missing", "images_unverified", "no_barcode", "products"):
            self.assertEqual(r[k], t[k])                                    # report = preview

    def test_other_sites_and_other_clouds_are_rejected(self):
        bad = ["https://evil.example.com/x.png", f"https://res.cloudinary.com/othercloud/image/upload/{A}",
               "http://169.254.169.254/latest/meta-data", "file:///etc/passwd", "ftp://res.cloudinary.com/x",
               "../../secret", "has space"]
        p, _, fake = self.run_import([row(f"P{i}", "", image=b) for i, b in enumerate(bad)])
        self.assertEqual(len(p["errors"]), len(bad))
        self.assertTrue(all("image:" in e for e in p["errors"]))
        self.assertEqual(fake.calls, [])                                    # nothing was fetched
        self.assertEqual(MasterProduct.objects.count(), 0)

    def test_spreadsheet_damaged_barcodes_are_reported_not_guessed(self):
        rows = [row("Sci", "6.9E+11"), row("Sci2", "8.90123E+12"), row("Zero lost", A[1:12]),
                row("Point zero", A + ".0"), row("Spaces", f" {B} ")]
        p, _, _ = self.run_import(rows, {A: 200, B: 200})
        errs = " ".join(p["errors"])
        self.assertIn("row 2:", errs)
        self.assertIn("row 3:", errs)
        self.assertIn("row 4:", errs)
        self.assertIn("spreadsheet", errs)
        self.assertEqual((self.image_of(A), self.image_of(B)), (A, B))     # ".0" and spaces are fine

    def test_existing_image_is_kept_unless_replace_is_ticked(self):
        self.run_import([row("Chips", A)], {A: 200})
        product = ProductBarcode.objects.get(code=A).product
        MasterProduct.objects.filter(pk=product.pk).update(image="catalog/pack_old1234.png")
        # same barcode again, image column pointing elsewhere: row skipped (no merge), image kept
        p, r, _ = self.run_import([row("Chips again", A, image="new_pic")], {"new_pic": 200})
        self.assertEqual(self.image_of(A), "catalog/pack_old1234.png")
        self.assertEqual((r["created"], r["existing_images_attached"]), (0, 0))
        self.assertIn("conflict", p["errors"][0])
        # replace ticked: but an unverifiable answer still never overwrites
        self.run_import([row("Chips again", A, image="new_pic")], {"new_pic": 500}, replace=True)
        self.assertEqual(self.image_of(A), "catalog/pack_old1234.png")
        _, r, _ = self.run_import([row("Chips again", A, image="new_pic")], {"new_pic": 200}, replace=True)
        self.assertEqual((self.image_of(A), r["existing_images_attached"]), ("new_pic", 1))

    def test_existing_product_without_image_gets_one(self):
        self.run_import([row("Chips", A)], {A: 404})
        self.assertEqual(self.image_of(A), "")
        _, r, _ = self.run_import([row("Chips", A)], {A: 200})             # image uploaded later, same file again
        self.assertEqual((self.image_of(A), r["created"], r["existing_images_attached"]), (A, 0, 1))

    def test_same_file_twice_changes_nothing(self):
        rows = [row("One", A), row("Two", B)]
        self.run_import(rows, {A: 200, B: 404})
        before = (MasterProduct.objects.count(), ProductChangeLog.objects.count(),
                  list(MasterProduct.objects.values_list("image", flat=True).order_by("id")))
        _, r, _ = self.run_import(rows, {A: 200, B: 404})
        after = (MasterProduct.objects.count(), ProductChangeLog.objects.count(),
                 list(MasterProduct.objects.values_list("image", flat=True).order_by("id")))
        self.assertEqual(before, after)
        self.assertEqual((r["created"], r["existing_images_attached"]), (0, 0))

    def test_commit_reuses_the_preview_answers(self):
        rows = [row("One", A), row("Two", B)]
        with mock.patch.object(cis, "_head", FakeCloudinary({A: 200, B: 404})):
            preview = imp.plan(rows)
        fake = FakeCloudinary({A: 404, B: 200})          # Cloudinary changed in between: the preview's answers win
        with mock.patch.object(cis, "_head", fake):
            p = imp.plan(rows, known=preview["statuses"])
            r = imp.commit_plan(p)
        self.assertEqual(fake.calls, [])
        self.assertEqual((r["images_found"], r["images_missing"]), (preview["totals"]["images_found"],
                                                                     preview["totals"]["images_missing"]))

    def test_one_retry_for_network_errors(self):
        self.run_import([row("Flaky", A), row("Down", B)], {A: [OSError("reset"), 200], B: [OSError(), OSError()]})
        self.assertEqual((self.image_of(A), self.image_of(B)), (A, ""))

    def test_large_files_are_not_checked_during_import(self):
        rows = [row(f"P{i}", ean13(f"8901234{i:05d}")) for i in range(imp.LARGE_FILE_ROWS + 1)]
        p, r, fake = self.run_import(rows, default=200)
        self.assertEqual(fake.calls, [])
        self.assertTrue(p["large_file"])
        self.assertEqual((r["created"], r["images_not_checked"]), (len(rows), len(rows)))

    @override_settings(CLOUDINARY_CLOUD_NAME="")
    def test_no_cloud_configured_means_unverified_never_attached(self):
        with mock.patch.dict("os.environ", {"CLOUDINARY_URL": ""}):
            p, _, fake = self.run_import([row("One", A)], default=200)
        self.assertEqual((fake.calls, self.image_of(A), p["totals"]["images_unverified"]), ([], "", 1))


@override_settings(CLOUDINARY_CLOUD_NAME=CLOUD)
class ImportAdminPageTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("cat_admin", password="Admin#Pass1")

    def upload(self, client, text, **extra):
        from django.core.files.uploadedfile import SimpleUploadedFile
        f = SimpleUploadedFile("p.csv", text.encode("utf-8"), content_type="text/csv")
        return client.post("/admin/catalog/masterproduct/import/", {"file": f, **extra})

    def test_preview_then_commit_shows_the_same_totals(self):
        csv_text = ("name,brand,category,pack_size,unit,barcode,mrp,tax_rate,description,image\n"
                    f"Chips,Test,Snacks,1,pc,{A},10,5,,\nNuts,Test,Snacks,1,pc,{B},10,5,,\nBad,Test,Snacks,1,pc,6.9E+11,10,5,,\n")
        self.client.force_login(self.admin)
        fake = FakeCloudinary({A: 200, B: 404})
        with mock.patch.object(cis, "_head", fake):
            prev = self.upload(self.client, csv_text)
            self.assertContains(prev, "Images found")
            self.assertContains(prev, B)                                  # listed as missing
            n_calls = len(fake.calls)
            done = self.client.post("/admin/catalog/masterproduct/import/", {"commit": "1"})
        self.assertEqual(len(fake.calls), n_calls)                        # no second check at commit
        self.assertContains(done, "Import finished")
        self.assertEqual(done.context["report"]["created"], 2)
        self.assertEqual(done.context["report"]["images_found"], prev.context["totals"]["images_found"])
        self.assertEqual(done.context["report"]["rows_with_errors"], 1)
        self.assertEqual(ProductBarcode.objects.get(code=A).product.image.name, A)

    def test_non_admin_cannot_open_the_import(self):
        user = User.objects.create_user("not_admin", password="x#Pass12345")
        self.client.force_login(user)
        r = self.client.get("/admin/catalog/masterproduct/import/")
        self.assertIn(r.status_code, (302, 403))
