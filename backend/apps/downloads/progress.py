"""Publishes DownloadTask state to the per-user `user_{id}_downloads`
Channels group — see apps.realtime.consumers.DownloadProgressConsumer."""

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer


def _source_name(source_id: str | None) -> str | None:
    if not source_id:
        return None
    from apps.catalog.models import Source

    return Source.objects.filter(id=source_id).values_list("name", flat=True).first() or source_id


def _serialize(task) -> dict:
    return {
        "id": task.id,
        "slug": task.slug,
        "title": task.title,
        "platform_id": task.platform_id,
        "platform_name": task.platform.name,
        "status": task.status,
        "progress": task.progress,
        "downloaded_bytes": task.downloaded_bytes,
        "total_bytes": task.total_bytes,
        "bytes_per_second": task.bytes_per_second,
        "link_name": task.link_name,
        "link_host": task.link_host,
        "link_is_torrent": task.link_is_torrent,
        "source_id": task.link_source_id or None,
        "source_name": _source_name(task.link_source_id),
        "error": task.error,
        "group_key": task.group_key,
        "group_title": task.group_title,
        "group_index": task.group_index,
        "created_at": task.created_at.isoformat(),
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
    }


def _send(task, event_type: str, extra: dict | None = None) -> None:
    layer = get_channel_layer()
    if layer is None:
        return
    payload = _serialize(task)
    if extra:
        payload.update(extra)
    async_to_sync(layer.group_send)(
        f"user_{task.user_id}_downloads",
        {"type": "download.event", "event": event_type, "data": payload},
    )


def push_progress(task, **extra) -> None:
    """`extra` carries live-only fields that never get persisted on
    DownloadTask (e.g. torrent peers/seeds) — see the plan's note on
    keeping those in the WS payload only."""
    _send(task, "download.progress", extra)


def push_status(task, **extra) -> None:
    event = {"completed": "download.completed", "failed": "download.failed"}.get(task.status, "download.progress")
    _send(task, event, extra)
