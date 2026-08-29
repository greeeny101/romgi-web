"""Publishes BiosDownload state to the per-user `user_{id}_bios` Channels
group — see apps.realtime.consumers.BiosProgressConsumer."""

import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

logger = logging.getLogger(__name__)


def serialize(bios) -> dict:
    return {
        "id": bios.id,
        "identifier": bios.identifier,
        "title": bios.title,
        "provider": bios.provider,
        "platform_id": bios.platform_id,
        "source_id": bios.source_id,
        "status": bios.status,
        "progress": bios.progress,
        "downloaded_bytes": bios.downloaded_bytes,
        "total_bytes": bios.total_bytes,
        "bytes_per_second": bios.bytes_per_second,
        "save_dir": bios.save_dir,
        "extract": bios.extract,
        "error": bios.error,
        # The client upserts this payload over the whole object, so every
        # field BiosDownloadOut declares has to be here — anything omitted
        # comes back undefined and silently drops out of the rendered row.
        # Same trap as romsets.progress.serialize.
        "file_count": bios.files.count(),
        "wanted_count": bios.files.filter(wanted=True).count(),
        "created_at": bios.created_at.isoformat(),
        "completed_at": bios.completed_at.isoformat() if bios.completed_at else None,
    }


def _send(bios, event_type: str, extra: dict | None = None) -> None:
    layer = get_channel_layer()
    if layer is None:
        return
    payload = serialize(bios)
    if extra:
        payload.update(extra)
    try:
        async_to_sync(layer.group_send)(
            f"user_{bios.user_id}_bios",
            {"type": "bios.event", "event": event_type, "data": payload},
        )
    except Exception:
        # A Redis blip must not take the transfer down with it — the bytes
        # are still landing on disk and the row is still correct, only the
        # live view is stale until the next push.
        logger.warning("Could not push bios progress for %s", bios.id, exc_info=True)


def push_progress(bios, **extra) -> None:
    _send(bios, "bios.progress", extra)


def push_status(bios, **extra) -> None:
    event = {"completed": "bios.completed", "failed": "bios.failed"}.get(bios.status, "bios.progress")
    _send(bios, event, extra)
