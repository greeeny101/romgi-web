"""
Ports lib/services/game_metadata_service.dart's cache table. One row per
`cache_key` = f"{platform}|{clean_title(title).lower()}" holding the
*merged* result across every configured provider — not per-provider, and
not per-Entry/slug: cache_key is title-derived so multi-disc entries
("Game (Disc 1)"/"Game (Disc 2)") share one row and one fetch, exactly like
the original app. Global/shared across all users, unlike credentials —
whoever's API keys pay for a fetch, the cached result benefits everyone,
same as the source app's single on-device cache.
"""

from django.db import models


class GameMetadataCache(models.Model):
    cache_key = models.TextField(unique=True)
    # {"description": str|None, "screenshots": [str], "artwork": [str]} —
    # None when no_match (nothing worth caching but the negative result).
    data = models.JSONField(null=True, blank=True)
    no_match = models.BooleanField(default=False)
    fetched_at = models.DateTimeField(auto_now=True, db_index=True)

    def __str__(self) -> str:
        return f"GameMetadataCache<{self.cache_key}>"
