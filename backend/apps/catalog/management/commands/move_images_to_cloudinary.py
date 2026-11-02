from django.conf import settings
from django.core.files import File
from django.core.files.storage import FileSystemStorage, default_storage
from django.core.management.base import BaseCommand, CommandError

from apps.catalog.models import MasterProduct


class Command(BaseCommand):
    help = ("One time: upload product pictures that are still on the server's disk to Cloudinary. "
            "Preview unless --commit. Safe to run twice.")

    def add_arguments(self, parser):
        parser.add_argument("--commit", action="store_true")

    def handle(self, commit, **options):
        if not hasattr(default_storage, "thumbnail_url"):
            raise CommandError("Cloudinary is not switched on. Set CLOUDINARY_URL first.")
        local = FileSystemStorage(location=settings.MEDIA_ROOT)
        moved = missing = 0
        for product in MasterProduct.objects.exclude(image=""):
            name = product.image.name
            if not local.exists(name):
                missing += 1
                self.stdout.write(f"not on the disk (upload it again in the admin): product {product.pk} {name}")
                continue
            moved += 1
            if commit:
                with local.open(name, "rb") as f:
                    new_name = default_storage.save(name, File(f))
                MasterProduct.objects.filter(pk=product.pk).update(image=new_name)
        verb = "moved" if commit else "can be moved"
        self.stdout.write(self.style.SUCCESS(f"{moved} picture(s) {verb}, {missing} missing."))