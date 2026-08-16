"""
Server-side replacement for flutter_secure_storage: every third-party
secret the app needs (Internet Archive session, debrid API keys,
ScreenScraper/SteamGridDB API keys) now lives here instead of per-device OS
keystores — per-user, Fernet-encrypted at rest (apps.common.fields.EncryptedJSONField).
"""

from django.conf import settings
from django.db import models

from apps.common.fields import EncryptedJSONField
from apps.common.models import TimeStampedModel


class EncryptedCredential(TimeStampedModel):
    PROVIDER_CHOICES = [
        ("internet_archive", "internet_archive"),
        ("realdebrid", "realdebrid"),
        ("torbox", "torbox"),
        ("screenscraper", "screenscraper"),
        ("steamgriddb", "steamgriddb"),
    ]
    STATUS_CHOICES = [
        ("unverified", "unverified"),
        ("ok", "ok"),
        ("stale", "stale"),
        ("invalid", "invalid"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="credentials")
    provider = models.CharField(max_length=32, choices=PROVIDER_CHOICES)
    # Provider-specific secret payload — e.g. IA: {username, access_key,
    # secret_key, cookies}; debrid: {api_key}; ScreenScraper:
    # {username, password, dev_id, dev_password}; SteamGridDB: {api_key}.
    data = EncryptedJSONField()

    # Staleness re-validation (IA: 24h) and circuit-breaker bookkeeping
    # (IA: 3 strikes) — ports internet_archive_auth_manager.dart's
    # IAValidationStatus + failureCount state. Simple API-key providers
    # (debrid/metadata) only ever move between unverified/ok/invalid, set
    # by the "test connection" endpoint — they have no staleness/strike
    # concept of their own.
    last_validated_at = models.DateTimeField(null=True, blank=True)
    failure_count = models.IntegerField(default=0)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="unverified")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "provider"], name="unique_user_provider_credential"),
        ]

    def __str__(self) -> str:
        return f"EncryptedCredential<{self.user_id} {self.provider}>"
