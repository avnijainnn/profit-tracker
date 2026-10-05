"""Read a private SQLite snapshot for the one-time workspace transfer only."""

import os
from pathlib import Path

from .settings import *  # noqa: F403,F401


source_db = os.environ.get("IMPORT_SOURCE_DB", "")
if not source_db or os.environ.get("IMPORT_SOURCE_ONLY") != "true":
    raise RuntimeError("This settings module is only for the private SQLite import process")

DATABASES = {"default": {
    "ENGINE": "django.db.backends.sqlite3",
    "NAME": Path(source_db).resolve().as_uri() + "?mode=ro",
    "OPTIONS": {"uri": True},
}}
