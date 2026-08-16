from django.contrib.auth.models import AbstractUser
from django.contrib.postgres.fields import ArrayField
from django.db import models

from apps.common.models import TimeStampedModel

from .managers import UserManager


class User(AbstractUser):
    """Email-login user. Full auth/JWT endpoints land in Phase 2."""

    username = None
    email = models.EmailField(unique=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    def __str__(self) -> str:
        return self.email


class UserSettings(TimeStampedModel):
    """
    Server-side equivalent of the Dart app's SettingsState (previously
    SharedPreferences, now per-user and Postgres-backed).
    """

    THEME_CHOICES = [("system", "system"), ("light", "light"), ("dark", "dark")]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="settings")
    theme = models.CharField(max_length=8, choices=THEME_CHOICES, default="system")

    default_platforms = models.ManyToManyField("catalog.Platform", blank=True, related_name="+")
    default_regions = models.ManyToManyField("catalog.Region", blank=True, related_name="+")

    max_concurrent_downloads = models.PositiveSmallIntegerField(default=3)
    torrents_disabled = models.BooleanField(default=False)
    auto_extract_disabled = models.BooleanField(default=False)
    extract_disabled_platforms = models.ManyToManyField(
        "catalog.Platform", blank=True, related_name="+"
    )

    debrid_enabled = models.BooleanField(default=False)
    debrid_provider_id = models.CharField(max_length=32, default="torbox")
    metadata_enabled = models.BooleanField(default=True)

    preferred_source_ids = ArrayField(models.CharField(max_length=32), default=list, blank=True)
    disabled_source_ids = ArrayField(models.CharField(max_length=32), default=list, blank=True)

    def __str__(self) -> str:
        return f"Settings<{self.user.email}>"
