"""
Celery tasks for the HTTP download pipeline — ports
lib/services/download_service.dart's state machine (see the plan's porting
reference map). Torrent links either route to apps.torrents (qBittorrent)
or, when the caller has debrid enabled, to apps.downloads.debrid — this
module owns the plain-HTTP path plus the shared failover/completion/
extraction machinery both of those hand back into.

Two deliberate adaptations from the Dart original, both noted inline where
they matter:
  - No Dio-style HEAD-probe-then-trust-Accept-Ranges dance. Each attempt
    just sends `Range` when a partial file exists and checks whether the
    server actually replied 206 vs 200 — self-correcting, no separate probe
    request needed.
  - Pause/cancel isn't a live socket interrupt (there's no per-task
    CancelToken to reach into a running Celery task). Instead the copy loop
    polls its own DB row at the same cadence as its progress push and exits
    early if the row was flipped to `paused` or deleted.
"""

from __future__ import annotations

import logging
import os
import time

import requests
from celery import shared_task
from django.conf import settings as django_settings
from django.utils import timezone

from apps.accounts.models import UserSettings
from apps.catalog.models import CatalogBuild, Entry
from apps.credentials.models import EncryptedCredential
from apps.credentials.services import internet_archive as ia

from .adapters.registry import registry
from .extraction import ExtractionError, extract_archive
from .link_resolver import AUTH_GATED_SCORE, rank_links
from .models import DownloadTask
from .playlist import playlist_file_name
from .progress import push_progress, push_status

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Mobile Safari/537.36"
)
MAX_HTTP_RETRIES = 3
RETRYABLE_SUBSTRINGS = ("ssl", "handshake", "certificate", "tls", "connection reset", "connection refused")
DB_WRITE_INTERVAL = 2.0
PROGRESS_PUSH_INTERVAL = 1.0
ARCHIVE_EXTENSIONS = (".zip", ".7z")
# A debrid-resolved CDN link failing with any of these is treated as "the
# link expired," not a generic error — bounded relink-and-retry below,
# ports download_service.dart's isDebridExpiry condition + _maxDebridRelinkAttempts.
DEBRID_EXPIRY_STATUSES = (401, 403, 404, 410)
MAX_DEBRID_RELINK_ATTEMPTS = 2


def task_dir(task_id: int) -> str:
    path = os.path.join(django_settings.STAGED_FILES_DIR, str(task_id))
    os.makedirs(path, exist_ok=True)
    return path


def _max_concurrent(user_id) -> int:
    settings_obj = UserSettings.objects.filter(user_id=user_id).first()
    return settings_obj.max_concurrent_downloads if settings_obj else 3


def dispatch_next_for_user(user_id) -> None:
    """Concurrency gate: starts as many pending tasks as there are free
    slots under the user's max_concurrent_downloads (0 = unlimited)."""
    active = DownloadTask.objects.filter(user_id=user_id, status="downloading").count()
    max_conc = _max_concurrent(user_id)
    if max_conc and active >= max_conc:
        return
    pending_qs = DownloadTask.objects.filter(user_id=user_id, status="pending").order_by("created_at")
    if max_conc:
        pending_qs = pending_qs[: max_conc - active]
    for task in pending_qs:
        start_download.delay(task.id)


@shared_task
def dispatch_pending_downloads() -> None:
    """Beat safety net — reconciles the queue in case a completion
    handler's dispatch call was missed (e.g. a worker restart)."""
    user_ids = DownloadTask.objects.filter(status="pending").values_list("user_id", flat=True).distinct()
    for user_id in user_ids:
        dispatch_next_for_user(user_id)


def _should_abort(task_id: int) -> bool:
    status = DownloadTask.objects.filter(id=task_id).values_list("status", flat=True).first()
    return status is None or status == "paused"


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, (requests.exceptions.ConnectionError, requests.exceptions.Timeout)):
        return True
    text = str(exc).lower()
    return any(s in text for s in RETRYABLE_SUBSTRINGS)


def _apply_link(task: DownloadTask, link) -> None:
    task.link_name = link.name
    task.link_url = link.url
    task.link_filename = link.filename
    task.link_host = link.host
    task.link_size = link.size
    task.link_source_id = link.source_id
    task.link_requires_auth = link.requires_auth
    task.link_is_torrent = link.torrent_id is not None
    task.link_torrent_magnet = (link.torrent.magnet or "") if link.torrent_id else ""
    task.link_torrent_file_index = link.torrent_file_index
    task.torrent_hash = ""
    # A failover candidate is a different link entirely — any debrid
    # resolution state belongs to the link being abandoned, not this one.
    task.debrid_resolved = False
    task.debrid_relink_attempts = 0


