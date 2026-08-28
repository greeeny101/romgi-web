"""
Two receivers, both here for the same reason: they cover the paths that don't
go through the API.

`record_failed_login` feeds Django-side login failures into the same lockout
counter the API uses. The Ninja throttles only cover /api/auth/*. The Django
admin is a separate session-based login form that never touches them, so
without this an attacker could sit on /admin/ and guess passwords for a staff
account unthrottled while the API happily reported the account as locked.

`user_login_failed` fires from django.contrib.auth.authenticate() itself, so it
covers the admin and anything else that authenticates — including the API's own
call. services.auth.login therefore does NOT record failures separately; it
would double-count.

`create_user_settings` guarantees a UserSettings row for every user. It used to
be created only by the /auth/register endpoint, so anyone made by
`manage.py createsuperuser` or the admin's add form had none until they first
opened the settings page — and the readers that fall back when the row is
missing then disagreed with the model's own defaults (no auto-extract, no
metadata). post_save covers every creation path at once.
"""

import logging

from django.conf import settings
from django.contrib.auth.signals import user_login_failed
from django.db.models.signals import post_save
from django.dispatch import receiver

from .services import lockout

logger = logging.getLogger("romgi.auth")


@receiver(user_login_failed)
def record_failed_login(sender, credentials=None, request=None, **kwargs):
    # USERNAME_FIELD is "email", but authenticate() is called with
    # username=<email> so the credentials dict can carry either key.
    creds = credentials or {}
    email = creds.get("email") or creds.get("username")
    if not email:
        return
    lockout.record_failure(email)


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_user_settings(sender, instance, created, raw=False, **kwargs):
    # `raw` means loaddata is replaying a fixture, which carries its own rows;
    # creating a second one here would collide with the OneToOne constraint.
    if not created or raw:
        return
    from .models import UserSettings

    UserSettings.objects.get_or_create(user=instance)
