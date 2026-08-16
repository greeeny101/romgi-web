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
import time

from celery import shared_task
from django.conf import settings as django_settings

from apps.downloads.models import DownloadTask
from apps.downloads.progress import push_progress, push_status
from apps.downloads.tasks import _finish_download, _handle_download_failure, task_dir

from .client import FINISHED_STATES, PRIORITY_DOWNLOAD, PRIORITY_SKIP, client

logger = logging.getLogger(__name__)

TAG_PREFIX = "romgi-task-"


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


def _fail_torrent(task: DownloadTask, error_text: str) -> None:
    if task.torrent_hash:
        client.delete(task.torrent_hash, delete_files=False)
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

    tag = _tag_for(task.id)
    client.add(magnet=task.link_torrent_magnet, tag=tag, save_path=_remote_dir(task.id))

    handle = None
    for _ in range(20):  # ~10s at 0.5s apiece — qBittorrent needs a moment to register the add
        handle = client.find_by_tag(tag)
        if handle is not None:
            break
        time.sleep(0.5)
    if handle is None:
        _fail_torrent(task, "qBittorrent did not acknowledge the torrent")
        return

    task.torrent_hash = handle.hash
    task.save(update_fields=["torrent_hash", "updated_at"])
    apply_selective_priority.delay(task.id)


@shared_task(bind=True, max_retries=20, default_retry_delay=2)
def apply_selective_priority(self, task_id: int) -> None:
    """File priorities can't be set until qBittorrent has the torrent's
    metadata (file list) — retries until torrents_files() returns rows,
    the Web-API-polling equivalent of TorrentServiceImpl's
    METADATA_RECEIVED-triggered replay of pendingPriorities."""
    task = DownloadTask.objects.get(id=task_id)
    if task.status != "downloading" or not task.torrent_hash:
        return

    files = client.files(task.torrent_hash)
    if not files:
        raise self.retry()

    wanted_index = task.link_torrent_file_index
    for f in files:
        priority = PRIORITY_DOWNLOAD if (wanted_index is None or f.index == wanted_index) else PRIORITY_SKIP
        client.set_file_priority(task.torrent_hash, f.id, priority)


@shared_task
def poll_active_torrents() -> None:
    """Beat, every few seconds — ports TorrentServiceImpl's 1s progress-poll
    loop. One qBittorrent call per active hash; pushes progress over
    Channels (peers/seeds are live-only — never persisted, see
    downloads.progress.push_progress) and hands off finished torrents to
    finalize_completed_torrent."""
    tasks = DownloadTask.objects.filter(status="downloading", link_is_torrent=True).exclude(torrent_hash="")
    for task in tasks:
        info = client.info(task.torrent_hash)
        if info is None:
            continue

        task.progress = info.progress
        task.downloaded_bytes = int(info.downloaded)
        task.total_bytes = int(info.size)
        task.bytes_per_second = int(info.dlspeed)
        task.save(update_fields=["progress", "downloaded_bytes", "total_bytes", "bytes_per_second", "updated_at"])
        push_progress(task, num_seeds=info.num_seeds, num_peers=info.num_leechs)

        if info.progress >= 1.0 or info.state in FINISHED_STATES:
            finalize_completed_torrent.delay(task.id)


@shared_task
def finalize_completed_torrent(task_id: int) -> None:
    """Ports _finishTorrentTask + TorrentServiceImpl's TORRENT_FINISHED
    handler: stop the torrent immediately (never seed), copy the selected
    file out of qBittorrent's save dir into the task's own staging dir,
    then remove the torrent from qBittorrent (data on disk is untouched
    otherwise — matches Kotlin's remove() without the delete-files flag)."""
    task = DownloadTask.objects.get(id=task_id)
    if task.status != "downloading" or not task.torrent_hash:
        return

    client.stop(task.torrent_hash)  # never seed — mirrors handle.pause() on TORRENT_FINISHED

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
    os.replace(source_path, dest_path)

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
    DownloadTask row is already gone."""
    if torrent_hash:
        client.delete(torrent_hash, delete_files=False)
