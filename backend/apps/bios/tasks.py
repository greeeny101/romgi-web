"""
The BIOS transfer.

One task owns the whole request from start to finish, which is the main
structural difference from apps.romsets: there, qBittorrent owns the bytes
out-of-process, so a beat task (`poll_active_romsets`) has to keep asking it
what happened. Here the worker performs the GETs itself and therefore
already knows, so it reports its own progress and no periodic task is
needed. The shape of the transfer loop — throttled DB writes, throttled
WebSocket pushes, an abort poll on the same cadence — is taken from
apps.downloads.tasks.http_download.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import timedelta

from celery import shared_task
from django.conf import settings as django_settings
from django.utils import timezone

from apps.common import archive_org
from apps.downloads.extraction import ExtractionError, extract_archive
from apps.downloads.tasks import _is_retryable

from .files import destination, is_safe
from .models import BiosDownload, BiosFile
from .progress import push_progress, push_status

logger = logging.getLogger(__name__)

# Matching apps.downloads.tasks: a push every 500ms is smooth in the browser,
# and a DB write every 2s keeps a long transfer off the write path. BIOS
# files are small enough that most finish inside one interval, which is why
# progress is also pushed at every file boundary regardless.
PROGRESS_PUSH_INTERVAL = 0.5
DB_WRITE_INTERVAL = 2.0

# How long a row may sit in "pending" before the beat safety net assumes its
# start message was lost. Generous on purpose: a legitimately queued message
# can wait a while behind a backlog, and re-dispatching one early is only
# wasted work, never a second transfer — see dispatch_pending_bios.
STALE_PENDING_SECONDS = 300

# Per-file retries before the whole request gives up. A BIOS pack is many
# small transfers rather than one big one, so it gets many independent
# chances to hit an archive.org stall: a 115-file pack failed at file 42 on
# a single 60s read timeout and threw away 41 good files' worth of progress.
# Retrying resumes from the partial rather than restarting the file.
MAX_FILE_RETRIES = 3

# Archives we can actually open. extraction.extract_archive dispatches
# anything that isn't .zip to py7zr, so an unguarded .rar reaches it as a
# raw library error rather than a message anyone can act on.
EXTRACTABLE_EXTENSIONS = (".zip", ".7z")


def save_root(bios: BiosDownload) -> str:
    """The absolute directory this request writes into, as Celery sees it."""
    return os.path.join(django_settings.ROM_LIBRARY_DIR, bios.save_dir)


def _persist(bios: BiosDownload, *fields: str) -> bool:
    """Write `fields` from the instance, tolerating the row being gone.

    Returns False when it matched nothing, which means the request was
    cancelled while the worker was mid-transfer.

    A plain `save(update_fields=...)` cannot be used on the transfer path:
    since Django 4.2 it raises `DatabaseError: Save with update_fields did
    not affect any rows.` when the row has disappeared, and cancelling a
    BIOS download deletes the row out from under a worker that is still
    writing chunks. That turned an ordinary cancel into a task traceback.
    """
    values = {f: getattr(bios, f) for f in fields}
    values["updated_at"] = timezone.now()
    return BiosDownload.objects.filter(id=bios.id).update(**values) > 0


def _should_abort(bios_id: int) -> bool:
    """True when the user paused or cancelled since the last chunk.

    A DB read rather than a Redis flag, matching downloads.tasks — the row
    is the single source of truth for the request's state, and a cancelled
    row simply isn't there any more.
    """
    status = BiosDownload.objects.filter(id=bios_id).values_list("status", flat=True).first()
    return status is None or status == "paused"


def _fail(bios: BiosDownload, message: str) -> None:
    logger.warning("BIOS download %s failed: %s", bios.id, message)
    bios.status = "failed"
    bios.error = message
    bios.bytes_per_second = 0
    if _persist(bios, "status", "error", "bytes_per_second"):
        push_status(bios)


def _complete(bios: BiosDownload) -> None:
    bios.status = "completed"
    bios.progress = 1.0
    bios.bytes_per_second = 0
    bios.completed_at = timezone.now()
    if _persist(bios, "status", "progress", "bytes_per_second", "completed_at"):
        push_status(bios)


def _pause(bios: BiosDownload) -> None:
    """Persist what the aborted transfer got through. The status column is
    left alone: `paused` was set by the API and a cancelled row is gone."""
    bios.bytes_per_second = 0
    _persist(bios, "downloaded_bytes", "progress", "bytes_per_second")


@shared_task(bind=True)
def start_bios_download(self, bios_id: int) -> None:
    # Claim the row with one conditional UPDATE rather than read-then-write.
    # Two dispatches for the same id can legitimately exist — the beat
    # safety net adds one whenever it can't tell a lost message from a
    # slow queue — and only the worker whose UPDATE matches may proceed.
    # Anything else (already running, paused, cancelled) matches nothing
    # and returns, so a duplicate is a no-op instead of a second transfer.
    claimed = BiosDownload.objects.filter(id=bios_id, status="pending").update(
        status="fetching_metadata",
        error="",
        celery_task_id=self.request.id or "",
        updated_at=timezone.now(),
    )
    if not claimed:
        return

    bios = BiosDownload.objects.filter(id=bios_id).first()
    if bios is None:  # cancelled in the moment between the claim and the read
        return
    push_status(bios)

    wanted = list(bios.files.filter(wanted=True))
    if not wanted:
        _fail(bios, "Nothing selected to download.")
        return

    directory = save_root(bios)
    try:
        os.makedirs(directory, exist_ok=True)
    except OSError as exc:
        _fail(bios, f"Could not create {bios.save_dir}: {exc}")
        return

    bios.total_bytes = sum(f.size for f in wanted)
    bios.status = "downloading"
    _persist(bios, "total_bytes", "status")
    push_status(bios)

    # Progress spans the whole request, not one file, so the bar moves
    # monotonically across a 40-file pack instead of resetting per file.
    done_bytes = sum(f.size for f in wanted if f.done)
    started = time.monotonic()
    start_bytes = done_bytes
    last_push = 0.0
    last_write = 0.0

    for entry in wanted:
        if entry.done:
            continue
        if _should_abort(bios.id):
            _pause(bios)
            return
        # Re-checked here and not only at selection time: the row could have
        # been written by an older build of the filter, and this is the last
        # point before a remote-supplied name reaches the filesystem.
        if not is_safe(entry.name):
            _fail(bios, f"Refusing to write {entry.name}: it points outside the library folder.")
            return

        file_base = done_bytes

        def on_progress(received: int, total: int, *, base=file_base) -> None:
            nonlocal last_push, last_write
            now = time.monotonic()
            elapsed = now - started
            bios.downloaded_bytes = base + received
            bios.progress = bios.downloaded_bytes / bios.total_bytes if bios.total_bytes else 0.0
            bios.bytes_per_second = int((bios.downloaded_bytes - start_bytes) / elapsed) if elapsed > 0 else 0
            if now - last_push >= PROGRESS_PUSH_INTERVAL:
                push_progress(bios)
                last_push = now
            if now - last_write >= DB_WRITE_INTERVAL:
                _persist(bios, "downloaded_bytes", "progress", "bytes_per_second")
                last_write = now

        attempt = 0
        while True:
            try:
                received, completed = archive_org.stream_file(
                    bios.identifier,
                    entry.name,
                    destination(directory, entry.name),
                    user=bios.user,
                    expected_size=entry.size,
                    md5=entry.md5 or None,
                    on_progress=on_progress,
                    should_abort=lambda: _should_abort(bios.id),
                )
                break
            except archive_org.ArchiveOrgError as exc:
                # stream_file wraps the requests exception, so the original
                # is on __cause__ — a bare read timeout matches none of
                # _is_retryable's substrings but is a requests.Timeout.
                attempt += 1
                if attempt > MAX_FILE_RETRIES or not _is_retryable(exc.__cause__ or exc):
                    # .update() rather than .save(): a cancel deletes the
                    # parent row and cascades this one away mid-transfer.
                    BiosFile.objects.filter(id=entry.id).update(error=str(exc))
                    _fail(bios, str(exc))
                    return
                logger.info(
                    "BIOS download %s: retrying %s (attempt %s/%s) after %s",
                    bios.id,
                    entry.name,
                    attempt,
                    MAX_FILE_RETRIES,
                    exc,
                )
                time.sleep(2 ** (attempt - 1))
                if _should_abort(bios.id):
                    _pause(bios)
                    return
            except OSError as exc:
                _fail(bios, f"Could not write {entry.name}: {exc}")
                return

        if not completed:
            bios.downloaded_bytes = file_base + received
            bios.progress = bios.downloaded_bytes / bios.total_bytes if bios.total_bytes else 0.0
            _pause(bios)
            return

        done_bytes = file_base + entry.size
        BiosFile.objects.filter(id=entry.id).update(progress=1.0, done=True, error="")

        bios.downloaded_bytes = done_bytes
        bios.progress = done_bytes / bios.total_bytes if bios.total_bytes else 0.0
        if not _persist(bios, "downloaded_bytes", "progress"):
            return  # cancelled while this file was in flight
        push_progress(bios)

    if bios.extract:
        extracted = _extract_downloaded(bios, directory, wanted)
        if extracted is False:
            return

    _complete(bios)


@shared_task
def dispatch_pending_bios() -> None:
    """Beat safety net — re-dispatches requests whose start message was lost.

    `enqueue_bios` hands off with `transaction.on_commit(...delay())`, so a
    broker hiccup, or a worker that prefetched the message and was killed
    before running it, strands the row in "pending" with nothing left to
    start it. Observed exactly that: a worker holding one prefetched
    `start_bios_download` died, and the row sat pending with no way to
    recover it from the UI short of pausing and resuming it.

    The same safety net exists for single-ROM downloads
    (downloads.tasks.dispatch_pending_downloads) for the same reason.

    Re-dispatching a row whose message is merely queued behind a backlog is
    harmless: start_bios_download claims the row with a conditional UPDATE,
    so whichever copy runs first wins and the rest return immediately.
    """
    cutoff = timezone.now() - timedelta(seconds=STALE_PENDING_SECONDS)
    stale = BiosDownload.objects.filter(status="pending", updated_at__lt=cutoff).values_list("id", flat=True)
    for bios_id in stale:
        logger.info("Re-dispatching BIOS download %s: still pending, start message presumed lost", bios_id)
        start_bios_download.delay(bios_id)


def _extract_downloaded(bios: BiosDownload, directory: str, files: list[BiosFile]) -> bool:
    """Expand any archives the request fetched, in place. Returns False when
    it failed and the row has already been marked failed.

    A BIOS pack is very often a single .zip whose contents are what the
    emulator actually wants, so this is the common case rather than an edge
    one. Unlike a ROM set there is no space check first: the archives here
    are megabytes, not tens of gigabytes.
    """
    archives = [f for f in files if f.name.lower().endswith(EXTRACTABLE_EXTENSIONS)]
    if not archives:
        return True

    bios.status = "extracting"
    bios.bytes_per_second = 0
    if not _persist(bios, "status", "bytes_per_second"):
        return False
    push_status(bios)

    for entry in archives:
        path = destination(directory, entry.name)
        if not os.path.exists(path):
            continue
        try:
            extract_archive(path, directory)
        except (ExtractionError, OSError) as exc:
            _fail(bios, f"Could not extract {entry.name}: {exc}")
            return False
        # extract_archive deliberately leaves its source in place; for BIOS
        # the archive itself is never what the emulator wants, so it goes.
        try:
            os.remove(path)
        except OSError:
            logger.warning("Extracted %s but could not remove the archive", path, exc_info=True)

    return True
