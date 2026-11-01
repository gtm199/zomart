from django.core.management.base import BaseCommand

from apps.catalog.models import MasterProduct


class Command(BaseCommand):
    help = "Make small thumbnails for products that have an image but no thumbnail yet."

    def handle(self, *args, **options):
        n = 0
        for product in MasterProduct.objects.exclude(image="").filter(thumbnail=""):
            product.make_thumbnail()
            n += 1
        self.stdout.write(self.style.SUCCESS(f"{n} product(s) processed."))