def _find_failover_link(task: DownloadTask):
    build = CatalogBuild.objects.filter(status="active").order_by("-started_at").first()
    if build is None:
        return None
    entry = Entry.objects.filter(build=build, slug=task.slug).first()
    if entry is None:
        return None
    settings_obj = UserSettings.objects.filter(user_id=task.user_id).first()
    # Bug fix: this used to be called with no third argument, so
    # ia_logged_in silently defaulted to False on every failover check —
    # every Internet-Archive-gated link got treated as unusable even for a
    # user with a valid, working IA session (confirmed live: a real
    # logged-in user's torrent failover landed on an IA link and was
    # rejected with "Internet Archive login required" anyway).
    credential = EncryptedCredential.objects.filter(user_id=task.user_id, provider="internet_archive").first()
    ia_logged_in = credential is not None and ia.is_logged_in(credential)
    ranked = rank_links(
        entry.links.select_related("source", "torrent"), settings_obj, ia_logged_in=ia_logged_in
    )
    tried = set(task.failed_urls) | {task.link_url}
    for candidate in ranked:
        if candidate.score > AUTH_GATED_SCORE and candidate.link.url not in tried:
            return candidate.link
    return None


def _handle_download_failure(task: DownloadTask, error_text: str) -> None:
    next_link = _find_failover_link(task)
    if next_link is not None:
        task.failed_urls = list(set(task.failed_urls) | {task.link_url})
        _apply_link(task, next_link)
        task.status = "pending"
        task.progress = 0.0
        task.downloaded_bytes = 0
        task.total_bytes = 0
        task.error = ""
        task.save()
        push_status(task)
        start_download.delay(task.id)
        return

    task.status = "failed"
    task.error = error_text
    task.save(update_fields=["status", "error", "updated_at"])
    push_status(task)
    dispatch_next_for_user(task.user_id)


def _handle_debrid_expiry(task: DownloadTask) -> None:
    """Ports download_service.dart's debrid-expiry handling: revert to
    torrent form and re-resolve, up to MAX_DEBRID_RELINK_ATTEMPTS times,
    before giving up for good. link_torrent_magnet/file_index were never
    touched while debrid_resolved was True, so reverting is just flipping
    the flags back — no data to restore."""
    task.debrid_relink_attempts += 1
    task.link_is_torrent = True
    task.debrid_resolved = False

    if task.debrid_relink_attempts <= MAX_DEBRID_RELINK_ATTEMPTS:
        task.status = "pending"
        task.progress = 0.0
        task.downloaded_bytes = 0
        task.total_bytes = 0
        task.error = ""
        task.save()
        push_status(task)
        start_download.delay(task.id)
        return

    task.status = "failed"
    task.error = "Debrid link expired and re-resolution kept failing"
    task.save()
    push_status(task)
    dispatch_next_for_user(task.user_id)


@shared_task(bind=True)
def start_download(self, task_id: int) -> None:
    try:
        task = DownloadTask.objects.get(id=task_id)
    except DownloadTask.DoesNotExist:
        return
    if task.status != "pending":
        return

    adapter = registry.adapter_for(task)
    if not adapter.can_start_download(task, task.user):
        task.status = "failed"
        task.error = adapter.auth_error
        task.save(update_fields=["status", "error", "updated_at"])
        push_status(task)
        dispatch_next_for_user(task.user_id)
        return

    task.status = "downloading"
    task.celery_task_id = self.request.id or ""
    task.save(update_fields=["status", "celery_task_id", "updated_at"])
    push_status(task)

    if task.link_is_torrent:
        # Lazy imports — both apps.torrents.tasks and apps.downloads.debrid.tasks
        # import helpers from this module at load time, so a module-level
        # import here would be circular.
        settings_obj = UserSettings.objects.filter(user_id=task.user_id).first()
        if settings_obj and settings_obj.debrid_enabled:
            from apps.downloads.debrid.tasks import resolve_debrid_link

            resolve_debrid_link.delay(task_id)
        else:
            from apps.torrents.tasks import add_torrent

            add_torrent.delay(task_id)
    else:
        http_download.delay(task_id)


