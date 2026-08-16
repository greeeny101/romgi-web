"""
Celery task orchestrating a torrent→HTTP resolution via a debrid provider —
ports lib/services/debrid_service.dart's resolveTorrentLink() find/poll/
unrestrict loop (2s initial poll, doubling backoff capped at 15s, 3-minute
overall timeout, 10s fixed wait on rate-limit) onto our task/model shape.

Runs as a single long-lived Celery task with an internal sleep loop —
same pattern as downloads.tasks.http_download — rather than being
re-dispatched between polls. Once resolved, hands off to http_download
exactly like a plain HTTP link; link_torrent_magnet/file_index are left
untouched so downloads.tasks._handle_debrid_expiry can revert to torrent
form if the CDN link expires mid-download.
"""

import time

from celery import shared_task

from apps.accounts.models import UserSettings
from apps.credentials.models import EncryptedCredential
from apps.downloads.models import DownloadTask
from apps.downloads.progress import push_progress, push_status
from apps.downloads.tasks import _should_abort, dispatch_next_for_user, http_download

from .base import DebridCaching, DebridError, DebridFileRequest, DebridNotCached, DebridReady
from .magnet import infohash_from_magnet
from .registry import registry

OVERALL_TIMEOUT = 180.0
INITIAL_DELAY = 2.0
MAX_DELAY = 15.0
RATE_LIMIT_DELAY = 10.0


def _fail(task: DownloadTask, message: str) -> None:
    task.status = "failed"
    task.error = message
    task.save(update_fields=["status", "error", "updated_at"])
    push_status(task)
    dispatch_next_for_user(task.user_id)


@shared_task
def resolve_debrid_link(task_id: int) -> None:
    task = DownloadTask.objects.get(id=task_id)
    if task.status != "downloading":
        return

    settings_obj = UserSettings.objects.filter(user_id=task.user_id).first()
    provider_id = settings_obj.debrid_provider_id if settings_obj else "torbox"
    provider = registry.by_id(provider_id)
    if provider is None:
        _fail(task, f"Unknown debrid provider: {provider_id}")
        return

    credential = EncryptedCredential.objects.filter(user_id=task.user_id, provider=provider_id).first()
    api_key = (credential.data or {}).get("api_key") if credential else None
    if not provider.is_configured(api_key):
        _fail(task, f"{provider.info.name} is not configured")
        return

    infohash = infohash_from_magnet(task.link_torrent_magnet)
    if infohash is None:
        _fail(task, "Could not determine torrent infohash")
        return

    req = DebridFileRequest(
        infohash=infohash,
        magnet=task.link_torrent_magnet,
        file_index=task.link_torrent_file_index or 0,
        file_path="",
        expected_size=task.link_size,
    )

    deadline = time.monotonic() + OVERALL_TIMEOUT
    delay = INITIAL_DELAY

    while True:
        if _should_abort(task.id):
            return

        result = provider.resolve_file(req, api_key)

        if isinstance(result, DebridReady):
            task.link_url = result.url
            task.link_host = provider.info.name
            task.link_requires_auth = False
            task.link_is_torrent = False
            task.debrid_resolved = True
            if result.size:
                task.link_size = result.size
            task.save()
            push_status(task)
            http_download.delay(task.id)
            return

        if isinstance(result, DebridNotCached):
            _fail(task, f"{provider.info.name}: file not cached")
            return

        if isinstance(result, DebridError):
            if result.auth_error or result.permanent:
                _fail(task, result.message)
                return
            if time.monotonic() > deadline:
                _fail(task, result.message)
                return
            time.sleep(RATE_LIMIT_DELAY if result.rate_limited else delay)
            delay = min(delay * 2, MAX_DELAY)
            continue

        # DebridCaching
        task.progress = result.progress or 0.0
        task.save(update_fields=["progress", "updated_at"])
        push_progress(task)
        if time.monotonic() > deadline:
            _fail(task, f"{provider.info.name}: timed out waiting to cache")
            return
        time.sleep(delay)
        delay = min(delay * 2, MAX_DELAY)
