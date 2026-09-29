"""Isolated local browser tests only. Never use this module to serve client data."""
import os
from pathlib import Path
import tempfile

from .test_settings import *  # noqa: F403,F401

# Live browser/server threads need separate SQLite connections. Keep a unique
# on-disk test database outside the project; --keepdb avoids Windows lock races
# while the live server thread finishes closing its connection.
DATABASES = {"default": {
    "ENGINE": "django.db.backends.sqlite3",
    "NAME": ":memory:",
    "TEST": {"NAME": str(Path(tempfile.gettempdir()) / f"profit-browser-{os.getpid()}.sqlite3")},
}}
