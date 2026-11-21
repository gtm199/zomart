from django.core.management.base import BaseCommand, CommandError

from apps.catalog.models import Brand, Category
from services import image_sync_service
from services.exceptions import BusinessRuleError


class Command(BaseCommand):
    help = ("Attach Cloudinary images (public ID = barcode) to catalogue products that have no image. Uses plain HEAD "
            "requests, never the Admin API. Resumable: running it again continues an unfinished run with the same options.")

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Only count what would be attached; change nothing")
        parser.add_argument("--replace", action="store_true", help="Also replace images products already have")
        parser.add_argument("--limit", type=int, default=None, help="Stop after this many products (resume later)")
        parser.add_argument("--category", default=None, help="Category id or exact name (includes its sub-categories)")
        parser.add_argument("--brand", default=None, help="Brand id or exact name")
        parser.add_argument("--batch", type=int, default=image_sync_service.BATCH, help="Products per chunk")

    @staticmethod
    def _find(model, value, label):
        if value is None:
            return None
        found = model.objects.filter(pk=value).first() if str(value).isdigit() else None
        found = found or model.objects.filter(name__iexact=value).first()
        if found is None:
            raise CommandError(f"{label} not found: {value}")
        return found

    def handle(self, dry_run=False, replace=False, limit=None, category=None, brand=None, batch=50, **opts):
        cat = self._find(Category, category, "Category")
        br = self._find(Brand, brand, "Brand")
        try:
            r = image_sync_service.run_all(
                None, dry_run=dry_run, replace=replace, category=cat, brand=br, limit=limit, batch=batch,
                progress=lambda r: self.stdout.write(f"  ... {r['processed']} of {r['total']} looked at, "
                                                     f"{r['remaining']} remaining"))
        except BusinessRuleError as exc:
            raise CommandError(exc.message)
        verb = "would be attached" if dry_run else "attached"
        self.stdout.write(self.style.SUCCESS(
            f"Run #{r['run']} {'(preview) ' if dry_run else ''}{'finished' if r['finished'] else 'paused'}: "
            f"{r['processed']} looked at, {r['attached']} {verb}, {r['still_missing']} still missing, "
            f"{r['unverified']} could not be verified, {r['skipped']} skipped, {r['remaining']} remaining."))
        if not r["finished"]:
            self.stdout.write("Run the same command again to continue.")
