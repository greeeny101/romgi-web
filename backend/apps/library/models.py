"""
Favorite/RecentlyViewed intentionally do NOT hold a hard FK to
catalog.Entry: Entry rows are per-CatalogBuild and get cascade-deleted once
their build is garbage-collected (see ingestion.orchestrator.gc_old_builds).
A user's favorite needs to survive catalog rebuilds, so it stores a
portable (slug, title, boxart_url) snapshot instead — same reasoning as the
DownloadTask link-snapshot design in the plan. `platform` is a real FK since
Platform rows are static reference data, never build-scoped or deleted.
"""

from django.conf import settings
from django.db import models


class Favorite(models.Model):
    """The Wishlist tab in the original app."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="favorites")
    slug = models.TextField()
    title = models.TextField()
    platform = models.ForeignKey("catalog.Platform", on_delete=models.CASCADE, related_name="+")
    boxart_url = models.URLField(max_length=2048, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "slug"], name="unique_favorite"),
        ]
        ordering = ["-created_at"]


class RecentlyViewed(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="recently_viewed")
    slug = models.TextField()
    title = models.TextField()
    platform = models.ForeignKey("catalog.Platform", on_delete=models.CASCADE, related_name="+")
    boxart_url = models.URLField(max_length=2048, null=True, blank=True)
    viewed_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "slug"], name="unique_recently_viewed"),
        ]
        ordering = ["-viewed_at"]
