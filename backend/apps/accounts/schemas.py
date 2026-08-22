from datetime import datetime

from ninja import Schema
from pydantic import EmailStr, Field

# Cheap client-side-equivalent floor. The real policy is
# AUTH_PASSWORD_VALIDATORS, enforced via services.passwords.validate_or_422 —
# this only spares the caller a round trip on an obviously-too-short password.
Password = Field(min_length=8, max_length=128)


class RegisterIn(Schema):
    email: EmailStr
    password: str = Password
    # Registration is invite-only; there is no open signup path.
    invite_code: str


class LoginIn(Schema):
    email: EmailStr
    password: str


class TokenPairOut(Schema):
    access: str
    refresh: str


class RefreshIn(Schema):
    refresh: str


class LogoutIn(Schema):
    refresh: str


class MeOut(Schema):
    id: int
    email: str


class CapabilitiesOut(Schema):
    """
    What this instance can actually do, so the SPA doesn't offer flows that
    will silently go nowhere. SMTP is optional in this deployment.
    """

    email_enabled: bool


class PasswordResetRequestIn(Schema):
    email: EmailStr


class PasswordResetConfirmIn(Schema):
    uid: str
    token: str
    new_password: str = Password


class PasswordChangeIn(Schema):
    current_password: str
    new_password: str = Password


class SessionOut(Schema):
    id: int
    ip_address: str | None
    user_agent: str
    created_at: datetime
    last_used_at: datetime
    expires_at: datetime
    # True for the session whose access token made this request — the client
    # labels it and refuses to revoke it without warning.
    current: bool


class UserSettingsOut(Schema):
    theme: str
    max_concurrent_downloads: int
    torrents_disabled: bool
    auto_extract_disabled: bool
    debrid_enabled: bool
    debrid_provider_id: str
    metadata_enabled: bool
    preferred_source_ids: list[str]
    disabled_source_ids: list[str]
    default_platform_ids: list[str]
    default_region_ids: list[str]
    extract_disabled_platform_ids: list[str]


class UserSettingsIn(Schema):
    theme: str | None = None
    max_concurrent_downloads: int | None = None
    torrents_disabled: bool | None = None
    auto_extract_disabled: bool | None = None
    debrid_enabled: bool | None = None
    debrid_provider_id: str | None = None
    metadata_enabled: bool | None = None
    preferred_source_ids: list[str] | None = None
    disabled_source_ids: list[str] | None = None
    default_platform_ids: list[str] | None = None
    default_region_ids: list[str] | None = None
    extract_disabled_platform_ids: list[str] | None = None
