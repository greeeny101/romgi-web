"""
Auth behaviour that must not regress.

Each test here corresponds to a way the pre-hardening code could be abused:
open registration, unvalidated passwords, unlimited guessing, reset links that
outlive their use, and refresh tokens that never died.
"""

from datetime import timedelta

import pytest
from django.utils import timezone
from ninja_jwt.settings import api_settings
from ninja_jwt.tokens import RefreshToken

from apps.accounts.models import Invite, User, UserSession
from apps.accounts.services import auth as auth_service
from apps.accounts.services import invites, lockout, reset

pytestmark = pytest.mark.django_db

PASSWORD = "correct-horse-battery-staple"


@pytest.fixture
def invite():
    return invites.create_invite()


@pytest.fixture
def user():
    return User.objects.create_user(email="player@example.com", password=PASSWORD)


def _register(client, code, email="new@example.com", password=PASSWORD):
    return client.post(
        "/register", json={"email": email, "password": password, "invite_code": code}
    )


# --- Invite gate ------------------------------------------------------------


def test_register_succeeds_with_a_valid_invite(api_client, invite):
    response = _register(api_client, invite.code)

    assert response.status_code == 200, response.content
    assert set(response.json()) == {"access", "refresh"}

    user = User.objects.get(email="new@example.com")
    invite.refresh_from_db()
    assert invite.used_by == user
    assert invite.used_at is not None
    # The settings row must be created in the same transaction as the user.
    assert user.settings is not None


def test_register_is_refused_without_an_invite_code(api_client):
    response = api_client.post(
        "/register", json={"email": "new@example.com", "password": PASSWORD}
    )
    assert response.status_code == 422
    assert not User.objects.filter(email="new@example.com").exists()


@pytest.mark.parametrize("code", ["", "not-a-real-code"])
def test_register_is_refused_with_an_unknown_invite_code(api_client, code):
    assert _register(api_client, code).status_code == 403
    assert not User.objects.filter(email="new@example.com").exists()


def test_an_invite_cannot_be_used_twice(api_client, invite):
    assert _register(api_client, invite.code, email="first@example.com").status_code == 200

    response = _register(api_client, invite.code, email="second@example.com")
    assert response.status_code == 403
    assert not User.objects.filter(email="second@example.com").exists()


def test_expired_invites_are_refused(api_client):
    invite = invites.create_invite()
    invite.expires_at = timezone.now() - timedelta(seconds=1)
    invite.save(update_fields=["expires_at"])

    assert _register(api_client, invite.code).status_code == 403


def test_an_invite_bound_to_an_address_rejects_everyone_else(api_client):
    invite = invites.create_invite(email="wanted@example.com")

    assert _register(api_client, invite.code, email="gatecrasher@example.com").status_code == 403
    assert _register(api_client, invite.code, email="wanted@example.com").status_code == 200


# NOTE: redeem()'s "must be called inside a transaction" guard has no test.
# pytest.mark.django_db wraps every test in a transaction of its own, so
# in_atomic_block is unconditionally true here and the guard is unreachable.
# It still earns its place in production: select_for_update outside a
# transaction is a silent no-op, which would quietly reopen the double-redeem
# race the lock exists to close.


# --- Password policy --------------------------------------------------------


@pytest.mark.parametrize("weak", ["12345678", "password", "player@example.com"])
def test_weak_passwords_are_rejected_on_register(api_client, invite, weak):
    response = _register(api_client, invite.code, email="player@example.com", password=weak)

    assert response.status_code == 422, f"{weak!r} was accepted"
    assert not User.objects.filter(email="player@example.com").exists()
    # Rejected registrations must not burn the invite.
    invite.refresh_from_db()
    assert not invite.is_used


def test_short_passwords_are_rejected_by_the_schema(api_client, invite):
    assert _register(api_client, invite.code, password="short").status_code == 422


# --- Login and lockout ------------------------------------------------------


def test_login_returns_a_token_pair(api_client, user):
    response = api_client.post("/login", json={"email": user.email, "password": PASSWORD})

    assert response.status_code == 200
    assert set(response.json()) == {"access", "refresh"}
    user.refresh_from_db()
    assert user.last_login is not None


