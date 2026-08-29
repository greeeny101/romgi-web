"""
Ninja endpoints for the ROM-set browser.

Search and item detail are thin proxies onto archive.org (cached), so the
browser never talks to archive.org directly and one user's search warms the
cache for everyone. `POST /romsets/downloads` is where the real work
happens: it resolves the item's torrent, records the file selection, checks
there is room for it, and hands off to Celery.
"""

from __future__ import annotations

from django.db import transaction
from django.shortcuts import get_object_or_404
from ninja import Router
from ninja.errors import HttpError
from ninja_jwt.authentication import JWTAuth

from apps.catalog.models import Platform
from apps.common import archive_org

from .bencode import BencodeError, torrent_files
from .emulators import build_query, get_emulator, load_emulators
from .models import RomSetDownload, RomSetFile
from .progress import serialize
from .schemas import (
    EmulatorOut,
    EnqueueRomSetIn,
    ItemDetailOut,
    LibrarySpaceOut,
    RomSetDownloadDetailOut,
    RomSetDownloadOut,
    SearchOut,
)
from .space import check_space
from .tasks import cancel_romset_torrent, start_romset_download

router = Router(tags=["romsets"], auth=JWTAuth())

PAGE_SIZE = 25

# Above this many files the item detail response stops shipping the whole
# list and the client selects by folder instead. A MAME reference set is
# ~4,800 files: 760KB of JSON, 4,800 checkboxes, and a browser layout pass
# nobody wants — and the useful choice there was never per-file anyway, it
# was "roms/ yes, samples/ no".
FILE_LIST_LIMIT = 750


def _detail(romset: RomSetDownload) -> dict:
    payload = serialize(romset)
    rows = list(romset.files.all()[: FILE_LIST_LIMIT + 1])
    payload["files_truncated"] = len(rows) > FILE_LIST_LIMIT
    payload["files"] = [
        {"path": f.path, "size": f.size, "wanted": f.wanted, "progress": f.progress, "done": f.done}
        for f in rows[:FILE_LIST_LIMIT]
    ]
    return payload


def _item_files(identifier: str, user) -> tuple[str, list[dict], int]:
    """`(torrent_root, files, total_size)` for an item.

    The list comes from the torrent, NOT from the metadata API. The two
    genuinely differ — the metadata API carries `_files.xml`, `_reviews.xml`
    and the torrent itself, none of which are inside the torrent — and only
    what is in the torrent can actually be downloaded. Metadata is used to
    enrich each entry with its checksums and format, matched by name.
    """
    try:
        data = archive_org.torrent_bytes(identifier, user)
        root, entries = torrent_files(data)
    except archive_org.ArchiveOrgAuthRequired as exc:
        raise HttpError(403, str(exc)) from exc
    except archive_org.ArchiveOrgError as exc:
        raise HttpError(502, str(exc)) from exc
    except BencodeError as exc:
        raise HttpError(502, f"archive.org returned a torrent we could not read: {exc}") from exc

    # Checksum/format enrichment is display-only, and on a 4,800-file item
    # the metadata payload it comes from is 1.6MB. Skip it once the file
    # list is too long to render individually anyway.
    details = archive_org.file_details(archive_org.item(identifier)) if len(entries) <= FILE_LIST_LIMIT else {}
    files = [
        {
            "path": entry.path,
            "size": entry.size,
            "format": (details.get(entry.path) or {}).get("format"),
            "md5": (details.get(entry.path) or {}).get("md5"),
            "sha1": (details.get(entry.path) or {}).get("sha1"),
        }
        for entry in entries
    ]
    return root, files, sum(entry.size for entry in entries)


def folder_of(path: str) -> str:
    """Top-level directory a torrent path sits in; "" for the root."""
    return path.split("/")[0] if "/" in path else ""


def carried_forward_paths(existing, available_paths: set[str]) -> set[str]:
    """Files a previous run of this set already fetched, which must stay
    selected however the new request narrows things.

    Deselecting a file is not a no-op: qBittorrent is told "do not
    download" for it, and when the torrent's data is already on disk it
    deletes that data. Confirmed the hard way — re-requesting a MAME set
    with only `roms/` ticked wiped the `samples/` folder an earlier run had
    fetched, and the same sequence reversed would have destroyed 30GB.
    Removing files stays something the user does in the filesystem; it is
    never a side effect of asking for a different part of a set.
    """
    if existing is None:
        return set()
    return {
        path
        for path in existing.files.filter(done=True).values_list("path", flat=True)
        if path in available_paths
    }


