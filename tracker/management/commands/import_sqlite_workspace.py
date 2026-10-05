"""Copy one existing SQLite workspace into an empty PostgreSQL deployment."""

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from collections import Counter
from contextlib import closing
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from tracker.models import Product, StoredUpload


MODEL_LABELS = (
    "auth.user", "tracker.account", "tracker.category", "tracker.subcategory",
    "tracker.product", "tracker.inventorylot", "tracker.entry",
    "tracker.stockmovement", "tracker.lotdepletion", "tracker.banktally",
    "tracker.changelog", "tracker.submission", "tracker.monthreview",
    "tracker.stockreversal", "tracker.recoverythrottle",
)


def normalized_records(raw):
    records = json.loads(raw)
    return sorted(records, key=lambda item: (item["model"], str(item["pk"])))


class Command(BaseCommand):
    help = "Read a SQLite workspace and optionally import it into an empty PostgreSQL database."

    def add_arguments(self, parser):
        parser.add_argument("--source-db", required=True)
        parser.add_argument("--media-root", required=True)
        parser.add_argument("--apply", action="store_true", help="Write to the empty PostgreSQL destination")

    def handle(self, *args, **options):
        source_path = Path(options["source_db"]).expanduser().resolve()
        media_root = Path(options["media_root"]).expanduser().resolve()
        if not source_path.is_file():
            raise CommandError("Source SQLite file does not exist.")
        if not media_root.is_dir():
            raise CommandError("Source media directory does not exist.")
        if options["apply"] and connection.vendor != "postgresql":
            raise CommandError("--apply requires a PostgreSQL DATABASE_URL.")

        with TemporaryDirectory(prefix="profit-workspace-import-") as temporary:
            temporary = Path(temporary)
            snapshot = temporary / "source.sqlite3"
            with closing(sqlite3.connect(source_path.as_uri() + "?mode=ro", uri=True)) as source:
                with closing(sqlite3.connect(snapshot)) as copy:
                    source.backup(copy)
            with closing(sqlite3.connect(snapshot.as_uri() + "?mode=ro", uri=True)) as source:
                if source.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise CommandError("The SQLite source failed its integrity check.")
                migrations = {row[0] for row in source.execute(
                    "SELECT name FROM django_migrations WHERE app='tracker'"
                )}
                if "0012_allow_empty_audit_metadata" not in migrations:
                    raise CommandError("The SQLite source needs migration 0012 before transfer.")
                users = source.execute("SELECT COUNT(*) FROM auth_user").fetchone()[0]
                if users != 1:
                    raise CommandError("Expected exactly one existing user in the SQLite source.")
                if source.execute("SELECT COUNT(*) FROM auth_user_groups").fetchone()[0] or source.execute(
                    "SELECT COUNT(*) FROM auth_user_user_permissions"
                ).fetchone()[0]:
                    raise CommandError("User groups or direct permissions need a separate reviewed transfer.")
                if source.execute("SELECT COUNT(*) FROM tracker_changelog WHERE action='demo_seeded'").fetchone()[0]:
                    raise CommandError("The source contains demo seed records; review it before transfer.")
                photo_names = [row[0] for row in source.execute(
                    "SELECT photo FROM tracker_product WHERE photo IS NOT NULL AND photo != ''"
                )]
                if len(photo_names) != len(set(photo_names)):
                    raise CommandError("Two products reference the same photo path; review the source.")
                photos = {}
                for name in photo_names:
                    photo_path = (media_root / name).resolve()
                    if not photo_path.is_relative_to(media_root) or not photo_path.is_file():
                        raise CommandError("A referenced product photo is missing or outside the media directory.")
                    photos[name] = photo_path.read_bytes()

            fixture = temporary / "workspace.json"
            source_environment = os.environ.copy()
            source_environment["DJANGO_SETTINGS_MODULE"] = "config.import_source_settings"
            source_environment["IMPORT_SOURCE_DB"] = str(snapshot)
            source_environment["IMPORT_SOURCE_ONLY"] = "true"
            with fixture.open("w", encoding="utf-8") as stream:
                result = subprocess.run(
                    [sys.executable, str(settings.BASE_DIR / "manage.py"), "dumpdata",
                     *MODEL_LABELS, "--settings=config.import_source_settings"],
                    cwd=settings.BASE_DIR, env=source_environment, stdout=stream,
                    stderr=subprocess.PIPE, text=True, check=False,
                )
            if result.returncode:
                raise CommandError("SQLite fixture export failed: " + result.stderr[-1000:])
            source_json = fixture.read_text(encoding="utf-8")
            source_records = normalized_records(source_json)
            source_counts = Counter(item["model"] for item in source_records)
            if source_counts["auth.user"] != 1:
                raise CommandError("The export did not contain exactly one user.")
            self.stdout.write(f"Source ready: {source_counts['auth.user']} user, "
                              f"{source_counts['tracker.entry']} entries, "
                              f"{source_counts['tracker.product']} products, "
                              f"{len(photos)} photos.")
            self.stdout.write("Source SQLite and media files were not changed.")
            if not options["apply"]:
                self.stdout.write("Dry run only. No destination data was changed.")
                return

            # Never merge into, or overwrite, a database that already has records.
            for label in MODEL_LABELS:
                if apps.get_model(label)._base_manager.exists():
                    raise CommandError("PostgreSQL destination already contains user or workspace data; nothing imported.")
            if StoredUpload.objects.exists():
                raise CommandError("PostgreSQL destination already contains photos; nothing imported.")

            with transaction.atomic():
                if connection.vendor == "postgresql":
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [7319041202])
                if get_user_model().objects.exists():
                    raise CommandError("A user was created in PostgreSQL during preflight; nothing imported.")
                call_command("loaddata", str(fixture), verbosity=0, stdout=StringIO())
                for name, data in photos.items():
                    StoredUpload.objects.create(path=name, data=data)
                target_fixture = StringIO()
                call_command("dumpdata", *MODEL_LABELS, database="default", stdout=target_fixture, verbosity=0)
                if normalized_records(target_fixture.getvalue()) != source_records:
                    raise CommandError("Post-import record verification failed; transaction rolled back.")
                if Product.objects.exclude(photo="").count() != len(photos):
                    raise CommandError("Post-import photo count failed; transaction rolled back.")
                for name, data in photos.items():
                    stored = StoredUpload.objects.get(path=name).data
                    if hashlib.sha256(bytes(stored)).digest() != hashlib.sha256(data).digest():
                        raise CommandError("Post-import photo verification failed; transaction rolled back.")
            self.stdout.write(self.style.SUCCESS(
                "Workspace transferred and verified. The client can sign in with the existing credentials."
            ))
