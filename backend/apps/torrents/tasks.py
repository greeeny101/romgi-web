"""
Celery tasks driving qBittorrent for the BitTorrent download path. Ports
TorrentServiceImpl.kt's selective-per-file-download and
never-seed-after-completion semantics onto qBittorrent's Web API — see the
plan's porting reference map. Scope: magnet-only (the catalog's optional
.torrent-file fallback isn't wired up here; MiNERVA, the only torrent
source in the plan's v1 scope, always provides a magnet).

Unlike the Kotlin engine's alert-driven METADATA_RECEIVED handler, this
polls torrents_files() with retries to detect when qBittorrent has resolved
the file list — the Web API has no push/webhook equivalent to subscribe to.
"""

from __future__ import annotations

import logging
import os
import shutil
import time

import qbittorrentapi
from celery import shared_task
from django.conf import settings as django_settings

from apps.downloads.debrid.magnet import infohash_from_magnet
from apps.downloads.models import DownloadTask
from apps.downloads.progress import push_progress, push_status
from apps.downloads.tasks import _finish_download, _handle_download_failure, task_dir

from .client import FINISHED_STATES, client
from .ownership import desired_priorities, torrent_in_use

logger = logging.getLogger(__name__)

TAG_PREFIX = "romgi-task-"

# How long apply_selective_priority waits for a magnet's metadata before
# giving up: 40 attempts at 15s, so 10 minutes. A ROM set never waits at all
# (its .torrent carries the file list, so priorities go on immediately), but
# a magnet's list has to come from the swarm — and a trackerless MiNERVA
# link has to bootstrap DHT and find peers first. The old budget was 20
# attempts at 2s: 40 seconds, which a healthy swarm beats and a thin or
# slow-starting one does not.
METADATA_MAX_RETRIES = 40
METADATA_RETRY_DELAY = 15


def _tag_for(task_id: int) -> str:
    return f"{TAG_PREFIX}{task_id}"


def _local_dir(task_id: int) -> str:
    """Where a torrent's files live as seen by THIS process (Django/Celery's
    mount of the shared torrent_data volume) — see the QBITTORRENT_SAVE_PATH
    setting comment for why this isn't the same string qBittorrent uses."""
    path = os.path.join(django_settings.TORRENT_WORKING_DIR, str(task_id))
    os.makedirs(path, exist_ok=True)
    return path


def _remote_dir(task_id: int) -> str:
    """The same directory as _local_dir, but as a path qBittorrent itself
    (running in its own container) can resolve — always POSIX-style since
    qBittorrent runs in a Linux container regardless of the host OS."""
    return f"{django_settings.QBITTORRENT_SAVE_PATH.rstrip('/')}/{task_id}"


def _other_active_tasks(torrent_hash: str, exclude_task_id: int | None = None) -> bool:
    """MiNERVA bundles thousands of games into a single torrent (one
    infohash shared across every Link that points into it), and qBittorrent
    dedupes torrents by infohash — so two unrelated DownloadTasks can end up
    riding the same qBittorrent torrent, each wanting a different file out
    of it. True if something else still needs it.

    Delegates to apps.torrents.ownership because DownloadTask is no longer
    the only owner of a torrent: a romsets.RomSetDownload can be riding the
    same infohash, and removing the torrent under it would strand it at
    "downloading" with no error."""
    return torrent_in_use(torrent_hash, exclude_task_id=exclude_task_id)


def _release_torrent(torrent_hash: str, exclude_task_id: int | None = None) -> None:
    """Only remove the torrent from qBittorrent once nothing else is still
    downloading from it — see _other_active_tasks."""
    if not _other_active_tasks(torrent_hash, exclude_task_id):
        client.delete(torrent_hash, delete_files=False)


def _fail_torrent(task: DownloadTask, error_text: str) -> None:
    if task.torrent_hash:
        _release_torrent(task.torrent_hash, exclude_task_id=task.id)
        task.torrent_hash = ""
        task.save(update_fields=["torrent_hash", "updated_at"])
    _handle_download_failure(task, error_text)


