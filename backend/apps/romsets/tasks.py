"""
Celery tasks driving a whole-item ("ROM set") download through qBittorrent.

Shape differs from apps.torrents.tasks in three ways that matter:

* Added from raw `.torrent` bytes, not a magnet — archive.org publishes a
  torrent per item and no magnet at all. The torrent arrives with its full
  file list, so there is no METADATA_RECEIVED race to poll around; but
  file priorities cannot be passed alongside an uploaded torrent, so the
  sequence is add-paused → set priorities → resume.
* Files are matched to qBittorrent by name, never by index. Three
  disagreeing file lists exist per item (metadata API, raw torrent,
  qBittorrent's pad-filtered view) and a positional mapping between any two
  of them is wrong.
* Nothing is moved on completion. The torrent's save path is the library
  folder itself, so the finished set is already where it belongs — which
  also means there is no multi-gigabyte copy between volumes at the end.
"""

from __future__ import annotations

import logging
import os
import time
import zipfile

import qbittorrentapi
from celery import shared_task
from django.conf import settings as django_settings
from django.utils import timezone

from apps.downloads.extraction import extract_archive
from apps.torrents.client import ERROR_STATES, client
from apps.torrents.ownership import desired_priorities, torrent_in_use

from . import archive_org
from .bencode import infohash_from_torrent
from .models import RomSetDownload, RomSetFile
from .progress import push_progress, push_status
from .space import InsufficientSpace, check_space, ensure_space, human_bytes

logger = logging.getLogger(__name__)

TAG = "romgi-romset"

# Archives we can actually open. extraction.extract_archive dispatches
# anything that isn't .zip to py7zr, so an unguarded .rar reaches it as a
# raw library error rather than a message anyone can act on.
EXTRACTABLE_EXTENSIONS = (".zip", ".7z")


def platform_dir(romset: RomSetDownload) -> str:
    """A set with no single platform still has to land somewhere."""
    return romset.platform_id or "_unsorted"


def remote_save_path(romset: RomSetDownload) -> str:
    """Where qBittorrent should save, in ITS OWN filesystem's terms.

    Deliberately stops at the platform directory: with
    content_layout="Original" the torrent contributes its own root folder
    (the archive.org identifier), so appending the identifier here as well
    would nest it twice.
    """
    base = django_settings.QBITTORRENT_LIBRARY_PATH.rstrip("/")
    return f"{base}/{platform_dir(romset)}"


def ensure_platform_dir(romset: RomSetDownload) -> None:
    """Create the platform directory that qBittorrent will save into, world-
    writable, before handing it the torrent.

    The daemon runs as uid 1000 (PUID in docker-compose) while Django and
    Celery run as root, and the library volume's root is root-owned 0755 —
    so left to itself qBittorrent cannot create anything under it and puts
    the torrent straight into `error` state with no usable message.
    Confirmed live: the first real transfer failed exactly this way.

    Explicit chmod rather than trusting makedirs(mode=...), whose mode is
    masked by the process umask.
    """
    path = os.path.join(django_settings.ROM_LIBRARY_DIR, platform_dir(romset))
    os.makedirs(path, exist_ok=True)
    try:
        os.chmod(path, 0o777)
    except OSError:
        logger.warning("Could not widen permissions on %s", path, exc_info=True)


def local_set_dir(romset: RomSetDownload) -> str:
    """The same directory as remote_save_path's result, as THIS process sees
    it — see the ROM_LIBRARY_DIR setting comment on why the two strings
    differ and must never be conflated."""
    return os.path.join(django_settings.ROM_LIBRARY_DIR, romset.save_dir)


def _fail(romset: RomSetDownload, message: str) -> None:
    logger.warning("ROM set %s failed: %s", romset.id, message)
    if romset.infohash and not torrent_in_use(romset.infohash, exclude_romset_id=romset.id):
        try:
            client.stop(romset.infohash)
            client.delete(romset.infohash, delete_files=False)
        except Exception:
            logger.warning("Could not release torrent %s", romset.infohash, exc_info=True)
    romset.status = "failed"
    romset.error = message
    romset.bytes_per_second = 0
    romset.save(update_fields=["status", "error", "bytes_per_second", "updated_at"])
    push_status(romset)


def _wanted_total(romset: RomSetDownload) -> int:
    return sum(romset.files.filter(wanted=True).values_list("size", flat=True))


def _outstanding_total(romset: RomSetDownload) -> int:
    """Bytes still to fetch. Files carried over from a previous run of the
    same set are already on disk, so charging the space check for them
    again would refuse a re-request that needs no new room at all."""
    return sum(romset.files.filter(wanted=True, done=False).values_list("size", flat=True))


