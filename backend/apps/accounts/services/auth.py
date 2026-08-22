"""
The one place refresh/access tokens are minted, rotated and revoked.

Token handling used to live inline in apps/accounts/api.py. It moved here so
the router stays thin (validate → delegate → return) and so a second
authentication factor can be inserted later without touching route signatures
or the client: TOTP becomes a branch inside `login`, not a rewrite.

Every issued refresh token gets a UserSession row and an `sid` claim. The claim
is set on the refresh token *before* `.access_token` is read, because
RefreshToken.access_token copies every claim except jti/exp/token_type — so the
access token carries `sid` too, and an authenticated request can tell which of
the user's sessions it is speaking for.
"""

import ipaddress
import logging

from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.models import AnonymousUser
from django.db import transaction
from django.utils import timezone
from ninja.errors import HttpError
from ninja.throttling import BaseThrottle
from ninja_jwt.authentication import JWTAuth
from ninja_jwt.exceptions import TokenError
from ninja_jwt.settings import api_settings
from ninja_jwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from ninja_jwt.tokens import RefreshToken

from ..models import User, UserSession
from ..schemas import TokenPairOut
from . import lockout

logger = logging.getLogger("romgi.auth")

# Deliberately identical for "no such account" and "wrong password" — see
# login() below.
INVALID_CREDENTIALS = "Invalid email or password."


def _client_ip(request) -> str | None:
    """
    Reuses ninja's own throttling ident logic so the address recorded against a
    session is the same one the throttles bucket on, and honours
    NINJA_NUM_PROXIES the same way.
    """
    ident = BaseThrottle().get_ident(request)
    try:
        return str(ipaddress.ip_address(ident))
    except ValueError:
        # get_ident joins the whole X-Forwarded-For chain when NUM_PROXIES is
        # unset, which isn't a storable address.
        return None


def _user_agent(request) -> str:
    return (request.META.get("HTTP_USER_AGENT") or "")[:400]


def issue_tokens(user: User, request) -> TokenPairOut:
    """Mint a fresh token pair and open a session for it."""
    refresh = RefreshToken.for_user(user)
    jti = refresh[api_settings.JTI_CLAIM]

    session = UserSession.objects.create(
        user=user,
        jti=jti,
        ip_address=_client_ip(request),
        user_agent=_user_agent(request),
        expires_at=timezone.now() + api_settings.REFRESH_TOKEN_LIFETIME,
    )

    refresh["sid"] = session.id
    access = refresh.access_token

    # authenticate() does not touch last_login — only django.contrib.auth.login()
    # fires the user_logged_in signal that updates it, and this app never calls
    # it. Without this the field would stay null forever, and the password-reset
    # token generator (which hashes last_login) would be weaker for it.
    user.last_login = timezone.now()
    user.save(update_fields=["last_login"])

    return TokenPairOut(access=str(access), refresh=str(refresh))


def rotate_tokens(raw_refresh: str, request) -> TokenPairOut:
    """
    Exchange a refresh token for a brand new pair, invalidating the old one.

    Rotation limits the damage from a stolen refresh token: it is single-use, so
    a thief and the real user cannot both keep using it — the second one to
    present it is rejected. The session survives the swap (same row, new jti),
    which is what keeps it listed under a stable id in GET /auth/sessions.
    """
    try:
        old = RefreshToken(raw_refresh)
    except TokenError:
        raise HttpError(401, "Invalid or expired refresh token.") from None

    jti = old[api_settings.JTI_CLAIM]
    session = UserSession.objects.filter(jti=jti, revoked_at__isnull=True).first()
    if session is None:
        # Either revoked out from under this client (another device pressed
        # "sign out everywhere") or minted before sessions existed.
        raise HttpError(401, "Session is no longer valid.")

    try:
        user = User.objects.get(pk=old["user_id"], is_active=True)
    except User.DoesNotExist:
        raise HttpError(401, "Session is no longer valid.") from None

    with transaction.atomic():
        old.blacklist()

        new = RefreshToken.for_user(user)
        session.jti = new[api_settings.JTI_CLAIM]
        session.last_used_at = timezone.now()
        session.expires_at = timezone.now() + api_settings.REFRESH_TOKEN_LIFETIME
        session.ip_address = _client_ip(request)
        session.user_agent = _user_agent(request)
        session.save(
            update_fields=["jti", "last_used_at", "expires_at", "ip_address", "user_agent"]
        )

        new["sid"] = session.id
        access = new.access_token

    return TokenPairOut(access=str(access), refresh=str(new))