def test_login_failures_lock_the_account_and_success_clears_it(api_client, user, settings):
    for _ in range(settings.LOGIN_FAILURE_LIMIT):
        assert (
            api_client.post("/login", json={"email": user.email, "password": "wrong"}).status_code
            == 401
        )

    # Locked: even the correct password is refused now.
    locked = api_client.post("/login", json={"email": user.email, "password": PASSWORD})
    assert locked.status_code == 429

    lockout.clear(user.email)
    assert api_client.post(
        "/login", json={"email": user.email, "password": PASSWORD}
    ).status_code == 200
    # A successful login resets the counter for the next window.
    assert not lockout.is_locked(user.email)


def test_lockout_is_case_and_whitespace_insensitive(user):
    lockout.record_failure("  PLAYER@Example.com  ")
    lockout.record_failure(user.email)
    lockout.record_failure(user.email)
    assert lockout.is_locked(user.email)


def test_login_does_not_reveal_whether_an_account_exists(api_client, user):
    missing = api_client.post("/login", json={"email": "nobody@example.com", "password": "wrong"})
    wrong = api_client.post("/login", json={"email": user.email, "password": "wrong"})

    assert missing.status_code == wrong.status_code == 401
    assert missing.json() == wrong.json()


# --- Refresh rotation -------------------------------------------------------


def test_refresh_rotates_and_kills_the_old_token(api_client, user):
    tokens = api_client.post("/login", json={"email": user.email, "password": PASSWORD}).json()

    rotated = api_client.post("/refresh", json={"refresh": tokens["refresh"]})
    assert rotated.status_code == 200
    new_tokens = rotated.json()
    # The endpoint must hand back a replacement refresh token, not just an
    # access token — the client has to store it or the next refresh fails.
    assert "refresh" in new_tokens
    assert new_tokens["refresh"] != tokens["refresh"]

    # Replaying the old one is refused.
    assert api_client.post("/refresh", json={"refresh": tokens["refresh"]}).status_code == 401
    # The replacement still works.
    assert api_client.post("/refresh", json={"refresh": new_tokens["refresh"]}).status_code == 200


def test_rotation_keeps_one_session_rather_than_creating_more(api_client, user):
    tokens = api_client.post("/login", json={"email": user.email, "password": PASSWORD}).json()
    assert user.sessions.count() == 1

    api_client.post("/refresh", json={"refresh": tokens["refresh"]})

    assert user.sessions.count() == 1


def test_a_revoked_session_cannot_be_refreshed(api_client, user):
    tokens = api_client.post("/login", json={"email": user.email, "password": PASSWORD}).json()
    auth_service.revoke_all_sessions(user)

    assert api_client.post("/refresh", json={"refresh": tokens["refresh"]}).status_code == 401


# --- Sessions ---------------------------------------------------------------


def _auth(tokens):
    return {"Authorization": f"Bearer {tokens['access']}"}


def test_sessions_lists_logins_and_marks_the_current_one(api_client, user):
    first = api_client.post("/login", json={"email": user.email, "password": PASSWORD}).json()
    api_client.post("/login", json={"email": user.email, "password": PASSWORD})

    response = api_client.get("/sessions", headers=_auth(first))
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert [s["current"] for s in body].count(True) == 1


def test_revoke_all_leaves_the_caller_signed_in(api_client, user):
    keep = api_client.post("/login", json={"email": user.email, "password": PASSWORD}).json()
    other = api_client.post("/login", json={"email": user.email, "password": PASSWORD}).json()

    assert api_client.post("/sessions/revoke-all", headers=_auth(keep)).status_code == 204

    assert api_client.get("/me", headers=_auth(keep)).status_code == 200
    assert api_client.post("/refresh", json={"refresh": other["refresh"]}).status_code == 401
    assert api_client.post("/refresh", json={"refresh": keep["refresh"]}).status_code == 200


def test_a_user_cannot_revoke_someone_elses_session(api_client, user):
    victim = User.objects.create_user(email="victim@example.com", password=PASSWORD)
    victim_tokens = api_client.post(
        "/login", json={"email": victim.email, "password": PASSWORD}
    ).json()
    victim_session = UserSession.objects.filter(user=victim).first()

    attacker = api_client.post("/login", json={"email": user.email, "password": PASSWORD}).json()

    response = api_client.delete(f"/sessions/{victim_session.id}", headers=_auth(attacker))
    assert response.status_code == 404
    assert api_client.post("/refresh", json={"refresh": victim_tokens["refresh"]}).status_code == 200


