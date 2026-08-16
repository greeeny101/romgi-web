from ninja import Schema
from pydantic import EmailStr


class RegisterIn(Schema):
    email: EmailStr
    password: str


class LoginIn(Schema):
    email: EmailStr
    password: str


class TokenPairOut(Schema):
    access: str
    refresh: str


class RefreshIn(Schema):
    refresh: str


class AccessOut(Schema):
    access: str


class LogoutIn(Schema):
    refresh: str


class MeOut(Schema):
    id: int
    email: str


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
