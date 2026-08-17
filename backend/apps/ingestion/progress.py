"""Publishes SourceHealth state to the global `ingestion_progress` Channels
group — see apps.realtime.consumers.IngestionProgressConsumer.

Unlike downloads (per-user groups, since DownloadTask has a user FK),
Source/SourceHealth are global rows, so every connected client shares one
fixed group name."""

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

GROUP_NAME = "ingestion_progress"


def _serialize(health) -> dict:
    return {
        "source_id": health.source_id,
        "status": health.status,
        "last_checked_at": health.last_checked_at.isoformat() if health.last_checked_at else None,
        "notes": health.notes,
        "entry_count": health.entry_count,
        "link_count": health.link_count,
    }


def push_source_health(health) -> None:
    layer = get_channel_layer()
    if layer is None:
        return
    try:
        async_to_sync(layer.group_send)(
            GROUP_NAME,
            {"type": "ingestion.event", "event": "source.health", "data": _serialize(health)},
        )
    except Exception:  # noqa: BLE001 - a dropped progress tick must never fail a scrape run
        pass
