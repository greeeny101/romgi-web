"""
Ninja endpoints for the downloads app. `POST /downloads` snapshots the
caller's chosen Link (or every member of a group) into a new DownloadTask
and hands off to Celery; live progress travels over the Channels WS
(apps.realtime.consumers.DownloadProgressConsumer), not polling.

A slug gets at most one DownloadTask per user (enforced by
DownloadTask's download_user_slug_uniq constraint): re-downloading a
title replaces the previous attempt instead of stacking another row.
"""

import os
import shutil

from django.conf import settings as django_settings
from django.db import transaction
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from ninja import Query, Router
from ninja.errors import HttpError
from ninja_jwt.authentication import JWTAuth

from apps.catalog.models import CatalogBuild, Entry, EntryGroup, Link, Source
from apps.library.models import Favorite

from .models import DownloadTask
from .schemas import DownloadTaskOut, EnqueueIn
from .tasks import dispatch_next_for_user

router = Router(tags=["downloads"], auth=JWTAuth())


def _active_build() -> CatalogBuild:
    build = CatalogBuild.objects.filter(status="active").order_by("-started_at").first()
    if build is None:
        raise HttpError(404, "No active catalog build.")
    return build


def _discard_task(task: DownloadTask) -> None:
    """Tears a task down completely: drops the row, its staged bytes and
    its qBittorrent slot. The filesystem/Celery side effects are deferred
    to commit so a rolled-back transaction can't leave a surviving row
    pointing at a directory that's already gone."""
    torrent_hash = task.torrent_hash
    directory = os.path.join(django_settings.STAGED_FILES_DIR, str(task.id))
    task.delete()
    transaction.on_commit(lambda: shutil.rmtree(directory, ignore_errors=True))
    if torrent_hash:
        from apps.torrents.tasks import cancel_torrent

        transaction.on_commit(lambda: cancel_torrent.delay(torrent_hash))


def _discard_existing(user, slug: str) -> None:
    """Clears the way for a re-download of `slug`. Enqueue used to refuse
    while a task was still in flight and silently append a second row once
    it wasn't, which is what left duplicate entries on the downloads page;
    now the newest request always wins and there is only ever one row."""
    for task in DownloadTask.objects.filter(user=user, slug=slug):
        _discard_task(task)


def _staged_size(task: DownloadTask) -> int | None:
    """Bytes of the file the user will actually save. Read off disk rather
    than stored: total_bytes is what the transfer moved, which stops matching
    the moment a disc set is collapsed into a .chd (a fraction of the size),
    and the retention sweep can remove the file at any point."""
    if not task.staged_file:
        return None
    path = os.path.join(django_settings.STAGED_FILES_DIR, str(task.id), task.staged_file)
    try:
        return os.path.getsize(path)
    except OSError:
        return None


def _out(task: DownloadTask, sources_by_id: dict[str, str] | None = None) -> DownloadTaskOut:
    source_name = None
    if task.link_source_id:
        if sources_by_id is not None:
            source_name = sources_by_id.get(task.link_source_id)
        else:
            source_name = Source.objects.filter(id=task.link_source_id).values_list("name", flat=True).first()
    return DownloadTaskOut(
        id=task.id,
        slug=task.slug,
        title=task.title,
        platform_id=task.platform_id,
        platform_name=task.platform.name,
        status=task.status,
        progress=task.progress,
        downloaded_bytes=task.downloaded_bytes,
        total_bytes=task.total_bytes,
        bytes_per_second=task.bytes_per_second,
        link_name=task.link_name,
        link_host=task.link_host,
        link_is_torrent=task.link_is_torrent,
        source_id=task.link_source_id or None,
        source_name=source_name or task.link_source_id or None,
        region_ids=task.region_ids or [],
        error=task.error,
        group_key=task.group_key,
        group_title=task.group_title,
        group_index=task.group_index,
        playlist_file=task.playlist_file,
        retry_count=task.retry_count,
        created_at=task.created_at.isoformat(),
        completed_at=task.completed_at.isoformat() if task.completed_at else None,
        # staged_file is the authoritative "the bytes are still there" flag:
        # every path that removes the staged directory blanks it in the same
        # breath (cleanup_expired_staged_files, and _discard_task drops the
        # row outright), so it can't point at a directory that's already gone.
        file_available=bool(task.staged_file),
        file_size=_staged_size(task),
        expires_at=task.expires_at.isoformat() if task.expires_at else None,
        first_retrieved_at=task.first_retrieved_at.isoformat() if task.first_retrieved_at else None,
        last_retrieved_at=task.last_retrieved_at.isoformat() if task.last_retrieved_at else None,
    )


