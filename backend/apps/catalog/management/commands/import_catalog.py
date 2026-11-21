from django.core.management.base import BaseCommand, CommandError

from services import catalog_import_service as svc


class Command(BaseCommand):
    help = ("Bulk-import master products from a CSV or XLSX file. Columns: name,brand,category,pack_size,unit,"
            "barcode,mrp,tax_rate,description and optional image (Cloudinary public ID; blank = use the barcode). "
            "PREVIEW unless --commit. Duplicates are skipped, never merged.")

    def add_arguments(self, parser):
        parser.add_argument("path")
        parser.add_argument("--commit", action="store_true")
        parser.add_argument("--activate", action="store_true", help="Create products as ACTIVE instead of DRAFT")
        parser.add_argument("--replace-images", action="store_true",
                            help="Also replace images of products already in the catalogue")
        parser.add_argument("--no-image-check", action="store_true", help="Do not look for images (run Sync later)")

    def handle(self, path, commit, activate, replace_images=False, no_image_check=False, **opts):
        try:
            if path.lower().endswith(".xlsx"):
                rows = svc.read_xlsx(path)
            else:
                with open(path, newline="", encoding="utf-8-sig") as f:
                    rows = svc.read_csv(f.read())
        except OSError as exc:
            raise CommandError(str(exc))
        p = svc.plan(rows, replace_images=replace_images, check=not no_image_check)
        t = p["totals"]
        self.stdout.write(f"{len(p['good'])} valid row(s), {len(p['errors'])} error(s).")
        self.stdout.write(f"Images: {t['images_found']} found, {t['images_missing']} missing, "
                          f"{t['images_unverified']} could not be verified, {t['images_not_checked']} not checked, "
                          f"{t['no_barcode']} without barcode; {t['existing_images_to_attach']} for existing products.")
        for e in p["errors"]:
            self.stdout.write(self.style.ERROR(e))
        if p["missing"]:
            self.stdout.write("Missing images: " + ", ".join(p["missing"]))
        if not commit:
            self.stdout.write("Preview only. Re-run with --commit to save the valid rows.")
            return
        r = svc.commit_plan(p, activate=activate)
        self.stdout.write(self.style.SUCCESS(f"Imported {r['created']} product(s); "
                                             f"{r['existing_images_attached']} image(s) attached to existing products."))
