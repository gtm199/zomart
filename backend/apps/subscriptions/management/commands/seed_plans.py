from django.core.management.base import BaseCommand

from services import subscription_service


class Command(BaseCommand):
    help = "Create the default Starter/Standard/Premium plans if they do not exist."

    def handle(self, *args, **options):
        subscription_service.seed_default_plans()
        self.stdout.write(self.style.SUCCESS("Subscription plans ready."))