@shared_task
def start_romset_download(romset_id: int) -> None:
    romset = RomSetDownload.objects.filter(id=romset_id).first()
    if romset is None or romset.status != "pending":
        return

    romset.status = "fetching_metadata"
    romset.save(update_fields=["status", "updated_at"])
    push_progress(romset)

    try:
        # The API already checked, but that check went stale the moment
        # another set queued behind this one.
        ensure_space(_outstanding_total(romset), exclude_romset_id=romset.id)
    except InsufficientSpace as exc:
        _fail(romset, str(exc))
        return

    try:
        data = archive_org.torrent_bytes(romset.identifier, romset.user)
    except archive_org.ArchiveOrgError as exc:
        _fail(romset, str(exc))
        return

    # Normally already known: archive.org publishes each item's infohash as
    # `btih` in its metadata, so the API records it at enqueue time and we
    # never have to compute it. This is the fallback for an item that
    # doesn't carry one.
    infohash = romset.infohash
    if not infohash:
        try:
            infohash = infohash_from_torrent(data)
        except Exception as exc:
            _fail(romset, f"Could not read the torrent for {romset.identifier}: {exc}")
            return

    try:
        handle = client.info(infohash)
        if handle is None:
            ensure_platform_dir(romset)
            try:
                client.add_torrent_file(
                    data=data,
                    tag=TAG,
                    save_path=remote_save_path(romset),
                    # Priorities can't be sent with an uploaded torrent, so
                    # it must not start transferring before we've had the
                    # chance to deselect files — otherwise qBittorrent
                    # begins pulling the largest file in the set immediately.
                    is_paused=True,
                )
            except qbittorrentapi.Conflict409Error:
                pass  # someone else added the same infohash first — adopt it below

            for _ in range(20):  # ~10s; qBittorrent needs a moment to register the add
                handle = client.info(infohash)
                if handle is not None:
                    break
                time.sleep(0.5)
    except Exception as exc:
        logger.exception("start_romset_download failed for %s", romset_id)
        _fail(romset, f"Could not add the torrent to qBittorrent: {exc}")
        return

    if handle is None:
        _fail(romset, "qBittorrent did not acknowledge the torrent")
        return

    romset.infohash = handle.hash
    romset.save(update_fields=["infohash", "updated_at"])

    try:
        files = client.files(handle.hash)
        if not files:
            _fail(romset, "qBittorrent has no file listing for this torrent")
            return
        for file_id, priority in desired_priorities(handle.hash, files).items():
            client.set_file_priority(handle.hash, file_id, priority)
        client.resume(handle.hash)
    except Exception as exc:
        logger.exception("Could not select files for ROM set %s", romset_id)
        _fail(romset, f"Could not select files in qBittorrent: {exc}")
        return

    romset.status = "downloading"
    romset.total_bytes = _wanted_total(romset)
    romset.save(update_fields=["status", "total_bytes", "updated_at"])
    push_progress(romset)


@shared_task
def poll_active_romsets() -> None:
    """Beat — aggregate progress for every downloading set.

    One tagged listing per tick covers every set at once; the per-file
    listing is only fetched for sets whose aggregate progress actually
    moved, so a stalled or seeding-blocked set costs a single call.
    """
    active = list(RomSetDownload.objects.filter(status="downloading").exclude(infohash=""))
    if not active:
        return

    try:
        handles = {h.hash: h for h in client.list_by_tag(TAG)}
    except Exception:
        logger.warning("Could not list ROM set torrents", exc_info=True)
        return

    free = None
    for romset in active:
        # An adopted torrent (added by something else first) won't carry our
        # tag, so fall back to a direct lookup rather than declaring it lost.
        handle = handles.get(romset.infohash)
        if handle is None:
            try:
                handle = client.info(romset.infohash)
            except Exception:
                logger.warning("Could not read torrent %s", romset.infohash, exc_info=True)
                continue
        if handle is None:
            _fail(romset, "The torrent is no longer present in qBittorrent")
            continue

        if handle.state in ERROR_STATES:
            _fail(romset, f"qBittorrent reported the torrent as '{handle.state}'")
            continue

        # Something outside this app can eat the volume while a set is in
        # flight. Stop before qBittorrent hits ENOSPC and errors the torrent
        # with partial files nobody can interpret.
        if free is None:
            free = check_space(0).free
        if free < django_settings.ROM_LIBRARY_MIN_FREE_BYTES:
            try:
                client.stop(romset.infohash)
            except Exception:
                logger.warning("Could not stop torrent %s", romset.infohash, exc_info=True)
            _fail(
                romset,
                f"Stopped: only {human_bytes(free)} left on the ROM library volume, "
                f"below the {human_bytes(django_settings.ROM_LIBRARY_MIN_FREE_BYTES)} reserve.",
            )
            continue

        total = int(handle.size) or romset.total_bytes
        completed = int(handle.completed)
        progress = float(handle.progress)
        moved = abs(progress - romset.progress) > 1e-9

        romset.progress = progress
        romset.downloaded_bytes = completed
        romset.total_bytes = total
        romset.bytes_per_second = int(handle.dlspeed)
        romset.save(update_fields=["progress", "downloaded_bytes", "total_bytes", "bytes_per_second", "updated_at"])

        if moved:
            _update_file_progress(romset)

        push_progress(romset, num_seeds=handle.num_seeds, num_peers=handle.num_leechs)

        if progress >= 1.0:
            finalize_romset.delay(romset.id)


