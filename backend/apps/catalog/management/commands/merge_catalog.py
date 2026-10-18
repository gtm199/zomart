from django.core.management.base import BaseCommand, CommandError

from services import catalog_service
from services.exceptions import BusinessRuleError


class Command(BaseCommand):
    help = ("Explicitly merge a duplicate into the right record. Preview unless --commit.\n"
            "  merge_catalog product 12 7 --commit   (product 12 is the duplicate, 7 is the one to keep)")

    def add_arguments(self, parser):
        parser.add_argument("kind", choices=["product", "brand", "category"])
        parser.add_argument("source", type=int, help="the duplicate (it is retired)")
        parser.add_argument("target", type=int, help="the record to keep")
        parser.add_argument("--commit", action="store_true")

    def handle(self, kind, source, target, commit, **opts):
        fn = {"product": catalog_service.merge_products, "brand": catalog_service.merge_brands,
              "category": catalog_service.merge_categories}[kind]
        try:
            report = fn(source, target, commit=commit)
        except BusinessRuleError as exc:
            raise CommandError(exc.message)
        for k, v in report.items():
            self.stdout.write(f"{k}: {v}")
        self.stdout.write(self.style.SUCCESS("Merged." if commit else "Preview only. Add --commit to merge."))