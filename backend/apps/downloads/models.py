"""
DownloadTask is the server-side equivalent of the Dart app's in-memory
queue + on-device DownloadTask (lib/services/download_service.dart /
lib/models/download_task.dart) — see the plan's porting reference map.

The chosen Link is snapshotted at enqueue/failover time (the link_* fields)
rather than FK'd, for the same reason as library.Favorite: Link rows are
per-CatalogBuild and get cascade-deleted once their build is
garbage-collected, but an in-flight or historical download must survive a
catalog rebuild.
"""

from django.conf import settings
from django.db import models


class DownloadTask(models.Model):
    STATUS_CHOICES = [
        ("pending", "pending"),
        ("downloading", "downloading"),
        ("paused", "paused"),
        ("extracting", "extracting"),
        ("completed", "completed"),
        ("failed", "failed"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="download_tasks")
    slug = models.TextField()
    title = models.TextField()
    platform = models.ForeignKey("catalog.Platform", on_delete=models.CASCADE, related_name="+")

    # Snapshot of the chosen Link — see module docstring. Refreshed in place
    # by tasks._apply_link() on failover to the next-ranked link.
    link_name = models.TextField()
    link_url = models.URLField(max_length=4096)
    link_filename = models.TextField(blank=True)
    link_host = models.CharField(max_length=255, blank=True)
    link_size = models.BigIntegerField(default=0)
    link_source_id = models.CharField(max_length=32, null=True, blank=True)
    # Snapshot of Entry.regions at enqueue — same GC-survival reason as the
    # rest of this block. Ids only ('eu', 'us', ...); the names come from the
    # (tiny, stable) Region table, which the client already fetches.
    region_ids = models.JSONField(default=list, blank=True)
    link_requires_auth = models.BooleanField(default=False)
    link_is_torrent = models.BooleanField(default=False)
    # Only populated when link_is_torrent — Phase 4 scope is magnet-only
    # (the catalog's optional .torrent-file fallback isn't wired up; the
    # only v1 torrent source, MiNERVA, always provides a magnet).
    link_torrent_magnet = models.TextField(blank=True)
    link_torrent_file_index = models.IntegerField(null=True, blank=True)

    # The active qBittorrent torrent hash while link_is_torrent is being
    # downloaded — cleared once finalized (completed or failed over).
    torrent_hash = models.CharField(max_length=40, blank=True)

    # Set while a torrent link has been resolved to a debrid CDN URL —
    # link_is_torrent is temporarily flipped to False so http_download
    # handles it as plain HTTP, while link_torrent_magnet/file_index stay
    # untouched so the task can revert to torrent form on relink/retry
    # (ports DownloadLink.debridResolved's exact "identity preserved"
    # behavior from the Dart model).
    debrid_resolved = models.BooleanField(default=False)
    debrid_relink_attempts = models.IntegerField(default=0)

    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="pending", db_index=True)
    progress = models.FloatField(default=0.0)
    downloaded_bytes = models.BigIntegerField(default=0)
    total_bytes = models.BigIntegerField(default=0)
    bytes_per_second = models.IntegerField(default=0)

    # Relative to STAGED_FILES_DIR/<task.id>/.
    staged_file = models.TextField(blank=True)
    playlist_file = models.TextField(blank=True)
    error = models.TextField(blank=True)
    retry_count = models.IntegerField(default=0)
    failed_urls = models.JSONField(default=list, blank=True)
    celery_task_id = models.CharField(max_length=64, blank=True)

    # Multi-disc group support (playlist_writer.dart's groupId/groupIndex/
    # groupTitle/groupTotal). group_key snapshots EntryGroup.group_key rather
    # than FK'ing it, for the same GC-survival reason as the link_* fields.
    group_key = models.TextField(blank=True)
    group_title = models.TextField(blank=True)
    group_index = models.IntegerField(null=True, blank=True)
    group_total = models.IntegerField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    first_retrieved_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at"]
        constraints = [
            # One task per title per user: downloads.api.enqueue replaces
            # the previous attempt rather than appending a second row, so
            # the downloads page can't accumulate duplicates of a slug.
            models.UniqueConstraint(fields=["user", "slug"], name="download_user_slug_uniq"),
        ]
        indexes = [
            models.Index(fields=["user", "status"], name="download_user_status_idx"),
            models.Index(fields=["status"], name="download_status_idx"),
        ]

    def __str__(self) -> str:
        return f"DownloadTask<{self.pk} {self.slug} {self.status}>"