def _folder_summary(files: list[dict]) -> list[dict]:
    summary: dict[str, dict] = {}
    for f in files:
        row = summary.setdefault(folder_of(f["path"]), {"path": folder_of(f["path"]), "file_count": 0, "size": 0})
        row["file_count"] += 1
        row["size"] += f["size"]
    # Biggest first: on a romset the one folder anyone cares about is the
    # one holding 31 of the 32 gigabytes.
    return sorted(summary.values(), key=lambda r: r["size"], reverse=True)


@router.get("/emulators", response=list[EmulatorOut])
def list_emulators(request):
    return [{"id": e.id, "name": e.name, "platform_id": e.platform_id} for e in load_emulators()]


@router.get("/search", response=SearchOut)
def search_sets(request, emulator: str, q: str = "", page: int = 1):
    known = get_emulator(emulator)
    if known is None:
        raise HttpError(404, f"Unknown emulator '{emulator}'.")

    try:
        results, total = archive_org.search(build_query(known, q), page=page, rows=PAGE_SIZE)
    except archive_org.ArchiveOrgError as exc:
        raise HttpError(502, str(exc)) from exc

    return {
        "items": [
            {
                "identifier": r.identifier,
                "title": r.title,
                "size": r.size,
                "downloads": r.downloads,
                "published": r.published,
            }
            for r in results
        ],
        "total": total,
        "page": page,
        "page_size": PAGE_SIZE,
    }


@router.get("/items/{identifier}", response=ItemDetailOut)
def get_item(request, identifier: str):
    try:
        payload = archive_org.item(identifier)
    except archive_org.ArchiveOrgError as exc:
        raise HttpError(502, str(exc)) from exc
    if not payload.get("metadata"):
        raise HttpError(404, f"No archive.org item named '{identifier}'.")

    _root, files, total_size = _item_files(identifier, request.user)
    summary = archive_org.item_summary(payload)
    summary["infohash"] = archive_org.published_infohash(payload)
    summary["restricted"] = archive_org.is_restricted(payload)
    summary["folders"] = _folder_summary(files)
    summary["file_count"] = len(files)
    summary["files_truncated"] = len(files) > FILE_LIST_LIMIT
    summary["files"] = files[:FILE_LIST_LIMIT]
    summary["total_size"] = total_size
    return summary


@router.get("/space", response=LibrarySpaceOut)
def library_space(request):
    report = check_space(0)
    return {
        "free": report.free,
        "committed": report.committed,
        "reserve": report.reserve,
        "available": max(0, report.available),
    }


@router.get("/downloads", response=list[RomSetDownloadOut])
def list_downloads(request):
    return [serialize(r) for r in RomSetDownload.objects.filter(user=request.user).prefetch_related("files")]


@router.get("/downloads/{romset_id}", response=RomSetDownloadDetailOut)
def get_download(request, romset_id: int):
    return _detail(get_object_or_404(RomSetDownload, id=romset_id, user=request.user))


