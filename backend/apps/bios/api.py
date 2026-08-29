"""
Ninja endpoints for the BIOS browser.

Search and item detail are thin proxies onto archive.org (cached), so the
browser never talks to archive.org directly and one user's search warms the
cache for everyone — the same arrangement apps.romsets.api uses. `POST
/bios/downloads` records the file selection and hands off to Celery.
"""

from __future__ import annotations

from django.db import transaction
from django.shortcuts import get_object_or_404
from ninja import Router
from ninja.errors import HttpError
from ninja_jwt.authentication import JWTAuth

from apps.catalog.models import Platform
from apps.common import archive_org

from .files import selectable
from .models import BiosDownload, BiosFile
from .progress import serialize
from .schemas import (
    BiosDownloadDetailOut,
    BiosDownloadOut,
    BiosSourceOut,
    EnqueueBiosIn,
    ItemDetailOut,
    SearchOut,
)
from .sources import build_query, get_source, load_sources
from .tasks import start_bios_download

router = Router(tags=["bios"], auth=JWTAuth())

PAGE_SIZE = 25


def _detail(bios: BiosDownload) -> dict:
    payload = serialize(bios)
    payload["files"] = [
        {
            "name": f.name,
            "size": f.size,
            "wanted": f.wanted,
            "progress": f.progress,
            "done": f.done,
            "error": f.error,
        }
        for f in bios.files.all()
    ]
    return payload


def _item_files(payload: dict) -> list[dict]:
    """The item's downloadable files, from the metadata API.

    Unlike a romset — where the list has to come from the torrent, because
    the metadata API lists derived files the torrent doesn't contain and
    only what's in the torrent can be fetched — HTTP fetches whatever
    `/download/<id>/<name>` resolves, which is exactly what the metadata API
    lists. So this is the authoritative list here; it just needs archive.org's
    own bookkeeping filtered out of it.
    """
    return sorted(
        (
            {"name": name, "size": detail["size"], "format": detail["format"], "md5": detail["md5"]}
            for name, detail in archive_org.file_details(payload).items()
            if selectable(name)
        ),
        key=lambda f: f["name"],
    )


def _fetch_item(identifier: str) -> dict:
    try:
        payload = archive_org.item(identifier)
    except archive_org.ArchiveOrgError as exc:
        raise HttpError(502, str(exc)) from exc
    if not payload.get("metadata"):
        raise HttpError(404, f"No archive.org item named '{identifier}'.")
    return payload


@router.get("/sources", response=list[BiosSourceOut])
def list_sources(request):
    return [{"id": s.id, "name": s.name, "platform_id": s.platform_id} for s in load_sources()]


@router.get("/search", response=SearchOut)
def search_bios(request, source: str, q: str = "", page: int = 1):
    known = get_source(source)
    if known is None:
        raise HttpError(404, f"Unknown BIOS source '{source}'.")

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
    payload = _fetch_item(identifier)
    files = _item_files(payload)

    summary = archive_org.item_summary(payload)
    summary["restricted"] = archive_org.is_restricted(payload)
    summary["files"] = files
    summary["file_count"] = len(files)
    summary["total_size"] = sum(f["size"] for f in files)
    return summary


@router.get("/downloads", response=list[BiosDownloadOut])
def list_downloads(request):
    return [serialize(b) for b in BiosDownload.objects.filter(user=request.user).prefetch_related("files")]


@router.get("/downloads/{bios_id}", response=BiosDownloadDetailOut)
def get_download(request, bios_id: int):
    return _detail(get_object_or_404(BiosDownload, id=bios_id, user=request.user))


@router.post("/downloads", response=BiosDownloadDetailOut)
def enqueue_bios(request, payload: EnqueueBiosIn):
    platform = None
    if payload.platform_id:
        platform = Platform.objects.filter(id=payload.platform_id).first()
        if platform is None:
            raise HttpError(400, f"Unknown platform '{payload.platform_id}'.")

    item = _fetch_item(payload.identifier)
    files = _item_files(item)
    available = {f["name"] for f in files}

    if payload.names:
        selected = set(payload.names)
        unknown = selected - available
        if unknown:
            raise HttpError(400, f"These files aren't in the item: {', '.join(sorted(unknown)[:5])}")
    else:
        selected = set(available)

    if not selected:
        raise HttpError(400, "Select at least one file.")

    summary = archive_org.item_summary(item)
    platform_id = platform.id if platform else None

    with transaction.atomic():
        # Re-requesting an item replaces the previous attempt. Nothing needs
        # tearing down first: no torrent is involved, and files already on
        # disk are left alone — a second run resumes them by Range rather
        # than re-fetching, so a narrower selection is genuinely passive
        # here (unlike a romset, where deselecting makes qBittorrent delete).
        BiosDownload.objects.filter(user=request.user, identifier=payload.identifier).delete()

        bios = BiosDownload.objects.create(
            user=request.user,
            identifier=payload.identifier,
            title=summary["title"] or payload.identifier,
            platform=platform,
            source_id=payload.source_id or "",
            save_dir=f"bios/{platform_id or '_unsorted'}",
            extract=payload.extract,
            total_bytes=sum(f["size"] for f in files if f["name"] in selected),
        )
        BiosFile.objects.bulk_create(
            BiosFile(
                bios=bios,
                name=f["name"],
                size=f["size"],
                md5=f["md5"] or "",
                wanted=f["name"] in selected,
            )
            for f in files
        )
        transaction.on_commit(lambda: start_bios_download.delay(bios.id))

    return _detail(bios)


@router.post("/downloads/{bios_id}/pause", response=BiosDownloadDetailOut)
def pause_bios(request, bios_id: int):
    bios = get_object_or_404(BiosDownload, id=bios_id, user=request.user)
    if bios.status in ("pending", "downloading"):
        # The running task polls this column between chunks and stops on its
        # own, leaving the partial file for a Range resume — see
        # tasks._should_abort. There is nothing to signal out-of-process.
        bios.status = "paused"
        bios.bytes_per_second = 0
        bios.save(update_fields=["status", "bytes_per_second", "updated_at"])
    return _detail(bios)


@router.post("/downloads/{bios_id}/resume", response=BiosDownloadDetailOut)
def resume_bios(request, bios_id: int):
    bios = get_object_or_404(BiosDownload, id=bios_id, user=request.user)
    if bios.status == "paused":
        bios.status = "pending"
        bios.error = ""
        bios.save(update_fields=["status", "error", "updated_at"])
        transaction.on_commit(lambda: start_bios_download.delay(bios.id))
    return _detail(bios)


@router.delete("/downloads/{bios_id}", response={204: None})
def cancel_bios(request, bios_id: int):
    bios = get_object_or_404(BiosDownload, id=bios_id, user=request.user)
    # Files already on disk are left alone deliberately: the library folder
    # is the user's, and the running task notices the row is gone on its
    # next chunk and exits — same contract as cancelling a ROM set.
    bios.delete()
    return 204, None
