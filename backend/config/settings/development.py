from .base import *  # noqa: F401,F403
from .base import INSTALLED_APPS, MIDDLEWARE, env

DEBUG = True
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

CORS_ALLOW_ALL_ORIGINS = True

INSTALLED_APPS = [*INSTALLED_APPS, "debug_toolbar"]
MIDDLEWARE = [
    "debug_toolbar.middleware.DebugToolbarMiddleware",
    *MIDDLEWARE,
]
INTERNAL_IPS = ["127.0.0.1"]
DEBUG_TOOLBAR_CONFIG = {
    # debug_toolbar's default SHOW_TOOLBAR_CALLBACK, when REMOTE_ADDR isn't
    # directly in INTERNAL_IPS, falls back to resolving host.docker.internal
    # via DNS to guess the Docker gateway IP — on *every* request. Under
    # Docker Compose, REMOTE_ADDR is always the gateway IP (e.g.
    # 192.168.65.1), never 127.0.0.1, so that fallback fires unconditionally
    # and — on at least some Docker Desktop for Mac networking setups — adds
    # a fixed ~8s DNS-resolution delay to literally every request. This app
    # never runs with DEBUG=True outside trusted local dev, so there's no
    # reason to gate the toolbar by IP in the first place.
    "SHOW_TOOLBAR_CALLBACK": lambda request: DEBUG,
}

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Local filesystem storage — see production.py for the S3-compatible equivalent.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
