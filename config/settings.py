"""Django settings for Stacks.

Everything deployment-specific comes from environment variables so the same
image works for anyone who self-hosts it. See .env.example.
"""

import os
import secrets
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


DEBUG = env_bool("STACKS_DEBUG", False)

# Data directory holds the SQLite database, downloaded covers, and (if no key
# is supplied) a generated secret key. Mount it as a volume.
DATA_DIR = Path(os.environ.get("STACKS_DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)


def _load_secret_key() -> str:
    supplied = os.environ.get("STACKS_SECRET_KEY")
    if supplied:
        return supplied
    # No key supplied: generate one once and persist it in the data volume so
    # sessions survive restarts. Safer than shipping a default key.
    key_file = DATA_DIR / ".secret_key"
    if key_file.exists():
        return key_file.read_text().strip()
    key = secrets.token_urlsafe(64)
    key_file.write_text(key)
    key_file.chmod(0o600)
    return key


SECRET_KEY = _load_secret_key()

# Loopback names are always allowed so the container health check works no
# matter which public hostname is configured.
ALLOWED_HOSTS = sorted({*env_list("STACKS_ALLOWED_HOSTS", "localhost"), "localhost", "127.0.0.1"})
# Needed when serving over HTTPS behind a reverse proxy, e.g.
# STACKS_CSRF_TRUSTED_ORIGINS=https://books.example.com
CSRF_TRUSTED_ORIGINS = env_list("STACKS_CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "whitenoise.runserver_nostatic",
    "django.contrib.staticfiles",
    "catalog",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # Everything requires login unless explicitly exempted.
    "catalog.middleware.LoginRequiredMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": DATA_DIR / "db.sqlite3",
        "OPTIONS": {
            "timeout": 20,
            "init_command": "PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON;",
            "transaction_mode": "IMMEDIATE",
        },
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = os.environ.get("STACKS_TIME_ZONE", "UTC")
USE_I18N = False
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
# The hashed-manifest storage needs `collectstatic` to have run, which it hasn't
# in local development or under `manage.py test`.
if DEBUG or (len(sys.argv) > 1 and sys.argv[1] == "test"):
    STORAGES["staticfiles"] = {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}

# Covers are served through an authenticated view, never as public static files.
COVERS_DIR = DATA_DIR / "covers"
COVERS_DIR.mkdir(parents=True, exist_ok=True)

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "library"
LOGOUT_REDIRECT_URL = "login"

# Stay signed in on a phone for a long time.
SESSION_COOKIE_AGE = 60 * 60 * 24 * 90
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"

# Behind a TLS-terminating proxy (Caddy, nginx, Traefik) set STACKS_HTTPS=true.
if env_bool("STACKS_HTTPS", False):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30

# Optional contact string sent in the User-Agent to Open Library, which asks
# API users to identify themselves.
STACKS_CONTACT = os.environ.get("STACKS_CONTACT", "")

# Metadata lookup behaviour.
LOOKUP_TIMEOUT = float(os.environ.get("STACKS_LOOKUP_TIMEOUT", "8"))
COVER_MAX_BYTES = 5 * 1024 * 1024
COVER_MAX_PIXELS = 1000  # longest side after resize
# Only these hosts may be fetched when downloading cover images.
COVER_ALLOWED_HOSTS = (
    "covers.openlibrary.org",
    "archive.org",
    "books.google.com",
    "books.googleusercontent.com",
)

PAGE_SIZE = 48

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": os.environ.get("STACKS_LOG_LEVEL", "INFO")},
}
