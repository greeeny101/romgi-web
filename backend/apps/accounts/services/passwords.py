"""
Server-side password policy.

AUTH_PASSWORD_VALIDATORS has been configured since the project started but was
never actually executed on the API path: register called
User.objects.create_user(), which calls set_password() directly and skips
validation entirely. The only check was minlength={8} in the browser, so
"12345678" was an acceptable password. Everything that sets a password goes
through validate_or_422 now.
"""

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from ninja.errors import HttpError


def validate_or_422(password: str, user=None) -> None:
    """
    Run the configured validators, translating Django's ValidationError into
    the JSON error shape the SPA already understands (ApiError reads
    `body.detail`).

    Pass `user` — even an unsaved instance — so UserAttributeSimilarityValidator
    has something to compare against; without it that validator silently passes.
    """
    try:
        validate_password(password, user=user)
    except ValidationError as exc:
        raise HttpError(422, " ".join(exc.messages)) from exc
