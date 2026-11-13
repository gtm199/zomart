from django.core.management.base import BaseCommand

from apps.shops.models import Shop
from services import retention_service


class Command(BaseCommand):
    help = ("The daily data retention cleanup. Each shop is handled on its own settings, and only once a day. "
            "Shops that have not switched retention on are skipped.")

    def add_arguments(self, parser):
        parser.add_argument("--shop", type=int, help="only this shop (its id)")
        parser.add_argument("--force", action="store_true", help="run again even if this shop already ran today")

    def handle(self, shop=None, force=False, **options):
        if shop:
            results = [retention_service.run_for_shop(Shop.objects.get(pk=shop), force=force)]
        else:
            results = retention_service.run_all(force=force)
        for r in results:
            self.stdout.write(str(r))
        self.stdout.write(self.style.SUCCESS(f"{len(results)} shop(s) processed."))