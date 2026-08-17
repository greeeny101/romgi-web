"""
Ninja endpoints for the downloads app. `POST /downloads` snapshots the
caller's chosen Link (or every member of a group) into a new DownloadTask
and hands off to Celery; live progress travels over the Channels WS
(apps.realtime.consumers.DownloadProgressConsumer), not polling.
"""

import os

from django.conf import settings as django_settings
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from ninja import Query, Router
from ninja.errors import HttpError
from ninja_jwt.authentication import JWTAuth

from apps.catalog.models import CatalogBuild, Entry, EntryGroup, Link, Source

from .models import DownloadTask
from .schemas import DownloadTaskOut, EnqueueIn, VerifyResultOut
from .tasks import dispatch_next_for_user

router = Router(tags=["downloads"], auth=JWTAuth())

# A task in one of these states already occupies a slot for its slug — a
# fresh enqueue of the same title would just duplicate it in the queue.
ACTIVE_STATUSES = ("pending", "downloading", "paused", "extracting")


def _active_build() -> CatalogBuild:
    build = CatalogBuild.objects.filter(status="active").order_by("-started_at").first()
    if build is None:
        raise HttpError(404, "No active catalog build.")
    return build


def _active_task_for(user, slug: str) -> DownloadTask | None:
    return DownloadTask.objects.filter(user=user, slug=slug, status__in=ACTIVE_STATUSES).first()


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
        error=task.error,
        group_key=task.group_key,
        group_title=task.group_title,
        group_index=task.group_index,
        playlist_file=task.playlist_file,
        retry_count=task.retry_count,
        created_at=task.created_at.isoformat(),
        completed_at=task.completed_at.isoformat() if task.completed_at else None,
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
def enqueue(request, payload: EnqueueIn):
    build = _active_build()

    if payload.group_id is not None:
        group = get_object_or_404(EntryGroup, id=payload.group_id, build=build)
        created = None
        any_active = False
        for member in group.members.select_related("entry").order_by("member_index"):
            if _active_task_for(request.user, member.entry.slug):
                any_active = True
                continue
            link = member.entry.links.order_by("-source__priority").first()
            if link is None:
                continue
            task = _enqueue_one(request.user, member.entry, link, group=group, group_index=member.member_index)
            created = created or task
        if created is None:
            if any_active:
                raise HttpError(409, "This title is already in your download queue.")
            raise HttpError(404, "No downloadable links found for this group.")
        dispatch_next_for_user(request.user.id)
        return _out(created)

    entry = get_object_or_404(Entry, slug=payload.slug, build=build)
    if _active_task_for(request.user, entry.slug):
        raise HttpError(409, f'"{entry.title}" is already in your download queue.')

    if payload.link_id is not None:
        link = get_object_or_404(Link, id=payload.link_id, entry=entry)
    else:
        link = entry.links.order_by("-source__priority").first()
        if link is None:
            raise HttpError(404, "No links found for this entry.")

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
    torrent_hash = task.torrent_hash
    task.delete()
    if torrent_hash:
        from apps.torrents.tasks import cancel_torrent

        cancel_torrent.delay(torrent_hash)
    dispatch_next_for_user(user_id)
    return 204, None


@router.get("/{task_id}/file")
def download_file(request, task_id: int):
    task = get_object_or_404(DownloadTask, id=task_id, user=request.user)
    if task.status != "completed" or not task.staged_file:
        raise HttpError(409, "This download is not ready yet.")

    path = os.path.join(django_settings.STAGED_FILES_DIR, str(task.id), task.staged_file)
    if not os.path.exists(path):
        raise Http404("Staged file no longer available.")

    if task.first_retrieved_at is None:
        task.first_retrieved_at = timezone.now()
        task.save(update_fields=["first_retrieved_at"])

    return FileResponse(open(path, "rb"), as_attachment=True, filename=os.path.basename(path))


@router.post("/{task_id}/verify", response=VerifyResultOut)
def verify_download(request, task_id: int):
    """Backs the Library "Downloaded" tab's Verify action — confirms the
    staged file backing a completed task is still actually present on
    disk (it may have been purged by cleanup_expired_staged_files, or the
    retention window may already be tracked but not yet enforced), and
    corrects task state if it's gone."""
    task = get_object_or_404(DownloadTask, id=task_id, user=request.user)
    if task.status != "completed":
        return VerifyResultOut(exists=False, message="This download never completed.")
    if not task.staged_file:
        return VerifyResultOut(exists=False, message="File already removed.")

    path = os.path.join(django_settings.STAGED_FILES_DIR, str(task.id), task.staged_file)
    if os.path.exists(path):
        return VerifyResultOut(exists=True, message=None)

    task.staged_file = ""
    task.save(update_fields=["staged_file"])
    return VerifyResultOut(exists=False, message="File is no longer available on the server.")