def _enqueue_one(user, entry: Entry, link: Link, group: EntryGroup | None = None, group_index=None) -> DownloadTask:
    return DownloadTask.objects.create(
        user=user,
        slug=entry.slug,
        title=entry.title,
        platform_id=entry.platform_id,
        link_name=link.name,
        link_url=link.url,
        link_filename=link.filename,
        link_host=link.host,
        link_size=link.size,
        link_source_id=link.source_id,
        region_ids=list(entry.regions.values_list("id", flat=True)),
        link_requires_auth=link.requires_auth,
        link_is_torrent=link.torrent_id is not None,
        link_torrent_magnet=(link.torrent.magnet or "") if link.torrent_id else "",
        link_torrent_file_index=link.torrent_file_index,
        group_key=group.group_key if group else "",
        group_title=(group.title or "") if group else "",
        group_index=group_index,
        group_total=group.member_count if group else None,
    )


@router.post("", response=DownloadTaskOut)
@transaction.atomic
def enqueue(request, payload: EnqueueIn):
    """Enqueues a title, replacing any task the user already has for the
    same slug. Each link is resolved before its predecessor is discarded,
    so a request that turns out to have nothing to download leaves the
    existing queue untouched."""
    build = _active_build()

    if payload.group_id is not None:
        group = get_object_or_404(EntryGroup, id=payload.group_id, build=build)
        members = [
            (member, member.entry.links.order_by("-source__priority").first())
            for member in group.members.select_related("entry")
            .prefetch_related("entry__regions")
            .order_by("member_index")
        ]
        if not any(link for _, link in members):
            raise HttpError(404, "No downloadable links found for this group.")
        created = None
        for member, link in members:
            if link is None:
                continue
            _discard_existing(request.user, member.entry.slug)
            task = _enqueue_one(request.user, member.entry, link, group=group, group_index=member.member_index)
            created = created or task
        dispatch_next_for_user(request.user.id)
        return _out(created)

    entry = get_object_or_404(Entry, slug=payload.slug, build=build)
    if payload.link_id is not None:
        link = get_object_or_404(Link, id=payload.link_id, entry=entry)
    else:
        link = entry.links.order_by("-source__priority").first()
        if link is None:
            raise HttpError(404, "No links found for this entry.")

    _discard_existing(request.user, entry.slug)
    task = _enqueue_one(request.user, entry, link)
    dispatch_next_for_user(request.user.id)
    return _out(task)


@router.get("", response=list[DownloadTaskOut])
def list_downloads(request, status: str = Query(None)):
    qs = DownloadTask.objects.filter(user=request.user).select_related("platform")
    if status:
        qs = qs.filter(status=status)
    sources_by_id = dict(Source.objects.values_list("id", "name"))
    return [_out(t, sources_by_id) for t in qs]


@router.get("/{task_id}", response=DownloadTaskOut)
def get_download(request, task_id: int):
    task = get_object_or_404(DownloadTask, id=task_id, user=request.user)
    return _out(task)


