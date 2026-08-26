"""Publishes RomSetDownload state to the per-user `user_{id}_romsets`
Channels group — see apps.realtime.consumers.RomSetProgressConsumer."""

import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

logger = logging.getLogger(__name__)


def serialize(romset) -> dict:
    return {
        "id": romset.id,
        "identifier": romset.identifier,
        "title": romset.title,
        "provider": romset.provider,
        "platform_id": romset.platform_id,
        "emulator_id": romset.emulator_id,
        "status": romset.status,
        "progress": romset.progress,
        "downloaded_bytes": romset.downloaded_bytes,
        "total_bytes": romset.total_bytes,
        "bytes_per_second": romset.bytes_per_second,
        "save_dir": romset.save_dir,
        "extract": romset.extract,
        "error": romset.error,
        # The client upserts this payload over the whole object, so every
        # field RomSetDownloadOut declares has to be here — anything omitted
        # comes back undefined and silently drops out of the rendered row.
        # Same trap as downloads.progress._serialize.
        "file_count": romset.files.count(),
        "wanted_count": romset.files.filter(wanted=True).count(),
        "created_at": romset.created_at.isoformat(),
        "completed_at": romset.completed_at.isoformat() if romset.completed_at else None,
    }


def _send(romset, event_type: str, extra: dict | None = None) -> None:
    layer = get_channel_layer()
    if layer is None:
        return
    payload = serialize(romset)
    if extra:
        payload.update(extra)
    try:
        async_to_sync(layer.group_send)(
            f"user_{romset.user_id}_romsets",
            {"type": "romset.event", "event": event_type, "data": payload},
        )
    except Exception:
        # A Redis blip must not kill the poll beat mid-tick and strand every
        # other set in the same pass — apps.downloads.progress doesn't guard
        # this and apps.ingestion.progress does; the latter is right.
        logger.warning("Could not push romset progress for %s", romset.id, exc_info=True)


def push_progress(romset, **extra) -> None:
    _send(romset, "romset.progress", extra)


def push_status(romset, **extra) -> None:
    event = {"completed": "romset.completed", "failed": "romset.failed"}.get(romset.status, "romset.progress")
    _send(romset, event, extra)
