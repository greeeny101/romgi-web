"""
Ports lib/services/game_metadata_service.dart's caching orchestrator: TTL
cache (14d hit / 3d miss, checked at read time — no eager expiry), a
multi-disc-dedup cache key derived from a cleaned title, errors never
cached, and "first non-null description wins" provider-merge order
(ScreenScraper before SteamGridDB, matching the registry's construction
order).
"""

import re

from django.utils import timezone

from apps.credentials.models import EncryptedCredential

from .models import GameMetadataCache
from .providers.base import MediaItem, MetadataError, MetadataFound, MetadataNoMatch
from .providers.registry import registry

HIT_TTL = timezone.timedelta(days=14)
MISS_TTL = timezone.timedelta(days=3)
PRUNE_AFTER = timezone.timedelta(days=30)

_BRACKET_RE = re.compile(r"\s*[\(\[][^)\]]*[\)\]]")
_WHITESPACE_RE = re.compile(r"\s+")


def clean_title(title: str) -> str:
    cleaned = _BRACKET_RE.sub(" ", title)
    cleaned = _WHITESPACE_RE.sub(" ", cleaned)
    return cleaned.strip()


def _media_from_cache(values) -> list[MediaItem]:
    items = (MediaItem.from_cached(v) for v in (values or []))
    return [item for item in items if item is not None]


def _creds_for(user, provider_id: str) -> dict:
    credential = EncryptedCredential.objects.filter(user=user, provider=provider_id).first()
    return (credential.data or {}) if credential else {}


def get_metadata(user, title: str, platform: str) -> MetadataFound | None:
    """Global/shared cache, not per-user — whoever's API keys pay for a
    fetch, the cached result benefits every user who views that game
    afterward, same as the source app's single on-device cache."""
    configured = []
    for provider in registry:
        creds = _creds_for(user, provider.info.id)
        if provider.is_configured(creds):
            configured.append((provider, creds))
    if not configured:
        return None

    clean = clean_title(title)
    if not clean:
        return None
    cache_key = f"{platform}|{clean.lower()}"

    cached = GameMetadataCache.objects.filter(cache_key=cache_key).first()
    if cached:
        ttl = MISS_TTL if cached.no_match else HIT_TTL
        if timezone.now() - cached.fetched_at < ttl:
            if cached.no_match:
                return None
            if cached.data:
                return MetadataFound(
                    description=cached.data.get("description"),
                    screenshots=_media_from_cache(cached.data.get("screenshots")),
                    artwork=_media_from_cache(cached.data.get("artwork")),
                )

    description = None
    screenshots: list[MediaItem] = []
    artwork: list[MediaItem] = []
    any_answered = False

    for provider, creds in configured:
        try:
            result = provider.fetch(clean, platform, creds)
        except Exception:
            continue
        if isinstance(result, MetadataFound):
            any_answered = True
            if description is None:
                description = result.description
            screenshots.extend(result.screenshots)
            artwork.extend(result.artwork)
        elif isinstance(result, MetadataNoMatch):
            any_answered = True
        elif isinstance(result, MetadataError):
            continue  # never counts as an answer — errors are never cached

    if not any_answered:
        return None

    is_empty = not description and not screenshots and not artwork
    GameMetadataCache.objects.update_or_create(
        cache_key=cache_key,
        defaults={
            "data": None
            if is_empty
            else {
                "description": description,
                "screenshots": [m.as_dict() for m in screenshots],
                "artwork": [m.as_dict() for m in artwork],
            },
            "no_match": is_empty,
        },
    )
    # Opportunistic housekeeping — Dart prunes rows older than 30 days on
    # every write, separate from the per-row TTL enforced above at read time.
    GameMetadataCache.objects.filter(fetched_at__lt=timezone.now() - PRUNE_AFTER).delete()

    if is_empty:
        return None
    return MetadataFound(description=description, screenshots=screenshots, artwork=artwork)
