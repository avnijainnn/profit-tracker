"""Migrate and initialize without requiring a paid provider shell."""
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = "Apply migrations and initialize an empty deployment before starting the server."

    def handle(self, *args, **options):
        # Serialize overlapping deploys on the direct PostgreSQL connection.
        # This is a session lock: do not use a transaction-pooler DATABASE_URL.
        lock_id = 7319041201
        postgres = connection.vendor == "postgresql"
        if postgres:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_lock(%s)", [lock_id])
        try:
            call_command("migrate", interactive=False, stdout=self.stdout, stderr=self.stderr)
            call_command("bootstrap_workspace", stdout=self.stdout, stderr=self.stderr)
        finally:
            if postgres:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_unlock(%s)", [lock_id])
