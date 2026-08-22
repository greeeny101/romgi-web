"""
Give every refresh token that is already in the wild a UserSession row.

Without this, the first thing each existing user's browser does after deploy is
call /auth/refresh, which now looks the token's jti up in UserSession, finds
nothing, and answers 401 — signing out everyone who was logged in at the moment
of the upgrade. The rows are reconstructed from ninja_jwt's OutstandingToken,
which has recorded (user, jti, created_at, expires_at) for every token ever
issued by RefreshToken.for_user().

Device details are left blank: the request that created these tokens is long
gone, so ip_address/user_agent are genuinely unknown and guessing would be
worse than an honest blank. They fill in on the next rotation.
"""

from django.db import migrations


def backfill(apps, schema_editor):
    UserSession = apps.get_model("accounts", "UserSession")
    OutstandingToken = apps.get_model("token_blacklist", "OutstandingToken")
    BlacklistedToken = apps.get_model("token_blacklist", "BlacklistedToken")

    blacklisted = set(BlacklistedToken.objects.values_list("token__jti", flat=True))
    existing = set(UserSession.objects.values_list("jti", flat=True))

    UserSession.objects.bulk_create(
        [
            UserSession(
                user_id=token.user_id,
                jti=token.jti,
                ip_address=None,
                user_agent="",
                created_at=token.created_at,
                updated_at=token.created_at,
                last_used_at=token.created_at,
                expires_at=token.expires_at,
            )
            for token in OutstandingToken.objects.filter(user_id__isnull=False).iterator()
            # A blacklisted token is already logged out; recreating a session
            # for it would quietly bring it back to life.
            if token.jti not in blacklisted and token.jti not in existing
        ]
    )


def noop(apps, schema_editor):
    """Deliberately irreversible-but-harmless: rolling back just leaves the rows."""


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_invite_usersession"),
        ("token_blacklist", "0001_initial"),
    ]

    operations = [migrations.RunPython(backfill, noop)]
