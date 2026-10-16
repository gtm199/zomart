import csv

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.catalog.models import Brand, Category, MasterProduct, ProductBarcode
from services import barcode_service, catalog_service

UNITS = {u.value for u in MasterProduct.Unit}


class Command(BaseCommand):
    help = ("Bulk-import master products from CSV. Columns: name,brand,category,pack_size,unit,barcode,mrp,tax_rate,description. "
            "Runs as a PREVIEW unless --commit is given. Rows that look like duplicates are skipped, never merged.")

    def add_arguments(self, parser):
        parser.add_argument("csv_path")
        parser.add_argument("--commit", action="store_true")
        parser.add_argument("--activate", action="store_true", help="Create products as ACTIVE instead of DRAFT")

    def handle(self, csv_path, commit, activate, **opts):
        try:
            handle = open(csv_path, newline="", encoding="utf-8-sig")
        except OSError as exc:
            raise CommandError(str(exc))
        ok, errors = [], []
        seen_barcodes = set()
        with handle:
            for n, row in enumerate(csv.DictReader(handle), start=2):
                try:
                    ok.append(self._validate(row, seen_barcodes))
                except ValueError as exc:
                    errors.append(f"row {n}: {exc}")
        self.stdout.write(f"{len(ok)} valid row(s), {len(errors)} error(s).")
        for e in errors:
            self.stdout.write(self.style.ERROR(e))
        if not commit:
            self.stdout.write("Preview only. Re-run with --commit to save the valid rows.")
            return
        with transaction.atomic():
            for d in ok:
                brand = Brand.objects.get_or_create(name=d["brand"])[0] if d["brand"] else None
                category = None
                if d["category"]:
                    category = Category.objects.get_or_create(name=d["category"], parent=None)[0]
                product = MasterProduct.objects.create(
                    name=d["name"], brand=brand, category=category, pack_size=d["pack_size"], unit=d["unit"],
                    mrp=d["mrp"], tax_rate=d["tax_rate"], description=d["description"],
                    status=MasterProduct.Status.ACTIVE if activate else MasterProduct.Status.DRAFT)
                if d["barcode"]:
                    ProductBarcode.objects.create(product=product, code=d["barcode"][0], symbology=d["barcode"][1], is_primary=True)
        self.stdout.write(self.style.SUCCESS(f"Imported {len(ok)} product(s)."))

    def _validate(self, row, seen):
        from decimal import Decimal, InvalidOperation
        name = (row.get("name") or "").strip()
        if not name:
            raise ValueError("name is required")
        unit = (row.get("unit") or "pc").strip().lower()
        if unit not in UNITS:
            raise ValueError(f"unit must be one of {sorted(UNITS)}")
        try:
            pack = Decimal((row.get("pack_size") or "1").strip())
            mrp = Decimal(row["mrp"]) if (row.get("mrp") or "").strip() else None
            tax = Decimal(row["tax_rate"]) if (row.get("tax_rate") or "").strip() else None
        except InvalidOperation:
            raise ValueError("pack_size, mrp and tax_rate must be numbers")
        brand_name = (row.get("brand") or "").strip()
        brand = Brand.objects.filter(name=brand_name).first() if brand_name else None
        if catalog_service.find_duplicates(name, brand.pk if brand else None, pack, unit).exists():
            raise ValueError("possible duplicate of an existing product (skipped, not merged)")
        barcode = None
        raw = (row.get("barcode") or "").strip()
        if raw:
            code, sym = barcode_service.validate_barcode(raw)  # raises ValueError
            if code in seen or ProductBarcode.objects.filter(code=code).exists():
                raise ValueError(f"barcode {code} already registered (barcode conflict)")
            seen.add(code)
            barcode = (code, sym)
        return {"name": name, "brand": brand_name, "category": (row.get("category") or "").strip(),
                "pack_size": pack, "unit": unit, "mrp": mrp, "tax_rate": tax,
                "description": (row.get("description") or "").strip(), "barcode": barcode}
