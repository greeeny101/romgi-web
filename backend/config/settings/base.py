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

# The SPA is served from a different origin than the API, so fetch() can only
# read CORS-safelisted response headers. Content-Disposition isn't one of them:
# without this, apiDownload's filename came back null on every save and the
# client fell back to DownloadTask.title — which is the game name with no
# extension, so "Virtua Tennis (USA).chd" saved as "Virtua Tennis".
CORS_EXPOSE_HEADERS = ["Content-Disposition"]

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
    # Deliberately the default "celery" queue rather than one of its own:
    # the celery-worker service already consumes -Q celery,downloads, so
    # password-reset mail needs no new worker in docker-compose.yml.
    "apps.accounts.tasks.*": {"queue": "celery"},
}

# --- Cache ------------------------------------------------------------------
# Must be shared across processes, not LocMemCache: the auth throttles
# (ninja.throttling) and the per-account lockout counters in
# apps.accounts.services.lockout live here, and daphne plus every celery
# worker runs in its own process. On LocMemCache each process would keep its
# own counter and an attacker would get N attempts per process instead of N
# total. Redis db 3 — 0 is general, 1 Celery, 2 Channels.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": env.str("CACHE_URL", default=f"{REDIS_URL.rstrip('/0')}/3"),
    },
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
# NOTE: ROTATE_REFRESH_TOKENS/BLACKLIST_AFTER_ROTATION used to be set here and
# did nothing. ninja_jwt reads them only in ninja_jwt/schema.py — the
# ninja-extra controller path this project deliberately bypasses (see the
# module docstring in apps/accounts/api.py) — so rotation never happened and
# one refresh token stayed valid for the full 14 days. Rotation is now done
# explicitly in apps.accounts.services.auth.rotate_tokens instead; don't
# re-add these keys, they'd read as if the library were handling it.
NINJA_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=14),
}

# ninja.throttling identifies clients by IP. With NUM_PROXIES unset, ninja
# trusts the whole X-Forwarded-For chain, which a client can forge — a new
# fake chain per request is a new bucket, so every auth throttle below
# becomes decorative. 0 means "ignore XFF, use REMOTE_ADDR", which is right
# for the bundled compose setup where nothing fronts daphne. Behind a
# reverse proxy set this to the number of proxies you actually run.
NINJA_NUM_PROXIES = env.int("NINJA_NUM_PROXIES", default=0)

# --- Auth ------------------------------------------------------------------
# Registration is invite-only: there is no open signup. Invites are issued
# from the Django admin or `manage.py createinvite`. See apps.accounts.models.Invite.
INVITE_EXPIRY_DAYS = env.int("INVITE_EXPIRY_DAYS", default=14)

# Per-account lockout (apps.accounts.services.lockout). Guards against
# distributed password spraying, which per-IP throttling alone cannot stop.
LOGIN_FAILURE_LIMIT = env.int("LOGIN_FAILURE_LIMIT", default=6)
LOGIN_FAILURE_WINDOW_SECONDS = env.int("LOGIN_FAILURE_WINDOW_SECONDS", default=900)
LOGIN_LOCKOUT_SECONDS = env.int("LOGIN_LOCKOUT_SECONDS", default=900)

PASSWORD_RESET_TIMEOUT = env.int("PASSWORD_RESET_TIMEOUT", default=60 * 60 * 24)

# The API can't infer the SPA's origin, and password-reset links have to point
# at the SvelteKit app rather than at Django. Also used to build invite signup
# URLs in the admin and in `manage.py createinvite`.
FRONTEND_BASE_URL = env.str("FRONTEND_BASE_URL", default="http://localhost:5173").rstrip("/")

DEFAULT_FROM_EMAIL = env.str("DEFAULT_FROM_EMAIL", default="romgi@localhost")
SERVER_EMAIL = DEFAULT_FROM_EMAIL

# The Django admin is a session+CSRF surface that the Ninja throttles above
# can't reach, so moving it off the default path is worth the one env var.
# Trailing slash required (it's passed straight to path()).
ADMIN_URL = env.str("ADMIN_URL", default="admin/")

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