@shared_task
def add_torrent(task_id: int) -> None:
    task = DownloadTask.objects.get(id=task_id)
    if task.status != "downloading":
        return
    if not task.link_torrent_magnet:
        _fail_torrent(task, "This torrent has no magnet link available")
        return

    # MiNERVA bundles thousands of games into one shared torrent, so another
    # task may already be downloading a different file out of this exact
    # infohash. Adopt it directly by hash rather than re-adding —
    # qBittorrent rejects a duplicate add for an infohash it already has
    # with a 409, which used to fail this task outright.
    infohash = infohash_from_magnet(task.link_torrent_magnet)
    tag = _tag_for(task.id)
    try:
        handle = client.info(infohash) if infohash else None
        if handle is None:
            try:
                # Added paused, and resumed by apply_selective_priority once
                # the file list has been narrowed down. A magnet carries no
                # file list, so a torrent added running selects everything
                # the moment metadata arrives — for the MiNERVA bundle that
                # is 3,847 files and 6.6TB, against the one game the user
                # asked for. Confirmed live: when metadata outlasted the
                # priority pass's retry budget, the whole bundle was left
                # selected and downloading.
                client.add(
                    magnet=task.link_torrent_magnet,
                    tag=tag,
                    save_path=_remote_dir(task.id),
                    is_paused=True,
                )
            except qbittorrentapi.Conflict409Error:
                pass  # lost the race to another task adding the same infohash — adopt it below

            for _ in range(20):  # ~10s at 0.5s apiece — qBittorrent needs a moment to register the add
                handle = client.info(infohash) if infohash else client.find_by_tag(tag)
                if handle is not None:
                    break
                time.sleep(0.5)
    except Exception as exc:
        # An uncaught error here used to just crash this task and leave
        # the DownloadTask stuck at status="downloading" forever — no
        # torrent_hash, no error message, no automatic retry, and no way
        # for the user to manually retry either (the retry endpoint only
        # accepts status="failed"). Confirmed live: a qBittorrent
        # credential mismatch did exactly this. Whatever goes wrong
        # talking to qBittorrent, the task must still end up in a state
        # the user can see and act on.
        logger.exception("add_torrent failed for task %s", task_id)
        _fail_torrent(task, f"Could not add torrent to qBittorrent: {exc}")
        return

    if handle is None:
        _fail_torrent(task, "qBittorrent did not acknowledge the torrent")
        return

    task.torrent_hash = handle.hash
    task.save(update_fields=["torrent_hash", "updated_at"])
    apply_selective_priority.delay(task.id)


@shared_task(bind=True, max_retries=METADATA_MAX_RETRIES, default_retry_delay=METADATA_RETRY_DELAY)
def apply_selective_priority(self, task_id: int) -> None:
    """File priorities can't be set until qBittorrent has the torrent's
    metadata (file list) — retries until torrents_files() returns rows,
    the Web-API-polling equivalent of TorrentServiceImpl's
    METADATA_RECEIVED-triggered replay of pendingPriorities.

    Priorities are set from every owner currently sharing this torrent_hash,
    not just this one — a shared torrent (see _other_active_tasks) means
    another in-flight task, or a ROM set, may already have its own files
    selected here, and overwriting those back to skip would stall them."""
    task = DownloadTask.objects.get(id=task_id)
    if task.status != "downloading" or not task.torrent_hash:
        return

    files = client.files(task.torrent_hash)
    if not files:
        try:
            raise self.retry()
        except self.MaxRetriesExceededError:
            # Running out of retries is not a benign timeout to swallow.
            # add_torrent left the torrent paused so it couldn't transfer
            # before this ran, so giving up quietly strands the task at
            # "downloading" forever — no progress, no error, and not even
            # retryable (the retry endpoint only accepts status="failed").
            # Failing releases the torrent too, which matters because
            # nothing else would ever clean it up.
            logger.warning("No torrent metadata for task %s after %s attempts", task_id, METADATA_MAX_RETRIES)
            _fail_torrent(task, "Timed out waiting for torrent metadata — no peers found for this magnet")
            return

    for file_id, priority in desired_priorities(task.torrent_hash, files).items():
        client.set_file_priority(task.torrent_hash, file_id, priority)

    # Only now is it safe to transfer. Unconditional rather than "only if we
    # were the one who paused it": reaching here means this task is an
    # active owner wanting bytes, and a torrent shared with another owner is
    # only ever stopped once nothing wants it (downloads.api.pause_download).
    # Resuming one already running is a no-op.
    client.resume(task.torrent_hash)