def revoke_session(session: UserSession) -> None:
    """
    Blacklist a session's current refresh token and close the row.

    Works from the jti alone — no need for the raw token — because
    RefreshToken.for_user already recorded an OutstandingToken for it.
    """
    outstanding = OutstandingToken.objects.filter(jti=session.jti).first()
    if outstanding is not None:
        BlacklistedToken.objects.get_or_create(token=outstanding)
    if session.revoked_at is None:
        session.revoked_at = timezone.now()
        session.save(update_fields=["revoked_at"])


def revoke_by_refresh_token(raw_refresh: str) -> None:
    """
    Log out by presenting the refresh token itself — the logout path, which has
    to work for a client whose access token already expired. Failures are
    swallowed: an already-expired or already-blacklisted token means the caller
    is logged out, which is what they asked for.
    """
    try:
        token = RefreshToken(raw_refresh)
    except TokenError:
        return

    jti = token[api_settings.JTI_CLAIM]
    session = UserSession.objects.filter(jti=jti, revoked_at__isnull=True).first()
    if session is not None:
        revoke_session(session)
    else:
        token.blacklist()


def active_sessions(user: User):
    return user.sessions.filter(revoked_at__isnull=True, expires_at__gt=timezone.now())


def revoke_all_sessions(user: User, *, except_session_id: int | None = None) -> int:
    """Sign the user out everywhere, optionally sparing the caller's own session."""
    qs = user.sessions.filter(revoked_at__isnull=True)
    if except_session_id is not None:
        qs = qs.exclude(pk=except_session_id)
    sessions = list(qs)
    for session in sessions:
        revoke_session(session)
    return len(sessions)


class SessionJWTAuth(JWTAuth):
    """
    JWTAuth, but it keeps the decoded token.

    Stock JWTAuth returns only the User and throws the validated token away, so
    the `sid` claim issue_tokens went to the trouble of setting would never
    reach the endpoint. Session management needs it to know which of the user's
    sessions is making the call — the one it must not revoke out from under
    itself.
    """

    def jwt_authenticate(self, request, token: str):
        request.user = AnonymousUser()
        validated_token = self.get_validated_token(token)
        user = self.get_user(validated_token)
        request.user = user
        request.auth_token = validated_token
        return user


def current_session_id(request) -> int | None:
    """The `sid` claim of the access token that authenticated this request."""
    validated_token = getattr(request, "auth_token", None)
    if validated_token is None:
        return None
    try:
        return int(validated_token["sid"])
    except (KeyError, TypeError, ValueError):
        # Tokens issued before sessions existed have no sid.
        return None


def login(email: str, password: str, request) -> TokenPairOut:
    """
    Authenticate and open a session, or raise.

    This is the natural insertion point for a second factor: once a TOTP model
    exists, the branch goes here — return an MFA challenge instead of a token
    pair — and neither the router nor the SPA's call shape has to change.
    """
    if lockout.is_locked(email):
        # 429 rather than 401 so the client can say something useful, and
        # phrased so it reveals nothing about whether the account exists.
        raise HttpError(429, "Too many failed attempts. Try again later.")

    # authenticate() takes the email as `username` because USERNAME_FIELD is
    # "email". Django's ModelBackend runs a dummy password hash for unknown
    # users, so this is already constant-time enough to not leak which emails
    # are registered.
    user = authenticate(request, username=email, password=password)
    if user is None:
        # The failure is counted by the user_login_failed receiver in
        # signals.py, which authenticate() fires for us — counting it again
        # here would halve the effective attempt limit.
        logger.info("Failed login for %s", email)
        raise HttpError(401, INVALID_CREDENTIALS)

    lockout.clear(email)
    logger.info("Successful login for %s", email)
    return issue_tokens(user, request)


def set_password(user: User, raw_password: str, *, keep_session_id: int | None = None) -> None:
    """
    Change a password and sign every other session out.

    Revoking is the point: a password change is how someone responds to a
    suspected compromise, and it would be worthless if the attacker's 14-day
    refresh token kept working afterwards.
    """
    user.set_password(raw_password)
    user.save(update_fields=["password"])
    revoke_all_sessions(user, except_session_id=keep_session_id)
    lockout.clear(user.email)


def email_enabled() -> bool:
    """
    Whether this instance can actually send mail.

    SMTP is optional — an operator can run romgi with no mail server at all, in
    which case password resets are issued out of band with
    `manage.py resetlink`. The SPA asks about this so it can say so plainly
    instead of promising an email that will never arrive.
    """
    backend = getattr(settings, "EMAIL_BACKEND", "")
    if "smtp" in backend:
        return bool(getattr(settings, "EMAIL_HOST", ""))
    # console/locmem/file backends "work" in the sense that the message goes
    # somewhere the operator can retrieve it.
    return bool(backend) and "dummy" not in backend