def _update_file_progress(romset: RomSetDownload) -> None:
    """Per-file progress, matched by name against qBittorrent's listing."""
    try:
        files = client.files(romset.infohash)
    except Exception:
        logger.warning("Could not read file listing for %s", romset.infohash, exc_info=True)
        return

    by_name = {f.name: f for f in files}
    rows = list(romset.files.filter(wanted=True))
    for row in rows:
        match = by_name.get(f"{romset.identifier}/{row.path}") or by_name.get(row.path)
        if match is None:
            continue
        row.progress = float(match.progress)
        row.done = row.progress >= 1.0
    RomSetFile.objects.bulk_update(rows, ["progress", "done"])


@shared_task
def finalize_romset(romset_id: int) -> None:
    """Verify what landed, release the torrent, then extract if asked.

    Verification is size-and-existence only: BitTorrent has already checked
    every piece against the torrent's hashes, so re-hashing gigabytes here
    would buy nothing.
    """
    romset = RomSetDownload.objects.filter(id=romset_id).first()
    if romset is None or romset.status != "downloading":
        return

    directory = local_set_dir(romset)
    missing: list[str] = []
    for row in romset.files.filter(wanted=True):
        path = os.path.join(directory, row.path)
        try:
            if os.path.getsize(path) != row.size:
                missing.append(f"{row.path} (wrong size)")
        except OSError:
            missing.append(row.path)

    if missing:
        preview = ", ".join(missing[:3])
        suffix = f" and {len(missing) - 3} more" if len(missing) > 3 else ""
        _fail(romset, f"Finished, but these files are missing on disk: {preview}{suffix}")
        return

    # Never seed. Data on disk is untouched — delete_files stays False.
    if not torrent_in_use(romset.infohash, exclude_romset_id=romset.id):
        try:
            client.stop(romset.infohash)
            client.delete(romset.infohash, delete_files=False)
        except Exception:
            logger.warning("Could not release torrent %s", romset.infohash, exc_info=True)
    romset.infohash = ""
    romset.bytes_per_second = 0
    romset.save(update_fields=["infohash", "bytes_per_second", "updated_at"])

    if romset.extract and _extractable(romset):
        romset.status = "extracting"
        romset.save(update_fields=["status", "updated_at"])
        push_progress(romset)
        extract_romset.delay(romset.id)
        return

    _complete(romset)


def _extractable(romset: RomSetDownload) -> bool:
    return any(row.path.lower().endswith(EXTRACTABLE_EXTENSIONS) for row in romset.files.filter(wanted=True))


def _complete(romset: RomSetDownload) -> None:
    romset.status = "completed"
    romset.progress = 1.0
    romset.bytes_per_second = 0
    romset.completed_at = timezone.now()
    romset.save(update_fields=["status", "progress", "bytes_per_second", "completed_at", "updated_at"])
    push_status(romset)


def _uncompressed_size(path: str) -> int:
    """What the archive will occupy once expanded, read from its index
    rather than guessed — extract_archive does not remove the source, so the
    volume has to hold both at once."""
    if path.lower().endswith(".zip"):
        with zipfile.ZipFile(path) as zf:
            return sum(info.file_size for info in zf.infolist() if not info.is_dir())
    import py7zr

    with py7zr.SevenZipFile(path, mode="r") as archive:
        return sum(f.uncompressed for f in archive.list() if not f.is_directory)


@shared_task
def extract_romset(romset_id: int) -> None:
    romset = RomSetDownload.objects.filter(id=romset_id).first()
    if romset is None or romset.status != "extracting":
        return

    directory = local_set_dir(romset)
    archives = [
        os.path.join(directory, row.path)
        for row in romset.files.filter(wanted=True)
        if row.path.lower().endswith(EXTRACTABLE_EXTENSIONS)
    ]

    for archive_path in archives:
        if not os.path.exists(archive_path):
            continue
        try:
            needed = _uncompressed_size(archive_path)
        except Exception as exc:
            _fail(romset, f"Could not read {os.path.basename(archive_path)}: {exc}")
            return

        try:
            ensure_space(needed, exclude_romset_id=romset.id)
        except InsufficientSpace as exc:
            _fail(romset, f"Downloaded, but extraction needs more room. {exc}")
            return

        target = os.path.dirname(archive_path)
        try:
            # The return value (the largest single extracted file) is
            # meaningless for a set — the whole tree is the deliverable.
            extract_archive(archive_path, target, on_progress=None)
        # Deliberately broad (ExtractionError included): py7zr raises its own
        # hierarchy, and anything escaping here would strand the row at
        # "extracting" with no error and no way for the user to retry.
        except Exception as exc:
            _fail(romset, f"Could not extract {os.path.basename(archive_path)}: {exc}")
            return

        os.remove(archive_path)

    _complete(romset)


@shared_task
def cancel_romset_torrent(infohash: str) -> None:
    """Called after the row is already gone, so it takes the hash directly —
    mirrors torrents.tasks.cancel_torrent."""
    if infohash and not torrent_in_use(infohash):
        try:
            client.stop(infohash)
            client.delete(infohash, delete_files=False)
        except Exception:
            logger.warning("Could not cancel torrent %s", infohash, exc_info=True)
