from .base import *  # noqa: F401,F403
from .base import env

DEBUG = False
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS")

SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=31536000)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
X_FRAME_OPTIONS = "DENY"
# Only matters for Django admin (session+CSRF-cookie auth) — the Ninja API
# itself is Bearer-token-only and CSRF-exempt by nature.
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])

# S3-compatible object storage for static files. NOTE: staged downloads
# (apps.downloads.tasks / apps.downloads.api's file-serving endpoint) do
# NOT use this — they read/write STAGED_FILES_DIR on local disk in every
# environment, dev and prod alike. That's a deliberate, currently-unaddressed
# gap: HTTP Range-resumable, incrementally-written downloads don't map
# cleanly onto S3's write-once object model, and building that properly
# needs a real S3-compatible endpoint to test against rather than shipping
# unverified. In production this means STAGED_FILES_DIR/TORRENT_WORKING_DIR
# must sit on a real persistent volume (docker-compose.yml's `staged_files`/
# `torrent_data` volumes do this for the bundled compose deployment) — a
# single-node assumption that won't survive multi-node horizontal scaling
# of the downloads worker without further work.
STORAGES = {
    "default": {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "bucket_name": env.str("AWS_STORAGE_BUCKET_NAME"),
            "region_name": env.str("AWS_S3_REGION_NAME", default=""),
            "endpoint_url": env.str("AWS_S3_ENDPOINT_URL", default=""),
            "custom_domain": env.str("AWS_S3_CUSTOM_DOMAIN", default=""),
            "default_acl": "private",
            "querystring_auth": True,
            "querystring_expire": 300,
        },
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.ManifestStaticFilesStorage",
    },
}

EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = env.str("EMAIL_HOST", default="")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_HOST_USER = env.str("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env.str("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = True
