"""Disposable on-disk database for concurrent local stress tests."""
import os
from pathlib import Path
import tempfile

from .test_settings import *  # noqa: F403,F401

DATABASES = {"default": {
    "ENGINE": "django.db.backends.sqlite3",
    "NAME": ":memory:",
    "OPTIONS": {"timeout": 30},
    "TEST": {"NAME": str(Path(tempfile.gettempdir()) / f"profit-stress-{os.getpid()}.sqlite3")},
}}
