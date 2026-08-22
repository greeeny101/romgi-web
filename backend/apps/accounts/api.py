"""
JWT auth endpoints + per-user settings. Uses django-ninja-jwt's token
classes directly (RefreshToken/AccessToken, JWTAuth) rather than its
bundled ninja-extra controllers, so the whole API stays on one plain
NinjaAPI/Router — consistent with the rest of this project.

Endpoints here stay thin on purpose: parse, delegate to services/, return.
The substance lives in apps/accounts/services/ so that a second auth factor
can be added later by changing one service function rather than the router
and every caller of it.

Every unauthenticated endpoint below carries a throttle. They are the only
routes in the app an anonymous caller can reach, and login in particular is
PBKDF2-backed, so an unthrottled one is both a guessing oracle and a cheap
way to burn all the CPU on the box.
"""

from django.db import IntegrityError, transaction
from ninja import Router
from ninja.errors import HttpError
from ninja.throttling import AnonRateThrottle, AuthRateThrottle

from .models import User, UserSession, UserSettings
from .schemas import (
    CapabilitiesOut,
    LoginIn,
    LogoutIn,
    MeOut,
    PasswordChangeIn,
    PasswordResetConfirmIn,
    PasswordResetRequestIn,
    RefreshIn,
    RegisterIn,
    SessionOut,
    TokenPairOut,
    UserSettingsIn,
    UserSettingsOut,
)
from .services import auth as auth_service
from .services import invites, passwords, reset
from .tasks import send_password_reset

router = Router(tags=["auth"])
jwt_auth = auth_service.SessionJWTAuth()


@router.get("/capabilities", response=CapabilitiesOut, throttle=[AnonRateThrottle("60/m")])
def capabilities(request):
    """Lets the login UI describe what this instance can do before anyone signs in."""
    return CapabilitiesOut(email_enabled=auth_service.email_enabled())


@router.post("/register", response=TokenPairOut, throttle=[AnonRateThrottle("5/h")])
def register(request, payload: RegisterIn):
    # One transaction for the invite, the user and their settings. Previously
    # UserSettings.objects.create() ran outside any transaction, so a failure
    # there left a user with no settings row behind.
    try:
        with transaction.atomic():
            invite = invites.redeem(payload.invite_code, payload.email)
            passwords.validate_or_422(payload.password, user=User(email=payload.email))
            user = User.objects.create_user(email=payload.email, password=payload.password)
            UserSettings.objects.create(user=user)
            invite.used_by = user
            invite.save(update_fields=["used_by"])
    except IntegrityError:
        # Reachable only by someone holding a valid invite, so naming the cause
        # is worth more than the enumeration it would otherwise risk.
        raise HttpError(409, "An account with this email already exists.") from None

    return auth_service.issue_tokens(user, request)


@router.post("/login", response=TokenPairOut, throttle=[AnonRateThrottle("10/m")])
def login(request, payload: LoginIn):
    return auth_service.login(payload.email, payload.password, request)


@router.post("/refresh", response=TokenPairOut, throttle=[AnonRateThrottle("30/m")])
def refresh_token(request, payload: RefreshIn):
    """
    Returns a whole new pair, not just an access token: refresh tokens rotate,
    so the old one is dead by the time this responds and the client must store
    the replacement.
    """
    return auth_service.rotate_tokens(payload.refresh, request)


@router.post("/logout", response={204: None}, throttle=[AnonRateThrottle("30/m")])
def logout(request, payload: LogoutIn):
    """
    Unauthenticated by design — a client whose access token has already expired
    must still be able to log out, and holding the refresh token is itself the
    proof of ownership.
    """
    auth_service.revoke_by_refresh_token(payload.refresh)
    return 204, None


@router.get("/me", response=MeOut, auth=jwt_auth)
def me(request):
    return MeOut(id=request.user.id, email=request.user.email)


# --- Passwords --------------------------------------------------------------


@router.post(
    "/password/reset", response={202: None}, throttle=[AnonRateThrottle("5/h")]
)
def password_reset(request, payload: PasswordResetRequestIn):
    """
    Always 202, whether or not the address is registered — anything else turns
    this into a way to enumerate who has an account here.
    """
    user = User.objects.filter(email__iexact=payload.email, is_active=True).first()
    if user is not None and auth_service.email_enabled():
        send_password_reset.delay(user.id)
    return 202, None


@router.post(
    "/password/reset/confirm", response=TokenPairOut, throttle=[AnonRateThrottle("10/h")]
)
def password_reset_confirm(request, payload: PasswordResetConfirmIn):
    user = reset.user_from_token(payload.uid, payload.token)
    if user is None:
        raise HttpError(400, "This reset link is invalid or has expired.")

    passwords.validate_or_422(payload.new_password, user=user)
    # No session spared: whoever triggered a reset may be locked out of their
    # own account, and any session still open could be the attacker's.
    auth_service.set_password(user, payload.new_password)
    return auth_service.issue_tokens(user, request)


@router.post(
    "/password/change", response=TokenPairOut, auth=jwt_auth, throttle=[AuthRateThrottle("10/h")]
)
def password_change(request, payload: PasswordChangeIn):
    user = request.user
    if not user.check_password(payload.current_password):
        raise HttpError(403, "Current password is incorrect.")

    passwords.validate_or_422(payload.new_password, user=user)
    auth_service.set_password(user, payload.new_password)
    # The caller's old refresh token was just revoked along with the rest, so
    # hand back a fresh pair rather than logging them out of the tab they're in.
    return auth_service.issue_tokens(user, request)


# --- Sessions ---------------------------------------------------------------


@router.get("/sessions", response=list[SessionOut], auth=jwt_auth)
def list_sessions(request):
    current = auth_service.current_session_id(request)
    return [
        SessionOut(
            id=session.id,
            ip_address=session.ip_address,
            user_agent=session.user_agent,
            created_at=session.created_at,
            last_used_at=session.last_used_at,
            expires_at=session.expires_at,
            current=session.id == current,
        )
        for session in auth_service.active_sessions(request.user)
    ]


# Declared before /sessions/{session_id}: routes resolve in declaration order
# and the parameterised path matches any string, so registering it first would
# swallow "revoke-all" and answer 405 (it only accepts DELETE).
@router.post("/sessions/revoke-all", response={204: None}, auth=jwt_auth)
def revoke_other_sessions(request):
    """Signs out every other device, leaving the caller logged in."""
    auth_service.revoke_all_sessions(
        request.user, except_session_id=auth_service.current_session_id(request)
    )
    return 204, None


@router.delete("/sessions/{int:session_id}", response={204: None}, auth=jwt_auth)
def revoke_session(request, session_id: int):
    session = UserSession.objects.filter(
        pk=session_id, user=request.user, revoked_at__isnull=True
    ).first()
    if session is None:
        raise HttpError(404, "Session not found.")
    auth_service.revoke_session(session)
    return 204, None


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
