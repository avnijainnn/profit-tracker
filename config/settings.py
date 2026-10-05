"""Local-first configuration. See README before deploying with real data."""
import os
import secrets
from pathlib import Path
from datetime import timedelta
import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent
DEBUG = os.environ.get("DJANGO_DEBUG", "true").lower() == "true"
DEMO_MODE = os.environ.get("APP_ENV") == "demo"
PASSWORD_RESET_ENABLED = os.environ.get(
    "ENABLE_PASSWORD_RESET", "false" if DEMO_MODE else "true"
).lower() == "true"
INITIAL_OWNER_SETUP_TOKEN = os.environ.get("INITIAL_OWNER_SETUP_TOKEN", "").strip()
DEPLOYED = bool(os.environ.get("RENDER")) or os.environ.get("APP_ENV") in ("production", "staging", "demo")
if DEPLOYED and DEBUG:
    raise RuntimeError("Hosted environments require DJANGO_DEBUG=false")
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if not DEBUG:
        raise RuntimeError("DJANGO_SECRET_KEY is required when DJANGO_DEBUG=false")
    # Random per-project development secret; never committed or included in exports.
    secret_file = BASE_DIR / ".local-secret"
    if not secret_file.exists():
        try:
            with secret_file.open("x", encoding="utf-8") as handle:
                handle.write(secrets.token_urlsafe(48))
            secret_file.chmod(0o600)
        except FileExistsError:
            pass
    SECRET_KEY = secret_file.read_text(encoding="utf-8").strip()

render_hostname = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "").strip()
allowed_hosts = os.environ.get("DJANGO_ALLOWED_HOSTS") or render_hostname
ALLOWED_HOSTS = [h.strip() for h in (allowed_hosts or "localhost,127.0.0.1,[::1]").split(",") if h.strip()]
if not DEBUG and (not allowed_hosts or "*" in ALLOWED_HOSTS):
    raise RuntimeError("Set explicit DJANGO_ALLOWED_HOSTS for production; wildcards are not allowed")
csrf_origins = os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS") or (f"https://{render_hostname}" if render_hostname else "")
CSRF_TRUSTED_ORIGINS = [v.strip() for v in csrf_origins.split(",") if v.strip()]
if not DEBUG and (len(SECRET_KEY) < 50 or not CSRF_TRUSTED_ORIGINS):
    raise RuntimeError("Production needs a secret of at least 50 characters and explicit HTTPS CSRF trusted origins")
if not DEBUG and any(not origin.startswith("https://") or "*" in origin for origin in CSRF_TRUSTED_ORIGINS):
    raise RuntimeError("Use explicit HTTPS origins without wildcards")
INSTALLED_APPS = [
    "django.contrib.admin", "django.contrib.auth", "django.contrib.contenttypes",
    "django.contrib.sessions", "django.contrib.messages", "django.contrib.staticfiles",
    "axes", "tracker",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "tracker.security.AuthenticatedNoCacheMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "axes.middleware.AxesMiddleware",
]
ROOT_URLCONF = "config.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"], "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
        "tracker.context_processors.review_month",
    ]},
}]
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3",
                         "OPTIONS": {"timeout": 30}}}
database_url = os.environ.get("DATABASE_URL", "")
if database_url:
    if not database_url.startswith(("postgres://", "postgresql://")):
        raise RuntimeError("DATABASE_URL must point to PostgreSQL")
    DATABASES["default"] = dj_database_url.parse(database_url, conn_max_age=60, conn_health_checks=True,
        ssl_require=os.environ.get("DATABASE_SSL_REQUIRE", "true").lower() == "true")
elif not DEBUG:
    raise RuntimeError("Production requires DATABASE_URL; SQLite fallback is disabled")
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LANGUAGE_CODE = "en-in"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_ROOT = Path(os.environ.get("PRODUCT_MEDIA_ROOT", BASE_DIR / "media"))
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_SECURE = not DEBUG
SECURE_SSL_REDIRECT = not DEBUG
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_HSTS_SECONDS = 31536000 if not DEBUG else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = False
# Preload is optional and requires a deliberate domain-owner decision. HTTPS/HSTS
# remain mandatory; only the suggestion to opt into the browser preload list is waived.
# Email-based Axes lockout is deliberate: it applies across IPs, cookies and
# user agents, without trusting forwarded headers. Covered by the lockout test.
SILENCED_SYSTEM_CHECKS = ["security.W021", "axes.W006"]
if os.environ.get("TRUST_PROXY_HTTPS", "false").lower() == "true":
    # Only behind a trusted proxy that removes/spoofs no incoming forwarding headers.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_REDIRECT_EXEMPT = [r"^healthz/$"]
SESSION_COOKIE_AGE = 8 * 60 * 60
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_NAME = "__Host-profit_session" if not DEBUG else "profit_session"
CSRF_COOKIE_NAME = "__Host-profit_csrf" if not DEBUG else "profit_csrf"
DATA_UPLOAD_MAX_MEMORY_SIZE = 1024 * 1024
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage" if DEBUG
                else "tracker.storage.DatabaseStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
AUTHENTICATION_BACKENDS = ["axes.backends.AxesStandaloneBackend", "tracker.authentication.EmailBackend"]
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = timedelta(minutes=15)
AXES_LOCKOUT_PARAMETERS = ["username"]
AXES_USERNAME_CALLABLE = "tracker.security.login_identifier"
AXES_RESET_ON_SUCCESS = True
AXES_SENSITIVE_PARAMETERS = ["username", "email", "password", "token"]
AXES_LOCKOUT_TEMPLATE = "registration/locked_out.html"
AXES_CLIENT_IP_CALLABLE = "tracker.security.no_client_ip"
EMAIL_BACKEND = (
    "django.core.mail.backends.smtp.EmailBackend"
    if not DEBUG and PASSWORD_RESET_ENABLED
    else "django.core.mail.backends.console.EmailBackend"
)
EMAIL_HOST = os.environ.get("EMAIL_HOST", "")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_TIMEOUT = 15
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "")
PASSWORD_RESET_TIMEOUT = 3600
if not DEBUG and PASSWORD_RESET_ENABLED and (not EMAIL_HOST or not DEFAULT_FROM_EMAIL):
    raise RuntimeError("Configure EMAIL_HOST and DEFAULT_FROM_EMAIL before enabling production password recovery")
if not DEBUG:
    LOGGING = {
        "version": 1, "disable_existing_loggers": True,
        "filters": {"redact": {"()": "config.logging.RedactOperationalLogs"}},
        "formatters": {"safe": {"format": "{levelname} {name} {message}", "style": "{"}},
        "handlers": {"console": {"class": "logging.StreamHandler", "filters": ["redact"], "formatter": "safe"}},
        "root": {"handlers": ["console"], "level": "WARNING"},
        "loggers": {"django": {"handlers": ["console"], "level": "WARNING", "propagate": False},
                    "axes": {"handlers": ["console"], "level": "WARNING", "propagate": False}},
    }