@shared_task
def http_download(task_id: int) -> None:
    task = DownloadTask.objects.get(id=task_id)
    if task.status != "downloading":
        return

    directory = task_dir(task.id)
    filename = task.link_filename or task.link_name or f"download-{task.id}"
    dest_path = os.path.join(directory, filename)

    existing_size = os.path.getsize(dest_path) if os.path.exists(dest_path) else 0
    if task.link_size and existing_size == task.link_size:
        _finish_download(task, dest_path)
        return
    if task.link_size and existing_size > task.link_size:
        os.remove(dest_path)

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive",
    }
    adapter = registry.adapter_for(task)
    adapter.prepare_headers(headers, task)

    task_attempt_start_bytes = os.path.getsize(dest_path) if os.path.exists(dest_path) else 0
    start_time = time.monotonic()
    last_db_write = 0.0
    last_push = 0.0
    retry_count = 0

    while True:
        current_size = os.path.getsize(dest_path) if os.path.exists(dest_path) else 0
        attempt_headers = dict(headers)
        if current_size > 0:
            attempt_headers["Range"] = f"bytes={current_size}-"

        try:
            with requests.get(task.link_url, headers=attempt_headers, stream=True, timeout=30) as resp:
                if resp.status_code == 416:
                    if os.path.exists(dest_path):
                        os.remove(dest_path)
                    task.downloaded_bytes = 0
                    task.progress = 0.0
                    task.status = "pending"
                    task.save(update_fields=["downloaded_bytes", "progress", "status", "updated_at"])
                    push_status(task)
                    start_download.delay(task.id)
                    return

                if resp.status_code in DEBRID_EXPIRY_STATUSES and task.debrid_resolved:
                    _handle_debrid_expiry(task)
                    return
                if resp.status_code in (401, 403):
                    adapter = registry.adapter_for(task)
                    adapter.on_auth_failure(task, task.user)
                    task.status = "failed"
                    task.error = adapter.auth_error
                    task.save(update_fields=["status", "error", "updated_at"])
                    push_status(task)
                    dispatch_next_for_user(task.user_id)
                    return

                resp.raise_for_status()

                range_honored = resp.status_code == 206
                mode = "ab" if (current_size > 0 and range_honored) else "wb"
                received = current_size if range_honored else 0

                content_length = resp.headers.get("Content-Length")
                total_bytes = (int(content_length) + received) if content_length else task.link_size

                aborted = False
                with open(dest_path, mode) as fh:
                    for chunk in resp.iter_content(chunk_size=64 * 1024):
                        if not chunk:
                            continue
                        fh.write(chunk)
                        received += len(chunk)

                        now = time.monotonic()
                        elapsed = now - start_time
                        bps = int((received - task_attempt_start_bytes) / elapsed) if elapsed > 0 else 0

                        task.downloaded_bytes = received
                        task.total_bytes = total_bytes
                        task.progress = received / total_bytes if total_bytes else 0.0
                        task.bytes_per_second = bps

                        if now - last_push >= PROGRESS_PUSH_INTERVAL:
                            push_progress(task)
                            last_push = now
                            if _should_abort(task.id):
                                aborted = True
                                break
                        if now - last_db_write >= DB_WRITE_INTERVAL:
                            task.save(
                                update_fields=[
                                    "downloaded_bytes",
                                    "total_bytes",
                                    "progress",
                                    "bytes_per_second",
                                    "updated_at",
                                ]
                            )
                            last_db_write = now

                if aborted:
                    task.save(
                        update_fields=["downloaded_bytes", "total_bytes", "progress", "bytes_per_second", "updated_at"]
                    )
                    return
            break
        except requests.exceptions.RequestException as exc:
            retry_count += 1
            if retry_count > MAX_HTTP_RETRIES or not _is_retryable(exc):
                _handle_download_failure(task, str(exc))
                return
            time.sleep(2 ** (retry_count - 1))
            continue

    final_size = os.path.getsize(dest_path)
    if task.link_size and final_size != task.link_size:
        os.remove(dest_path)
        task.status = "failed"
        task.error = f"Download incomplete ({final_size} of {task.link_size} bytes)"
        task.save(update_fields=["status", "error", "updated_at"])
        push_status(task)
        dispatch_next_for_user(task.user_id)
        return

    task.downloaded_bytes = final_size
    task.total_bytes = final_size
    task.progress = 1.0
    task.save(update_fields=["downloaded_bytes", "total_bytes", "progress", "updated_at"])
    _finish_download(task, dest_path)


def _should_extract(archive_path: str, task: DownloadTask) -> bool:
    if not archive_path.lower().endswith(ARCHIVE_EXTENSIONS):
        return False
    settings_obj = UserSettings.objects.filter(user_id=task.user_id).first()
    if settings_obj is None or settings_obj.auto_extract_disabled:
        return False
    return not settings_obj.extract_disabled_platforms.filter(id=task.platform_id).exists()


