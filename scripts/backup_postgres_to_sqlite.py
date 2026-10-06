"""Create a verified, private SQLite recovery copy of the live workspace.

The PostgreSQL source is only read. Run with DATABASE_URL in the environment or
pass --connection-file pointing to a private, ignored file containing one
DATABASE_URL=... line.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
from io import StringIO
import json
import os
from pathlib import Path
import sqlite3
import sys


PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--connection-file", type=Path)
parser.add_argument("--output-dir", type=Path)
args = parser.parse_args()

if args.connection_file:
    line = args.connection_file.read_text(encoding="utf-8").strip()
    if not line.startswith("DATABASE_URL=") or "\n" in line:
        parser.error("The private connection file must contain one DATABASE_URL=... line.")
    os.environ["DATABASE_URL"] = line.split("=", 1)[1]
if not os.environ.get("DATABASE_URL", "").startswith(("postgres://", "postgresql://")):
    parser.error("Set a PostgreSQL DATABASE_URL or pass --connection-file.")

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
os.environ.setdefault("DJANGO_DEBUG", "true")

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402
from django.core.management import call_command  # noqa: E402
from django.db import connection, connections, transaction  # noqa: E402

if connection.vendor != "postgresql":
    parser.error("The source must be PostgreSQL.")

output_dir = args.output_dir or (
    PROJECT / "backups" / ("live-sqlite-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S"))
)
output_dir = output_dir.resolve()
output_dir.mkdir(parents=True, exist_ok=False)
fixture_path = output_dir / "workspace.json"
sqlite_path = output_dir / "workspace.sqlite3"

# All migration and fixture writes target only this new SQLite alias.
settings.DATABASES["backup"] = {"ENGINE": "django.db.backends.sqlite3", "NAME": str(sqlite_path)}
connections.databases["backup"] = settings.DATABASES["backup"]
connections.configure_settings(connections.databases)
call_command("migrate", database="backup", interactive=False, verbosity=0)

with transaction.atomic(using="default"):
    with connection.cursor() as cursor:
        cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
    with fixture_path.open("w", encoding="utf-8") as fixture:
        call_command("dumpdata", "auth.user", "tracker", database="default", stdout=fixture, verbosity=0)

call_command("loaddata", str(fixture_path), database="backup", verbosity=0)

source = json.loads(fixture_path.read_text(encoding="utf-8"))
sqlite_export = StringIO()
call_command("dumpdata", "auth.user", "tracker", database="backup", stdout=sqlite_export, verbosity=0)
restored = json.loads(sqlite_export.getvalue())
key = lambda row: (row["model"], str(row["pk"]))
if sorted(source, key=key) != sorted(restored, key=key):
    raise RuntimeError("SQLite content differs from the PostgreSQL snapshot.")

with sqlite3.connect(sqlite_path.as_uri() + "?mode=ro", uri=True) as check:
    if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise RuntimeError("SQLite integrity check failed.")
    counts = Counter(row["model"] for row in source)
    if check.execute("SELECT COUNT(*) FROM auth_user").fetchone()[0] != counts["auth.user"]:
        raise RuntimeError("SQLite user count differs from the snapshot.")
    if check.execute("SELECT COUNT(*) FROM tracker_entry").fetchone()[0] != counts["tracker.entry"]:
        raise RuntimeError("SQLite entry count differs from the snapshot.")
    if check.execute("SELECT COUNT(*) FROM tracker_storedupload").fetchone()[0] != counts["tracker.storedupload"]:
        raise RuntimeError("SQLite stored photo count differs from the snapshot.")

connections["backup"].close()
print("sqlite_backup:", sqlite_path)
print("sqlite_bytes:", sqlite_path.stat().st_size)
print("sqlite_sha256:", hashlib.sha256(sqlite_path.read_bytes()).hexdigest())
print("verified_counts:", {
    "users": counts["auth.user"], "entries": counts["tracker.entry"],
    "products": counts["tracker.product"], "stored_photos": counts["tracker.storedupload"],
})
