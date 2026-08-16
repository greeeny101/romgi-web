"""
JWT auth endpoints + per-user settings. Uses django-ninja-jwt's token
classes directly (RefreshToken/AccessToken, JWTAuth) rather than its
bundled ninja-extra controllers, so the whole API stays on one plain
NinjaAPI/Router — consistent with the rest of this project.
"""

from django.contrib.auth import authenticate
from django.db import IntegrityError
from ninja import Router
from ninja.errors import HttpError
from ninja_jwt.authentication import JWTAuth
from ninja_jwt.exceptions import TokenError
from ninja_jwt.tokens import RefreshToken

from .models import User, UserSettings
from .schemas import (
    AccessOut,
    LoginIn,
    LogoutIn,
    MeOut,
    RefreshIn,
    RegisterIn,
    TokenPairOut,
    UserSettingsIn,
    UserSettingsOut,
)

router = Router(tags=["auth"])
jwt_auth = JWTAuth()


def _token_pair(user: User) -> TokenPairOut:
    refresh = RefreshToken.for_user(user)
    return TokenPairOut(access=str(refresh.access_token), refresh=str(refresh))


@router.post("/register", response=TokenPairOut)
def register(request, payload: RegisterIn):
    try:
        user = User.objects.create_user(email=payload.email, password=payload.password)
    except IntegrityError:
        raise HttpError(409, "An account with this email already exists.")
    UserSettings.objects.create(user=user)
    return _token_pair(user)


@router.post("/login", response=TokenPairOut)
def login(request, payload: LoginIn):
    user = authenticate(request, username=payload.email, password=payload.password)
    if user is None:
        raise HttpError(401, "Invalid email or password.")
    return _token_pair(user)


@router.post("/refresh", response=AccessOut)
def refresh_token(request, payload: RefreshIn):
    try:
        refresh = RefreshToken(payload.refresh)
    except TokenError:
        raise HttpError(401, "Invalid or expired refresh token.")
    return AccessOut(access=str(refresh.access_token))


@router.post("/logout", response={204: None})
def logout(request, payload: LogoutIn):
    try:
        RefreshToken(payload.refresh).blacklist()
    except TokenError:
        pass
    return 204, None


@router.get("/me", response=MeOut, auth=jwt_auth)
def me(request):
    return MeOut(id=request.user.id, email=request.user.email)


settings_router = Router(tags=["settings"])


def _settings_out(settings: UserSettings) -> UserSettingsOut:
    return UserSettingsOut(
        theme=settings.theme,
        max_concurrent_downloads=settings.max_concurrent_downloads,
        torrents_disabled=settings.torrents_disabled,
        auto_extract_disabled=settings.auto_extract_disabled,
        debrid_enabled=settings.debrid_enabled,
        debrid_provider_id=settings.debrid_provider_id,
        metadata_enabled=settings.metadata_enabled,
        preferred_source_ids=settings.preferred_source_ids,
        disabled_source_ids=settings.disabled_source_ids,
        default_platform_ids=list(settings.default_platforms.values_list("id", flat=True)),
        default_region_ids=list(settings.default_regions.values_list("id", flat=True)),
        extract_disabled_platform_ids=list(
            settings.extract_disabled_platforms.values_list("id", flat=True)
        ),
    )


@settings_router.get("", response=UserSettingsOut, auth=jwt_auth)
def get_settings(request):
    settings, _ = UserSettings.objects.get_or_create(user=request.user)
    return _settings_out(settings)


@settings_router.patch("", response=UserSettingsOut, auth=jwt_auth)
def update_settings(request, payload: UserSettingsIn):
    settings, _ = UserSettings.objects.get_or_create(user=request.user)

    scalar_fields = [
        "theme",
        "max_concurrent_downloads",
        "torrents_disabled",
        "auto_extract_disabled",
        "debrid_enabled",
        "debrid_provider_id",
        "metadata_enabled",
        "preferred_source_ids",
        "disabled_source_ids",
    ]
    dirty = []
    for field in scalar_fields:
        value = getattr(payload, field)
        if value is not None:
            setattr(settings, field, value)
            dirty.append(field)
    if dirty:
        settings.save(update_fields=dirty)

    if payload.default_platform_ids is not None:
        settings.default_platforms.set(payload.default_platform_ids)
    if payload.default_region_ids is not None:
        settings.default_regions.set(payload.default_region_ids)
    if payload.extract_disabled_platform_ids is not None:
        settings.extract_disabled_platforms.set(payload.extract_disabled_platform_ids)

    return _settings_out(settings)
