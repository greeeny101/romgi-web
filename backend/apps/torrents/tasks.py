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
from apps.downloads.tasks import _finish_download, _handle_download_failure, live_task, task_dir

from .client import ERROR_STATES, FINISHED_STATES, STOPPED_STATES, client
from .ownership import desired_priorities, torrent_in_use

logger = logging.getLogger(__name__)

TAG_PREFIX = "romgi-task-"

# How long apply_selective_priority waits for a magnet's metadata before
# giving up: 24 attempts at 5s, so 2 minutes. A ROM set never waits at all
# (its .torrent carries the file list, so priorities go on immediately), but
# a magnet's list has to come from the swarm, and a trackerless MiNERVA link
# has to bootstrap DHT first.
#
# This was 40 attempts at 15s — 10 minutes — which was compensating for a
# bug rather than for a slow swarm: the torrent was being added stopped, so
# metadata could never arrive and the only effect of a longer budget was a
# longer wait before the inevitable failure (see TorrentClient.add). With
# the torrent actually in the swarm, the 15.7GB/1,193-file MiNERVA N64
# bundle returned its file list in under 5 seconds. 2 minutes is roughly
# twenty times that, so it still absorbs a thin or slow-starting swarm while
# failing fast enough to be worth reading an error about.
#
# The 5s delay also shortens every successful start: the first check runs
# immediately after the add and normally misses, so this interval is dead
# time on the happy path for every torrent download.
METADATA_MAX_RETRIES = 24
METADATA_RETRY_DELAY = 5

# How long finalize waits for a stopped torrent to actually report stopped
# before reading its file — see _await_stopped. Normally well under a second;
# the ceiling only matters if the daemon is wedged.
STOP_FLUSH_TIMEOUT = 15.0
STOP_FLUSH_POLL = 0.5


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


def _local_from_remote(remote_path: str) -> str | None:
    """Translate a save path qBittorrent reported back into this process's
    view of the same directory, or None if it sits outside our mount.

    The inverse of _remote_dir, and necessary because a task does not always
    own the directory its own file lands in. qBittorrent dedupes by infohash,
    so when a second task wants a different file out of an already-present
    MiNERVA bundle, add_torrent adopts the existing torrent rather than
    re-adding it — and the torrent keeps the save path of whichever task
    added it first. Assuming _local_dir(task.id) instead made every adopting
    task report "Downloaded file missing on disk" after transferring
    perfectly: the bytes were all there, one directory over.
    """
    base = django_settings.QBITTORRENT_SAVE_PATH.rstrip("/")
    remote = (remote_path or "").rstrip("/")
    if not remote:
        return None
    if remote == base:
        return django_settings.TORRENT_WORKING_DIR
    if not remote.startswith(base + "/"):
        return None
    return os.path.join(django_settings.TORRENT_WORKING_DIR, *remote[len(base) + 1 :].split("/"))


def _find_downloaded_file(task: DownloadTask, info, name: str) -> str | None:
    """Absolute path of this task's finished file, or None if it isn't there.

    Tries the torrent's actual save path first and this task's own directory
    second. The fallback matters for torrents added before save-path
    translation existed, and costs nothing when the first candidate hits.
    """
    candidates = [_local_from_remote(getattr(info, "save_path", "")), _local_dir(task.id)]
    for directory in candidates:
        if not directory:
            continue
        candidate = os.path.join(directory, *name.split("/"))
        if os.path.exists(candidate):
            return candidate
    return None


def _sweep_torrent_dir(info) -> None:
    """Remove a released torrent's save directory once nothing rides it.

    Only the leftovers of files earlier owners copied rather than moved (see
    finalize_completed_torrent) — everything anyone wanted is already in its
    own staging directory by now. Guarded to paths under TORRENT_WORKING_DIR
    so a misreported save path can never point this at the library.
    """
    directory = _local_from_remote(getattr(info, "save_path", ""))
    if not directory:
        return
    root = os.path.abspath(django_settings.TORRENT_WORKING_DIR)
    target = os.path.abspath(directory)
    if target == root or not target.startswith(root + os.sep):
        return
    shutil.rmtree(target, ignore_errors=True)