def test_logout_closes_the_session(api_client, user):
    tokens = api_client.post("/login", json={"email": user.email, "password": PASSWORD}).json()

    assert api_client.post("/logout", json={"refresh": tokens["refresh"]}).status_code == 204

    assert api_client.post("/refresh", json={"refresh": tokens["refresh"]}).status_code == 401
    assert not auth_service.active_sessions(user).exists()


# --- Password reset and change ----------------------------------------------


def test_reset_link_works_once_and_signs_every_session_out(api_client, user):
    stale = api_client.post("/login", json={"email": user.email, "password": PASSWORD}).json()
    # Logging in bumped last_login in the database, and the reset token hashes
    # it — building a link from this stale instance would produce one the
    # server then rejects.
    user.refresh_from_db()
    url = reset.build_reset_url(user)
    uid, token = url.split("uid=")[1].split("&token=")

    payload = {"uid": uid, "token": token, "new_password": "a-brand-new-passphrase"}
    assert api_client.post("/password/reset/confirm", json=payload).status_code == 200

    # Single use: the token's hash covers the password it just changed.
    assert api_client.post("/password/reset/confirm", json=payload).status_code == 400

    user.refresh_from_db()
    assert user.check_password("a-brand-new-passphrase")
    assert api_client.post("/refresh", json={"refresh": stale["refresh"]}).status_code == 401


def test_reset_confirm_enforces_the_password_policy(api_client, user):
    url = reset.build_reset_url(user)
    uid, token = url.split("uid=")[1].split("&token=")

    response = api_client.post(
        "/password/reset/confirm", json={"uid": uid, "token": token, "new_password": "12345678"}
    )
    assert response.status_code == 422
    user.refresh_from_db()
    assert user.check_password(PASSWORD)


def test_reset_request_is_always_accepted(api_client, user):
    for email in (user.email, "nobody@example.com"):
        assert api_client.post("/password/reset", json={"email": email}).status_code == 202


def test_password_change_requires_the_current_password(api_client, user):
    tokens = api_client.post("/login", json={"email": user.email, "password": PASSWORD}).json()

    response = api_client.post(
        "/password/change",
        json={"current_password": "wrong", "new_password": "a-brand-new-passphrase"},
        headers=_auth(tokens),
    )

    assert response.status_code == 403
    user.refresh_from_db()
    assert user.check_password(PASSWORD)


def test_password_change_drops_other_sessions_but_keeps_the_caller_usable(api_client, user):
    other = api_client.post("/login", json={"email": user.email, "password": PASSWORD}).json()
    tokens = api_client.post("/login", json={"email": user.email, "password": PASSWORD}).json()

    response = api_client.post(
        "/password/change",
        json={"current_password": PASSWORD, "new_password": "a-brand-new-passphrase"},
        headers=_auth(tokens),
    )

    assert response.status_code == 200
    fresh = response.json()
    # The caller gets a working replacement pair rather than being logged out.
    assert api_client.get("/me", headers=_auth(fresh)).status_code == 200
    assert api_client.post("/refresh", json={"refresh": other["refresh"]}).status_code == 401


# --- Misc -------------------------------------------------------------------


def test_capabilities_reports_whether_email_works(api_client, settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    settings.EMAIL_HOST = ""
    assert api_client.get("/capabilities").json() == {"email_enabled": False}

    settings.EMAIL_HOST = "smtp.example.com"
    assert api_client.get("/capabilities").json() == {"email_enabled": True}


def test_access_token_carries_the_session_id(user, rf):
    request = rf.post("/")
    tokens = auth_service.issue_tokens(user, request)

    session = UserSession.objects.get(user=user)
    from ninja_jwt.tokens import AccessToken

    assert AccessToken(tokens.access)["sid"] == session.id
    assert RefreshToken(tokens.refresh)[api_settings.JTI_CLAIM] == session.jti


def test_createsuperuser_refuses_a_non_staff_superuser():
    with pytest.raises(ValueError):
        User.objects.create_superuser("root@example.com", PASSWORD, is_staff=False)


def test_invite_signup_url_points_at_the_frontend(settings):
    invite = Invite.objects.create()
    assert invite.signup_url == f"{settings.FRONTEND_BASE_URL}/signup?invite={invite.code}"
