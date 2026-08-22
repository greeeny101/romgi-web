"""
Account-related background work.

Routed to the default "celery" queue (see CELERY_TASK_ROUTES) rather than a
queue of its own — the existing celery-worker service already consumes
-Q celery,downloads, so none of this needs a new container.
"""

import logging

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone
from ninja_jwt.token_blacklist.models import BlacklistedToken, OutstandingToken

from .models import User, UserSession
from .services import reset

logger = logging.getLogger("romgi.auth")

RESET_SUBJECT = "Reset your romgi password"
RESET_BODY = """\
Someone asked to reset the romgi password for this address.

Open this link to choose a new one:

{url}

The link expires in {hours} hours and can only be used once.

If this wasn't you, no action is needed — your password has not changed.
"""


@shared_task
def send_password_reset(user_id: int) -> None:
    """
    Dispatched by POST /auth/password/reset. Fire-and-forget: the endpoint
    answers 202 regardless of whether this succeeds, or even whether the
    address existed, so that it can't be used to test which emails are
    registered.
    """
    user = User.objects.filter(pk=user_id, is_active=True).first()
    if user is None:
        return

    url = reset.build_reset_url(user)
    send_mail(
        subject=RESET_SUBJECT,
        message=RESET_BODY.format(url=url, hours=settings.PASSWORD_RESET_TIMEOUT // 3600),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=False,
    )
    logger.info("Password reset email sent to user %s", user_id)


@shared_task
def prune_expired_tokens() -> None:
    """
    Beat, daily. Every login writes an OutstandingToken plus a UserSession, and
    nothing ever deleted them — on a long-lived instance those tables grow
    without bound. Once a refresh token is past its expiry it can't be used
    whether or not it's blacklisted, so the rows carry no security value.
    """
    now = timezone.now()

    blacklisted, _ = BlacklistedToken.objects.filter(token__expires_at__lt=now).delete()
    outstanding, _ = OutstandingToken.objects.filter(expires_at__lt=now).delete()
    sessions, _ = UserSession.objects.filter(expires_at__lt=now).delete()

    logger.info(
        "Pruned %s blacklisted, %s outstanding tokens and %s sessions",
        blacklisted,
        outstanding,
        sessions,
    )
