from celery import shared_task
from django.utils import timezone

from .models import EncryptedCredential
from .services import internet_archive


@shared_task
def internet_archive_login(user_id: int, username: str, password: str) -> None:
    """API-dispatched (202 + poll via AsyncResult, see api.py). Raising
    here is intentional — the login result is read back through Celery's
    result backend as the task's success/failure state and exception
    message, not a return value."""
    result = internet_archive.login(username, password)
    EncryptedCredential.objects.update_or_create(
        user_id=user_id,
        provider="internet_archive",
        defaults={
            "data": result,
            "status": "ok",
            "failure_count": 0,
            "last_validated_at": timezone.now(),
        },
    )


@shared_task
def internet_archive_revalidate() -> None:
    """Beat, daily — re-validates any IA session stale beyond the 24h
    threshold, same as the app's ensureFresh() but run proactively rather
    than only when a user happens to open the app."""
    for credential in EncryptedCredential.objects.filter(provider="internet_archive"):
        internet_archive.ensure_fresh(credential)
