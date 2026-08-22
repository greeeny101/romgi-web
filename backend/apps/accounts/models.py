import secrets

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.utils import timezone

from apps.common.models import TimeStampedModel

from .managers import UserManager


class User(AbstractUser):
    """Email-login user."""

    username = None
    email = models.EmailField(unique=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    def __str__(self) -> str:
        return self.email


def generate_invite_code() -> str:
    return secrets.token_urlsafe(32)


class Invite(TimeStampedModel):
    """
    Registration is invite-only — this instance is not open signup. An invite
    is issued from the Django admin or `manage.py createinvite`, handed to the
    invitee out of band (the app cannot rely on having SMTP), and consumed
    exactly once by POST /api/auth/register.
    """

    code = models.CharField(max_length=64, unique=True, default=generate_invite_code)
    # Optional: bind the invite to one address so a leaked code can't be
    # redeemed by whoever finds it. Blank means any email may use it.
    email = models.EmailField(blank=True)
    note = models.CharField(max_length=200, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="invites_created",
    )
    expires_at = models.DateTimeField(null=True, blank=True)
    used_at = models.DateTimeField(null=True, blank=True)
    used_by = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="invite_used",
    )

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"Invite<{self.email or 'any'} {self.status}>"

    @property
    def is_expired(self) -> bool:
        return self.expires_at is not None and self.expires_at <= timezone.now()

    @property
    def is_used(self) -> bool:
        return self.used_at is not None

    @property
    def status(self) -> str:
        if self.is_used:
            return "used"
        if self.is_expired:
            return "expired"
        return "pending"

    def is_valid_for(self, email: str) -> bool:
        if self.is_used or self.is_expired:
            return False
        if self.email:
            return self.email.casefold() == (email or "").casefold()
        return True

    @property
    def signup_url(self) -> str:
        return f"{settings.FRONTEND_BASE_URL}/signup?invite={self.code}"


class UserSession(TimeStampedModel):
    """
    One row per issued refresh token, so a user can see and revoke their own
    logins. ninja_jwt's OutstandingToken already records (user, jti) but it's a
    third-party model with no room for the device details this needs, hence the
    companion row joined on `jti`.

    `jti` changes on every refresh (rotation replaces the token but keeps the
    session), so it is indexed but deliberately NOT unique — a blacklisted
    predecessor and its replacement can briefly coexist.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="sessions"
    )
    jti = models.CharField(max_length=255, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=400, blank=True)
    last_used_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-last_used_at",)
        indexes = [models.Index(fields=["user", "revoked_at"])]

    def __str__(self) -> str:
        return f"Session<{self.user_id} {self.jti[:8]}>"

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None and self.expires_at > timezone.now()


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
