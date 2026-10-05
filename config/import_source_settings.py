"""Read a private SQLite snapshot for the one-time workspace transfer only."""

import os
from pathlib import Path

from .settings import *  # noqa: F403,F401


source_db = os.environ.get("IMPORT_SOURCE_DB", "")
if not source_db or os.environ.get("IMPORT_SOURCE_ONLY") != "true":
    raise RuntimeError("This settings module is only for the private SQLite import process")

build_test_source = os.environ.get("IMPORT_BUILD_TEST_SOURCE") == "true"
if build_test_source and not DEBUG:  # noqa: F405
    raise RuntimeError("Writable import source is only for tests")

DATABASES = {"default": {
    "ENGINE": "django.db.backends.sqlite3",
    "NAME": source_db if build_test_source else Path(source_db).resolve().as_uri() + "?mode=ro",
    "OPTIONS": {} if build_test_source else {"uri": True},
}}