@router.post("/downloads", response=RomSetDownloadDetailOut)
def enqueue_set(request, payload: EnqueueRomSetIn):
    platform = None
    if payload.platform_id:
        platform = Platform.objects.filter(id=payload.platform_id).first()
        if platform is None:
            raise HttpError(400, f"Unknown platform '{payload.platform_id}'.")

    try:
        item = archive_org.item(payload.identifier)
    except archive_org.ArchiveOrgError as exc:
        raise HttpError(502, str(exc)) from exc
    if not item.get("metadata"):
        raise HttpError(404, f"No archive.org item named '{payload.identifier}'.")

    root, files, _total = _item_files(payload.identifier, request.user)
    available_paths = {f["path"] for f in files}

    if payload.paths or payload.folders:
        selected = set(payload.paths or ())
        unknown = selected - available_paths
        if unknown:
            raise HttpError(400, f"These files aren't in the item's torrent: {', '.join(sorted(unknown)[:5])}")

        wanted_folders = set(payload.folders or ())
        known_folders = {folder_of(p) for p in available_paths}
        unknown_folders = wanted_folders - known_folders
        if unknown_folders:
            raise HttpError(400, f"No such folders in this set: {', '.join(sorted(unknown_folders)[:5])}")
        selected |= {p for p in available_paths if folder_of(p) in wanted_folders}
    else:
        selected = set(available_paths)

    if not selected:
        raise HttpError(400, "Select at least one file.")

    existing = RomSetDownload.objects.filter(user=request.user, identifier=payload.identifier).first()

    # Anything this set already downloaded stays selected, whatever the new
    # request asks for. Deselecting a file doesn't just leave it alone:
    # qBittorrent is handed "do not download" for it, and having been given
    # a torrent whose data is already on disk it DELETES that data.
    # Confirmed the hard way — re-requesting a MAME set with only `roms/`
    # ticked wiped the `samples/` folder a previous run had fetched. The
    # same sequence in the other order would have destroyed 30GB.
    #
    # Removing files stays a filesystem operation the user does themselves;
    # it is never a side effect of asking for a different part of a set.
    already_downloaded = carried_forward_paths(existing, available_paths)
    selected |= already_downloaded

    # Two different totals: the set's size (what qBittorrent will report as
    # its wanted size, so it's what progress is measured against) and the
    # bytes this request actually has to fetch, which is what the disk needs
    # room for.
    selected_size = sum(f["size"] for f in files if f["path"] in selected)
    needed = sum(f["size"] for f in files if f["path"] in selected and f["path"] not in already_downloaded)
    report = check_space(needed, exclude_romset_id=existing.id if existing else None)
    if not report.ok:
        raise HttpError(507, report.message())

    summary = archive_org.item_summary(item)
    platform_id = platform.id if platform else None

    with transaction.atomic():
        if existing is not None:
            stale_hash = existing.infohash
            existing.delete()
            if stale_hash:
                transaction.on_commit(lambda h=stale_hash: cancel_romset_torrent.delay(h))

        romset = RomSetDownload.objects.create(
            user=request.user,
            identifier=payload.identifier,
            title=summary["title"] or payload.identifier,
            platform=platform,
            emulator_id=payload.emulator_id or "",
            infohash=archive_org.published_infohash(item) or "",
            save_dir=f"{platform_id or '_unsorted'}/{root}",
            extract=payload.extract,
            total_bytes=selected_size,
        )
        RomSetFile.objects.bulk_create(
            (
                RomSetFile(
                    romset=romset,
                    path=f["path"],
                    size=f["size"],
                    wanted=f["path"] in selected,
                    # Carried over from the run that fetched it, so the new
                    # row doesn't claim to be starting from zero.
                    done=f["path"] in already_downloaded,
                    progress=1.0 if f["path"] in already_downloaded else 0.0,
                )
                for f in files
            ),
            # A reference set is ~4,800 rows; batching keeps this off one
            # enormous INSERT and out of one enormous list in memory.
            batch_size=500,
        )
        transaction.on_commit(lambda: start_romset_download.delay(romset.id))

    return _detail(romset)


@router.post("/downloads/{romset_id}/pause", response=RomSetDownloadDetailOut)
def pause_set(request, romset_id: int):
    romset = get_object_or_404(RomSetDownload, id=romset_id, user=request.user)
    if romset.status == "downloading" and romset.infohash:
        from apps.torrents.client import client as torrent_client
        from apps.torrents.ownership import torrent_in_use

        # A paused set keeps its torrent and its partial data, so only stop
        # the torrent if nothing else is riding the same infohash.
        if not torrent_in_use(romset.infohash, exclude_romset_id=romset.id):
            torrent_client.stop(romset.infohash)
        romset.status = "paused"
        romset.bytes_per_second = 0
        romset.save(update_fields=["status", "bytes_per_second", "updated_at"])
    return _detail(romset)


@router.post("/downloads/{romset_id}/resume", response=RomSetDownloadDetailOut)
def resume_set(request, romset_id: int):
    romset = get_object_or_404(RomSetDownload, id=romset_id, user=request.user)
    if romset.status == "paused" and romset.infohash:
        from apps.torrents.client import client as torrent_client

        torrent_client.resume(romset.infohash)
        romset.status = "downloading"
        romset.save(update_fields=["status", "updated_at"])
    return _detail(romset)


@router.delete("/downloads/{romset_id}", response={204: None})
def cancel_set(request, romset_id: int):
    romset = get_object_or_404(RomSetDownload, id=romset_id, user=request.user)
    infohash = romset.infohash
    romset.delete()
    if infohash:
        # Files already on disk are left alone deliberately: the library
        # folder is the user's, and a cancelled 40 GB set is usually worth
        # resuming rather than re-fetching.
        transaction.on_commit(lambda: cancel_romset_torrent.delay(infohash))
    return 204, None
