"""Test configuration: never deploy this settings module."""
from .settings import *  # noqa: F403,F401

AXES_ENABLED = False
# Test fixtures exercise authentication behavior, not password hashing speed.
# Production settings retain Django's secure default password hashers.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