@shared_task
def poll_active_torrents() -> None:
    """Beat, every few seconds — ports TorrentServiceImpl's 1s progress-poll
    loop. Two qBittorrent calls per active hash; pushes progress over
    Channels (peers/seeds are live-only — never persisted, see
    downloads.progress.push_progress) and hands off finished torrents to
    finalize_completed_torrent.

    Progress/size/downloaded are read off this task's own wanted file, not
    the torrent as a whole — MiNERVA's torrents bundle thousands of games
    together, so the torrent-wide totals (info.size/info.downloaded) can be
    orders of magnitude bigger than the one file this task actually wants,
    and info.downloaded is a lifetime counter that never shrinks even after
    file priorities narrow the selection back down."""
    tasks = (
        DownloadTask.objects.filter(status="downloading", link_is_torrent=True)
        .exclude(torrent_hash="")
        .select_related("platform")
    )
    for task in tasks:
        info = client.info(task.torrent_hash)
        if info is None:
            continue

        files = client.files(task.torrent_hash)
        wanted_index = task.link_torrent_file_index
        chosen = next((f for f in files if wanted_index is None or f.index == wanted_index), None)

        if chosen is not None:
            task.progress = chosen.progress
            task.total_bytes = int(chosen.size)
            task.downloaded_bytes = int(chosen.size * chosen.progress)
        else:
            # File listing not resolved yet (still racing apply_selective_priority) —
            # fall back to the torrent-wide figures rather than showing nothing.
            task.progress = info.progress
            task.downloaded_bytes = int(info.downloaded)
            task.total_bytes = int(info.size)
        task.bytes_per_second = int(info.dlspeed)
        task.save(update_fields=["progress", "downloaded_bytes", "total_bytes", "bytes_per_second", "updated_at"])
        push_progress(task, num_seeds=info.num_seeds, num_peers=info.num_leechs)

        if task.progress >= 1.0 or (chosen is None and info.state in FINISHED_STATES):
            finalize_completed_torrent.delay(task.id)


@shared_task
def finalize_completed_torrent(task_id: int) -> None:
    """Ports _finishTorrentTask + TorrentServiceImpl's TORRENT_FINISHED
    handler: copy the selected file out of qBittorrent's save dir into the
    task's own staging dir, then — if nothing else is still downloading
    from this torrent (see _other_active_tasks) — stop it (never seed) and
    remove it from qBittorrent (data on disk is untouched otherwise —
    matches Kotlin's remove() without the delete-files flag). A shared
    MiNERVA torrent with another task still pulling a different file out of
    it is left running untouched."""
    task = DownloadTask.objects.get(id=task_id)
    if task.status != "downloading" or not task.torrent_hash:
        return

    info = client.info(task.torrent_hash)
    files = client.files(task.torrent_hash)
    if info is None or not files:
        _fail_torrent(task, "Torrent finished but qBittorrent has no file listing for it")
        return

    wanted_index = task.link_torrent_file_index
    chosen = next((f for f in files if wanted_index is None or f.index == wanted_index), files[0])
    # Built from _local_dir, not info.save_path — the latter is a path in
    # qBittorrent's own container filesystem, meaningless to this process.
    source_path = os.path.join(_local_dir(task.id), chosen.name)
    if not os.path.exists(source_path):
        _fail_torrent(task, f"Downloaded file missing on disk: {chosen.name}")
        return

    dest_path = os.path.join(task_dir(task.id), os.path.basename(chosen.name))
    # os.replace() requires source and dest on the same filesystem — in
    # Compose, torrent_data and staged_files are separate volumes, so a
    # torrent's finalize always hit EXDEV ("Invalid cross-device link").
    # shutil.move() falls back to copy+delete across filesystems.
    shutil.move(source_path, dest_path)

    # Leave a torrent another task still wants running untouched.
    if not _other_active_tasks(task.torrent_hash, exclude_task_id=task.id):
        client.stop(task.torrent_hash)  # never seed — mirrors handle.pause() on TORRENT_FINISHED
        client.delete(task.torrent_hash, delete_files=False)
    task.torrent_hash = ""
    task.save(update_fields=["torrent_hash", "updated_at"])

    _finish_download(task, dest_path)


@shared_task
def cancel_torrent(torrent_hash: str) -> None:
    """Called from downloads.api.cancel_download when the task being
    cancelled is an in-flight torrent, so qBittorrent doesn't keep seeding
    or occupying a slot for a task the user deleted. Takes the hash
    directly rather than a task_id — by the time this runs, the
    DownloadTask row is already gone. Only actually removes it from
    qBittorrent if no other task is still downloading a different file out
    of the same shared torrent (see _other_active_tasks)."""
    if torrent_hash:
        _release_torrent(torrent_hash)
