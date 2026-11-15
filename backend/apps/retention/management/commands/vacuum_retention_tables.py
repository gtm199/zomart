from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import connection

LABELS = ["sales.SaleItem", "orders.Order", "orders.OrderItem", "orders.OrderEvent", "orders.DeliveryTrack",
          "shops.ShopNotification", "shops.AuditLog", "admin.LogEntry", "accounts.PasswordResetCode"]


class Command(BaseCommand):
    help = ("PostgreSQL only. After a big retention cleanup, lets the database reuse the space freed by the deleted rows "
            "(VACUUM). Add --full to also give the disk space back to the server: that locks each table while it runs, "
            "so do it at night, not while shops are billing.")

    def add_arguments(self, parser):
        parser.add_argument("--full", action="store_true")

    def handle(self, full=False, **options):
        if connection.vendor != "postgresql":
            self.stdout.write("Not PostgreSQL: nothing to do.")
            return
        for label in LABELS:
            try:
                table = apps.get_model(label)._meta.db_table
            except LookupError:
                continue
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_total_relation_size(%s::regclass)", [table])
                before = cursor.fetchone()[0]
                cursor.execute(f'VACUUM ({"FULL, " if full else ""}ANALYZE) "{table}"')
                cursor.execute("SELECT pg_total_relation_size(%s::regclass)", [table])
                after = cursor.fetchone()[0]
            self.stdout.write(f"{table}: {before / 1048576:.1f} MB -> {after / 1048576:.1f} MB")
        self.stdout.write(self.style.SUCCESS("Done."))