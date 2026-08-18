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


def build_state() -> dict:
    """Whether any build currently holds the one-at-a-time ingestion slot.

    Derived from the DB rather than passed in by the caller, so a start and
    a finish event can't disagree about the truth — every call site just
    says "this may have changed" and the query decides.
    """
    from apps.catalog.models import CatalogBuild

    build = CatalogBuild.objects.filter(status="running").order_by("-started_at").first()
    return {
        "running": build is not None,
        "build_id": build.pk if build else None,
        "started_at": build.started_at.isoformat() if build else None,
    }


def push_build_status() -> None:
    """Tell every connected client whether the ingestion slot is taken, so
    the Sources page can disable Run everywhere instead of letting the user
    click into a 409."""
    layer = get_channel_layer()
    if layer is None:
        return
    try:
        async_to_sync(layer.group_send)(
            GROUP_NAME,
            {"type": "ingestion.event", "event": "build.status", "data": build_state()},
        )
    except Exception:  # noqa: BLE001 - same as below: never fail a run over a progress tick
        pass


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
