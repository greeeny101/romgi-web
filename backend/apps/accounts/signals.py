"""
Feeds Django-side login failures into the same lockout counter the API uses.

The Ninja throttles only cover /api/auth/*. The Django admin is a separate
session-based login form that never touches them, so without this an attacker
could sit on /admin/ and guess passwords for a staff account unthrottled while
the API happily reported the account as locked.

`user_login_failed` fires from django.contrib.auth.authenticate() itself, so it
covers the admin and anything else that authenticates — including the API's own
call. services.auth.login therefore does NOT record failures separately; it
would double-count.
"""

import logging

from django.contrib.auth.signals import user_login_failed
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
