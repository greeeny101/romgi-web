"""
Shared settings. Never import this directly — use `development` or
`production`, both of which start with `from .base import *`.
"""

from datetime import timedelta
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env.str("SECRET_KEY")
ENCRYPTION_KEY = env.str("ENCRYPTION_KEY")

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.User"

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    # Third-party
    "ninja",
    "ninja_jwt",
    "ninja_jwt.token_blacklist",
    "corsheaders",
    "channels",
    "django_celery_beat",
    "storages",
    # First-party
    "apps.common",
    "apps.accounts",
    "apps.catalog",
    "apps.ingestion",
    "apps.library",
    "apps.downloads",
    "apps.torrents",
    "apps.credentials",
    "apps.metadata",
    "apps.realtime",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
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
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": env.db_url("DATABASE_URL"),
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# --- CORS -------------------------------------------------------------
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[])

# --- Redis / Celery -----------------------------------------------------
REDIS_URL = env.str("REDIS_URL", default="redis://localhost:6379/0")

CELERY_BROKER_URL = env.str("CELERY_BROKER_URL", default=f"{REDIS_URL.rstrip('/0')}/1")
CELERY_RESULT_BACKEND = env.str("CELERY_RESULT_BACKEND", default=f"{REDIS_URL.rstrip('/0')}/1")
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"
CELERY_TASK_ROUTES = {
    "apps.ingestion.tasks.*": {"queue": "ingestion"},
    "apps.downloads.tasks.*": {"queue": "downloads"},
    # Debrid resolution is part of the download pipeline (it hands off to
    # downloads.tasks.http_download once resolved) — same queue, not its
    # own, since it's not an external-daemon integration like torrents.
    "apps.downloads.debrid.tasks.*": {"queue": "downloads"},
    "apps.torrents.tasks.*": {"queue": "torrents"},
    "apps.credentials.tasks.*": {"queue": "credentials"},
    "apps.metadata.tasks.*": {"queue": "metadata"},
}

# --- Channels -------------------------------------------------------------
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [env.str("CHANNELS_REDIS_URL", default=f"{REDIS_URL.rstrip('/0')}/2")],
        },
    },
}

# --- Django Ninja / JWT ---------------------------------------------------
NINJA_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=14),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
}

# --- qBittorrent -----------------------------------------------------------
QBITTORRENT_HOST = env.str("QBITTORRENT_HOST", default="http://localhost:8080")
QBITTORRENT_USERNAME = env.str("QBITTORRENT_USERNAME", default="admin")
QBITTORRENT_PASSWORD = env.str("QBITTORRENT_PASSWORD", default="adminadmin")
# TORRENT_WORKING_DIR and QBITTORRENT_SAVE_PATH point at the *same* shared
# volume (docker-compose's `torrent_data`) but are mounted at different
# paths in each container — Django/Celery see it at TORRENT_WORKING_DIR,
# the qBittorrent daemon sees the identical files at QBITTORRENT_SAVE_PATH.
# apps.torrents.tasks always talks to qBittorrent using the latter and
# reads the resulting files back using the former; never conflate the two.
TORRENT_WORKING_DIR = env.str("TORRENT_WORKING_DIR", default=str(BASE_DIR / "data" / "torrents"))
QBITTORRENT_SAVE_PATH = env.str("QBITTORRENT_SAVE_PATH", default="/downloads")

# --- Staged download file retention ----------------------------------------
STAGED_FILE_RETENTION_HOURS = env.int("STAGED_FILE_RETENTION_HOURS", default=24)
STAGED_FILE_UNCLAIMED_DAYS = env.int("STAGED_FILE_UNCLAIMED_DAYS", default=7)
STAGED_FILES_DIR = env.str("STAGED_FILES_DIR", default=str(BASE_DIR / "data" / "staged"))

# --- Catalog ingestion ------------------------------------------------------
CATALOG_BUILD_RETENTION = env.int("CATALOG_BUILD_RETENTION", default=2)
# A build row only leaves "running" from inside the worker that owns it, so a
# worker killed mid-run (restart, OOM) strands it there permanently — and the
# "is a build already running?" guard then refuses every manual run forever.
# Anything still running after this many hours is treated as abandoned. Must
# stay comfortably above a real full-ingestion wall time (~1.5h observed).
CATALOG_BUILD_STALE_AFTER_HOURS = env.int("CATALOG_BUILD_STALE_AFTER_HOURS", default=6)
RETROACHIEVEMENTS_API_USER = env.str("RA_API_USER", default="")
RETROACHIEVEMENTS_API_KEY = env.str("RA_API_KEY", default="")

# The NoPayStation scraper (apps/ingestion/pipeline/sources/nopaystation)
# generates RAP/ZRIF key files at ingestion time and needs somewhere to
# write them and a URL those files are actually served from — see
# apps.ingestion.api.get_ingestion_key. Read directly via os.environ by the
# (framework-agnostic) pipeline scraper too, so both sides agree without a
# Django import there; this is just the Django-facing copy.
NOPAYSTATION_KEYS_DIR = env.str("NOPAYSTATION_KEYS_DIR", default=str(BASE_DIR / "data" / "nopaystation"))

# --- External metadata / debrid provider defaults (per-user keys live in
# apps.credentials.EncryptedCredential; these are only ingestion-time secrets) --
