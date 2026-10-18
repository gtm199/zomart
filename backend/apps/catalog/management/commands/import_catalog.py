from django.core.management.base import BaseCommand, CommandError

from services import catalog_import_service as svc


class Command(BaseCommand):
    help = ("Bulk-import master products from a CSV or XLSX file. Columns: name,brand,category,pack_size,unit,"
            "barcode,mrp,tax_rate,description. PREVIEW unless --commit. Duplicates are skipped, never merged.")

    def add_arguments(self, parser):
        parser.add_argument("path")
        parser.add_argument("--commit", action="store_true")
        parser.add_argument("--activate", action="store_true", help="Create products as ACTIVE instead of DRAFT")

    def handle(self, path, commit, activate, **opts):
        try:
            if path.lower().endswith(".xlsx"):
                rows = svc.read_xlsx(path)
            else:
                with open(path, newline="", encoding="utf-8-sig") as f:
                    rows = svc.read_csv(f.read())
        except OSError as exc:
            raise CommandError(str(exc))
        good, errors = svc.validate_rows(rows)
        self.stdout.write(f"{len(good)} valid row(s), {len(errors)} error(s).")
        for e in errors:
            self.stdout.write(self.style.ERROR(e))
        if not commit:
            self.stdout.write("Preview only. Re-run with --commit to save the valid rows.")
            return
        self.stdout.write(self.style.SUCCESS(f"Imported {svc.commit_rows(good, activate)} product(s)."))