@router.post("/{task_id}/pause", response=DownloadTaskOut)
def pause_download(request, task_id: int):
    task = get_object_or_404(DownloadTask, id=task_id, user=request.user)
    if task.status in ("pending", "downloading"):
        # For HTTP downloads, http_download's own copy loop polls this
        # status and exits on its own — see downloads.tasks._should_abort.
        # A torrent keeps transferring in qBittorrent regardless, so it
        # needs to be told directly.
        if task.link_is_torrent and task.torrent_hash:
            from apps.torrents.client import client as torrent_client

            torrent_client.stop(task.torrent_hash)
        task.status = "paused"
        task.save(update_fields=["status", "updated_at"])
    return _out(task)


@router.post("/{task_id}/resume", response=DownloadTaskOut)
def resume_download(request, task_id: int):
    task = get_object_or_404(DownloadTask, id=task_id, user=request.user)
    if task.status == "paused":
        if task.link_is_torrent and task.torrent_hash:
            from apps.torrents.client import client as torrent_client

            torrent_client.resume(task.torrent_hash)
            task.status = "downloading"
        else:
            task.status = "pending"
        task.save(update_fields=["status", "updated_at"])
        dispatch_next_for_user(request.user.id)
    return _out(task)


@router.post("/{task_id}/retry", response=DownloadTaskOut)
def retry_download(request, task_id: int):
    task = get_object_or_404(DownloadTask, id=task_id, user=request.user)
    if task.status != "failed":
        raise HttpError(400, "Only failed downloads can be retried.")
    task.status = "pending"
    task.progress = 0.0
    task.downloaded_bytes = 0
    task.total_bytes = 0
    task.error = ""
    task.retry_count += 1
    # A manual retry always re-enters debrid resolution from scratch if the
    # original link was a torrent — matches Dart's retryDownload reverting
    # debridResolved and clearing the relink-attempt counter.
    if task.debrid_resolved:
        task.link_is_torrent = True
        task.debrid_resolved = False
    task.debrid_relink_attempts = 0
    task.save()
    dispatch_next_for_user(request.user.id)
    return _out(task)


@router.delete("/{task_id}", response={204: None})
def cancel_download(request, task_id: int):
    task = get_object_or_404(DownloadTask, id=task_id, user=request.user)
    user_id = task.user_id
    _discard_task(task)
    dispatch_next_for_user(user_id)
    return 204, None


@router.get("/{task_id}/file")
def download_file(request, task_id: int):
    task = get_object_or_404(DownloadTask, id=task_id, user=request.user)
    if task.status != "completed" or not task.staged_file:
        raise HttpError(409, "This download is not ready yet.")

    path = os.path.join(django_settings.STAGED_FILES_DIR, str(task.id), task.staged_file)
    if not os.path.exists(path):
        # Blank staged_file so file_available stops advertising bytes that
        # aren't there. cleanup_expired_staged_files does this for anything it
        # purges, but it's an hourly beat and can't see a file removed out from
        # under it, so this is the correction path the removed verify endpoint
        # used to provide.
        task.staged_file = ""
        task.save(update_fields=["staged_file"])
        raise Http404("Staged file no longer available.")

    # last_retrieved_at moves every time; first_retrieved_at is set once and
    # then left alone, because cleanup_expired_staged_files reads a null there
    # as "nobody ever claimed this".
    now = timezone.now()
    fields = ["last_retrieved_at"]
    task.last_retrieved_at = now
    if task.first_retrieved_at is None:
        task.first_retrieved_at = now
        fields.append("first_retrieved_at")
    task.save(update_fields=fields)

    # A wishlist is a list of things you still want, so downloading a title and
    # saving the file off the server is exactly the point at which it stops
    # belonging there. Keyed by slug, not task id, because Favorite snapshots a
    # slug rather than FK'ing the entry (see library.models). Unconditional
    # rather than only on the first save: re-favoriting a title you already have
    # and saving it again means the same thing.
    Favorite.objects.filter(user=request.user, slug=task.slug).delete()

    return FileResponse(open(path, "rb"), as_attachment=True, filename=os.path.basename(path))
