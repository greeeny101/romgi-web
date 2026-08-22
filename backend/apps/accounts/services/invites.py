"""
Invite issuance and redemption.

This instance does not have open registration: `POST /api/auth/register`
requires a code that a staff user created beforehand. That's the whole
gate — there is no email-verification step, because an invite handed to a
specific person already establishes who is joining, and requiring SMTP would
make the instance unusable for operators who don't run a mail server.
"""

from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from ninja.errors import HttpError

from ..models import Invite, User


def create_invite(
    *,
    created_by: User | None = None,
    email: str = "",
    note: str = "",
    expires_days: int | None = None,
) -> Invite:
    days = settings.INVITE_EXPIRY_DAYS if expires_days is None else expires_days
    return Invite.objects.create(
        created_by=created_by,
        email=(email or "").strip(),
        note=note,
        # 0 or negative means "never expires" — useful for a long-lived code an
        # operator keeps for themselves.
        expires_at=timezone.now() + timedelta(days=days) if days > 0 else None,
    )


def redeem(code: str, email: str) -> Invite:
    """
    Claim an invite for `email`, or raise.

    Must run inside the caller's transaction: it takes a row lock so two
    requests racing on the same code can't both pass — without it, a leaked
    code could be redeemed by any number of people simultaneously.
    """
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("redeem() must be called inside a transaction")

    invite = Invite.objects.select_for_update().filter(code=(code or "").strip()).first()

    # One message for every rejection: a code that is merely expired should not
    # be distinguishable from one that was never valid, or the endpoint becomes
    # an oracle for guessing codes.
    if invite is None or not invite.is_valid_for(email):
        raise HttpError(403, "This invite code is not valid.")

    invite.used_at = timezone.now()
    invite.save(update_fields=["used_at"])
    return invite