def _await_stopped(torrent_hash: str, timeout: float = STOP_FLUSH_TIMEOUT) -> bool:
    """Block until qBittorrent confirms the torrent is stopped.

    stop() only asks. Returning as soon as the request is accepted would put
    the read back inside the window it was moved out of, so this waits for
    the daemon's own state to say the files have been let go. Normally under
    a second.

    Falls through with a warning rather than failing on timeout: a copy that
    might be stale is still better than abandoning a download that has
    finished transferring, and extraction remains the backstop.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        info = client.info(torrent_hash)
        if info is None or info.state in STOPPED_STATES:
            return True
        time.sleep(STOP_FLUSH_POLL)
    logger.warning("Torrent %s did not report stopped within %.0fs; reading it anyway", torrent_hash, timeout)
    return False


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
    task = live_task(task_id)
    if task is None or task.status != "downloading":
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
                # Runs only until the file list arrives, then stops itself;
                # apply_selective_priority narrows the selection and resumes.
                # A magnet carries no file list, so a torrent added running
                # selects everything the moment metadata arrives — for the
                # MiNERVA bundle that is 3,847 files and 6.6TB, against the
                # one game the user asked for.
                #
                # Adding it *paused* was the first attempt at that guard and
                # is a deadlock: a stopped torrent joins no swarm on
                # qBittorrent 5.x, so metadata never arrives, and the wait
                # below times out reporting "no peers" while DHT is perfectly
                # healthy. See TorrentClient.add.
                client.add(
                    magnet=task.link_torrent_magnet,
                    tag=tag,
                    save_path=_remote_dir(task.id),
                    stop_at_metadata=True,
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
    task = live_task(task_id)
    if task is None or task.status != "downloading" or not task.torrent_hash:
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
            # Deliberately does not name a cause. The old wording ("no peers
            # found for this magnet") asserted one, and when the real fault
            # was on our side — the torrent added stopped, so it was never in
            # the swarm to find peers in — it sent the investigation looking
            # at DHT and port forwarding while qBittorrent sat there with 110
            # healthy DHT nodes. Say what was observed, and where to look.
            waited = METADATA_MAX_RETRIES * METADATA_RETRY_DELAY // 60
            _fail_torrent(
                task,
                f"No file list for this torrent after {waited} minutes. Its swarm may have no active "
                "seeders, or qBittorrent may not be reaching the network — check whether it is "
                "connected and has DHT nodes in its Web UI.",
            )
            return

    for file_id, priority in desired_priorities(task.torrent_hash, files).items():
        client.set_file_priority(task.torrent_hash, file_id, priority)

    # Only now is it safe to transfer. Unconditional rather than "only if we
    # were the one who paused it": reaching here means this task is an
    # active owner wanting bytes, and a torrent shared with another owner is
    # only ever stopped once nothing wants it (downloads.api.pause_download).
    # Resuming one already running is a no-op.
    client.resume(task.torrent_hash)


def _reported_progress(info, chosen) -> float:
    """How much of the wanted file to show the user, on a scale that moves.

    qBittorrent reports per-file progress with piece granularity: a piece
    that is half downloaded counts for nothing, so the number only advances
    when a whole piece lands. MiNERVA's bundles use 8MiB pieces, and because
    libtorrent fetches pieces rarest-first rather than front-to-back, none
    of them lands early. Measured on a 65MB N64 ROM: the file sat at exactly
    0.0000 for 47 seconds while 48MB of it transferred, then went 0 -> 0.13
    -> 0.26 -> 0.51 -> 0.77 -> 1.0. A ROM smaller than a single piece — most
    of an N64 or Mega Drive library — can only ever report 0.0 or 1.0. What
    the user sees is a download frozen at zero that abruptly completes.

    info.completed measures the same transfer without the rounding, over the
    whole *selected* region rather than one file. Across the identical
    transfer it advanced on every single sample, 819KB through to the full
    48MiB. That is the number worth showing.

    Its limitation is real and worth stating: it describes the selection,
    not this one file. Queueing three ROMs out of one bundle selects three
    files that share a 48MiB piece region, and the bytes arriving belong to
    whichever of them a piece happens to cover — so what is honestly known
    is how far that shared region has come, which is what every row then
    reports. The file's own figure is used as a floor wherever it is ahead,
    so a piece this file has actually verified is never given back.

    It runs optimistic at the end: pieces verify a few seconds after the
    region completes, so a row can sit near 100% briefly. That is why the
    estimate is capped below 1.0 — progress == 1.0 is what marks the task
    finished, and only the file's own verified progress may set it.
    """
    if chosen.progress >= 1.0:
        return 1.0
    if info.size <= 0:
        return chosen.progress
    return max(chosen.progress, min(info.completed / info.size, 0.999))


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

        # Neither of these is in FINISHED_STATES, so without this branch the
        # task sits at "downloading" forever with no error and no progress —
        # the trap ERROR_STATES was defined to catch, and which only
        # romsets.tasks.poll_active_romsets was actually checking for.
        if info.state in ERROR_STATES:
            _fail_torrent(
                task,
                "qBittorrent stopped this torrent: "
                + (
                    "its files went missing from disk"
                    if info.state == "missingFiles"
                    else "it reported an error (often a full disk)"
                )
                + ". Check the torrent in the qBittorrent Web UI.",
            )
            continue

        files = client.files(task.torrent_hash)
        wanted_index = task.link_torrent_file_index
        chosen = next((f for f in files if wanted_index is None or f.index == wanted_index), None)

        if chosen is not None:
            task.progress = _reported_progress(info, chosen)
            task.total_bytes = int(chosen.size)
            task.downloaded_bytes = int(chosen.size * task.progress)
        else:
            # File listing not resolved yet (still racing apply_selective_priority).
            #
            # Deliberately NOT info.size/info.downloaded here. Those describe
            # the whole torrent, and a MiNERVA bundle is thousands of games:
            # the PlayStation one reported 18,037,303,316,474 bytes, so a
            # 189MB download announced itself as 18TB until the file list
            # resolved. The catalog's own estimate is wrong by a rounding
            # error; the torrent-wide figure is wrong by five orders of
            # magnitude, and it is what the user reads while waiting.
            task.progress = 0.0
            task.downloaded_bytes = 0
            task.total_bytes = int(task.link_size or 0)
        task.bytes_per_second = int(info.dlspeed)
        task.save(update_fields=["progress", "downloaded_bytes", "total_bytes", "bytes_per_second", "updated_at"])
        push_progress(task, num_seeds=info.num_seeds, num_peers=info.num_leechs)

        # Deliberately the file's own piece-granular progress rather than
        # task.progress, which _reported_progress may be interpolating: that
        # estimate runs a second or two ahead of the pieces actually being
        # verified, and finishing on it would copy the file out from under a
        # write still in flight.
        if (chosen is not None and chosen.progress >= 1.0) or (chosen is None and info.state in FINISHED_STATES):
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
    task = live_task(task_id)
    if task is None or task.status != "downloading" or not task.torrent_hash:
        return

    info = client.info(task.torrent_hash)
    files = client.files(task.torrent_hash)
    if info is None or not files:
        _fail_torrent(task, "Torrent finished but qBittorrent has no file listing for it")
        return

    wanted_index = task.link_torrent_file_index
    chosen = next((f for f in files if wanted_index is None or f.index == wanted_index), files[0])
    source_path = _find_downloaded_file(task, info, chosen.name)
    if source_path is None:
        _fail_torrent(task, f"Downloaded file missing on disk: {chosen.name}")
        return

    dest_path = os.path.join(task_dir(task.id), os.path.basename(chosen.name))
    # Whether anything else is still riding this infohash decides both how the
    # file leaves the torrent's directory and whether the torrent survives.
    shared = _other_active_tasks(task.torrent_hash, exclude_task_id=task.id)

    # Stop BEFORE reading the file, not after, and in every case.
    #
    # libtorrent calls a piece complete once it has hash-verified it in
    # memory; the 16KiB blocks behind it are written out asynchronously.
    # This project's torrent directory is an SMB share
    # (TORRENT_DATA_HOST_PATH) that qBittorrent writes to from inside Docker
    # and this worker reads back through a different client, which widens
    # that window considerably.
    #
    # Reading inside it produced a file of exactly the right length with a
    # valid PK zip header, no truncation, and individual 16KiB holes of
    # zeros punched through the middle — 2 blocks missing on task 135, 12 on
    # task 180 — which surfaces as "invalid block type" partway through
    # inflate and nowhere earlier. Retrying the download always fixed it,
    # because by then the blocks had landed.
    #
    # Stopping flushes those writes and lets go of the file, and
    # _await_stopped waits for the daemon to confirm rather than assuming.
    # A shared torrent is stopped too and resumed below: its siblings lose a
    # second or two, which is worth not handing them the same holes.
    client.stop(task.torrent_hash)  # never seed — mirrors handle.pause() on TORRENT_FINISHED
    _await_stopped(task.torrent_hash)

    try:
        # os.replace() requires source and dest on the same filesystem — in
        # Compose, torrent_data and staged_files are separate volumes, so a
        # torrent's finalize always hit EXDEV ("Invalid cross-device link").
        # shutil.move() falls back to copy+delete across filesystems.
        if shared:
            # Copy, don't move: the torrent is still registered and still
            # wanted by another task pulling a different file out of the same
            # MiNERVA bundle. Taking a file out from under a live torrent is
            # how it lands in qBittorrent's "missingFiles" state, and every
            # task riding the infohash would then sit at "downloading" with
            # no error. The leftover is cleaned up by whichever owner
            # finishes last, below.
            shutil.copy2(source_path, dest_path)
        else:
            shutil.move(source_path, dest_path)
    finally:
        # In a finally block because leaving a shared torrent stopped would
        # stall every sibling riding it with no error and nothing to resume
        # them — a worse outcome than whatever went wrong with the copy.
        if shared:
            client.resume(task.torrent_hash)

    if not shared:
        client.delete(task.torrent_hash, delete_files=False)
        # Last owner out sweeps the copies its predecessors left behind.
        # Safe only here: nothing else is riding the infohash, so no other
        # task or ROM set is still reading from this directory.
        _sweep_torrent_dir(info)
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