def _finish_download(task: DownloadTask, archive_path: str) -> None:
    if not _should_extract(archive_path, task):
        task.staged_file = os.path.relpath(archive_path, task_dir(task.id))
        task.status = "completed"
        task.completed_at = timezone.now()
        task.expires_at = task.completed_at + timezone.timedelta(hours=django_settings.STAGED_FILE_RETENTION_HOURS)
        task.save(update_fields=["staged_file", "status", "completed_at", "expires_at", "updated_at"])
        push_status(task)
        _after_completion(task)
        return

    task.status = "extracting"
    task.save(update_fields=["status", "updated_at"])
    push_status(task)
    extract_archive_task.delay(task.id, archive_path)


@shared_task
def extract_archive_task(task_id: int, archive_path: str) -> None:
    task = DownloadTask.objects.get(id=task_id)
    out_dir = os.path.join(task_dir(task.id), "extracted")
    last_push = 0.0

    def on_progress(extracted: int, total: int) -> None:
        nonlocal last_push
        now = time.monotonic()
        task.progress = extracted / total if total else 1.0
        if now - last_push >= 0.2:
            push_progress(task)
            last_push = now

    try:
        result_path = extract_archive(archive_path, out_dir, on_progress=on_progress)
    except ExtractionError:
        task.status = "failed"
        task.error = "Extraction failed — the archive may be corrupt"
        task.save(update_fields=["status", "error", "updated_at"])
        push_status(task)
        dispatch_next_for_user(task.user_id)
        return

    os.remove(archive_path)
    task.staged_file = os.path.relpath(result_path, task_dir(task.id))
    task.status = "completed"
    task.completed_at = timezone.now()
    task.expires_at = task.completed_at + timezone.timedelta(hours=django_settings.STAGED_FILE_RETENTION_HOURS)
    task.progress = 1.0
    task.save(update_fields=["staged_file", "status", "completed_at", "expires_at", "progress", "updated_at"])
    push_status(task)
    _after_completion(task)


def _after_completion(task: DownloadTask) -> None:
    dispatch_next_for_user(task.user_id)
    if task.group_key:
        write_playlist.delay(task.id)


@shared_task
def write_playlist(task_id: int) -> None:
    """
    Ports playlist_writer.dart's "wait for every disc member to finish"
    gate and duplicate-index guard. The output itself is adapted: the
    original writes a local .m3u referencing files that already share one
    on-device folder. Here each disc's staged file lives behind its own
    DownloadTask's `/downloads/{id}/file` endpoint, so the playlist lists
    those instead — still a playable M3U for a client fetching relative to
    the API origin.
    """
    task = DownloadTask.objects.get(id=task_id)
    if not task.group_key:
        return

    members = list(
        DownloadTask.objects.filter(user=task.user, group_key=task.group_key).order_by("group_index")
    )
    if len(members) < 2 or any(m.status != "completed" for m in members):
        return

    expected_total = max([task.group_total or 0] + [m.group_total or 0 for m in members])
    if expected_total:
        if len(members) < expected_total:
            return
        if len({m.group_index for m in members if m.group_index is not None}) < expected_total:
            return

    lines = [f"/api/downloads/{m.id}/file" for m in members]
    filename = playlist_file_name(task.group_title or members[0].title)
    with open(os.path.join(task_dir(task.id), filename), "w") as f:
        f.write("\n".join(lines) + "\n")

    task.playlist_file = filename
    task.save(update_fields=["playlist_file"])


@shared_task
def cleanup_expired_staged_files() -> None:
    """Beat safety net (hourly): enforces STAGED_FILE_RETENTION_HOURS for
    claimed downloads and STAGED_FILE_UNCLAIMED_DAYS for ones nobody ever
    retrieved. Only removes files on disk — DownloadTask rows persist for
    history, matching the plan's retention note."""
    import shutil

    now = timezone.now()
    expired = DownloadTask.objects.filter(status="completed", expires_at__lt=now, staged_file__gt="")
    unclaimed_cutoff = now - timezone.timedelta(days=django_settings.STAGED_FILE_UNCLAIMED_DAYS)
    unclaimed = DownloadTask.objects.filter(
        status="completed",
        first_retrieved_at__isnull=True,
        completed_at__lt=unclaimed_cutoff,
        staged_file__gt="",
    )

    for task in (expired | unclaimed).distinct():
        directory = os.path.join(django_settings.STAGED_FILES_DIR, str(task.id))
        if os.path.isdir(directory):
            shutil.rmtree(directory, ignore_errors=True)
        task.staged_file = ""
        task.save(update_fields=["staged_file"])


# Celery's autodiscover_tasks() only finds a `tasks.py` at the top level of
# each Django app package — apps.downloads.debrid is a submodule of the
# downloads app, not its own app, so it's invisible to that discovery.
# Importing it here (after everything it needs from this module is already
# defined above) registers its @shared_task functions as a side effect.
from apps.downloads.debrid import tasks as _debrid_tasks  # noqa: E402,F401
