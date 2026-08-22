"""
Password reset links.

Uses Django's own PasswordResetTokenGenerator rather than a new model: the
tokens are stateless and self-invalidating, because the hash covers the user's
current password hash and last_login. Setting a new password (or simply logging
in again) therefore voids every outstanding link automatically, which is exactly
the single-use behaviour this needs and one less table to prune.
"""

from django.conf import settings
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

from ..models import User

token_generator = PasswordResetTokenGenerator()


def build_reset_url(user: User) -> str:
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = token_generator.make_token(user)
    return f"{settings.FRONTEND_BASE_URL}/reset-password?uid={uid}&token={token}"


def user_from_token(uidb64: str, token: str) -> User | None:
    """Resolve a reset link back to its user, or None if it doesn't check out."""
    try:
        uid = urlsafe_base64_decode(uidb64).decode()
        user = User.objects.get(pk=uid, is_active=True)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        return None
    if not token_generator.check_token(user, token):
        return None
    return user
