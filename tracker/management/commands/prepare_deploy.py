"""Migrate and initialize without requiring a paid provider shell."""
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = "Apply migrations and initialize an empty deployment before starting the server."

    def handle(self, *args, **options):
        # The app may use Neon's transaction pooler, but a session advisory lock
        # for migrations must use the direct host for the same database.
        lock_id = 7319041201
        postgres = connection.vendor == "postgresql"
        if postgres:
            host = connection.settings_dict.get("HOST", "")
            if host.endswith(".neon.tech") and "-pooler." in host:
                connection.close()
                connection.settings_dict["HOST"] = host.replace("-pooler.", ".", 1)
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_lock(%s)", [lock_id])
        try:
            call_command("migrate", interactive=False, stdout=self.stdout, stderr=self.stderr)
            call_command("bootstrap_workspace", stdout=self.stdout, stderr=self.stderr)
        finally:
            if postgres:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_unlock(%s)", [lock_id])
