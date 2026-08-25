"""
Whole-archive.org-item downloads ("ROM sets"), kept deliberately separate
from apps.downloads.DownloadTask.

DownloadTask is built on invariants a set contradicts at every point: one
file per task (`staged_file` is a single path), one task per (user, slug),
and a stage-then-claim-then-expire lifecycle ending at an endpoint that
serves exactly one file. A set is N files, identified by an archive.org
identifier rather than a catalog slug, and is delivered by landing in a
server-side library folder that nothing ever claims or expires. Bending
DownloadTask to cover both would have put the working single-ROM path at
risk for no gain.

What the two DO share is one qBittorrent daemon and therefore one infohash
space — see apps.torrents.ownership for the guard that keeps them from
deleting each other's torrents.
"""

from django.conf import settings
from django.db import models

from apps.common.models import TimeStampedModel

# A set holds its torrent while paused, unlike a paused DownloadTask which
# deliberately releases it — see apps.torrents.ownership.torrent_in_use.
ACTIVE_STATUSES = ("pending", "fetching_metadata", "downloading", "paused", "extracting")


class RomSetDownload(TimeStampedModel):
    STATUS_CHOICES = [
        ("pending", "pending"),
        ("fetching_metadata", "fetching_metadata"),
        ("downloading", "downloading"),
        ("paused", "paused"),
        ("extracting", "extracting"),
        ("completed", "completed"),
        ("failed", "failed"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="rom_sets")
    provider = models.CharField(max_length=32, default="internet_archive")
    identifier = models.CharField(max_length=255, db_index=True)
    title = models.TextField()
    # Static reference data, so a hard FK is right here — same reasoning as
    # library.Favorite.platform. Null means "unsorted": a set that isn't tied
    # to one platform (a No-Intro multi-console dump) still has to land
    # somewhere.
    platform = models.ForeignKey("catalog.Platform", on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    emulator_id = models.CharField(max_length=32, blank=True)

    infohash = models.CharField(max_length=40, blank=True, db_index=True)
    # Relative to ROM_LIBRARY_DIR — the same relative path resolves under
    # QBITTORRENT_LIBRARY_PATH inside the qBittorrent container.
    save_dir = models.TextField(blank=True)

    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default="pending")
    total_bytes = models.BigIntegerField(default=0)
    downloaded_bytes = models.BigIntegerField(default=0)
    progress = models.FloatField(default=0.0)
    bytes_per_second = models.IntegerField(default=0)

    extract = models.BooleanField(default=False)
    error = models.TextField(blank=True)
    celery_task_id = models.CharField(max_length=255, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            # One row per user per item: re-requesting a set replaces the
            # previous attempt rather than stacking a second copy, matching
            # how DownloadTask treats a re-requested slug.
            models.UniqueConstraint(fields=["user", "identifier"], name="romset_user_identifier_uniq"),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.identifier} ({self.status})"


class RomSetFile(models.Model):
    """One file inside the set's torrent.

    `path` is the path as it appears in the *torrent*, without the root
    directory qBittorrent prefixes onto it. Three different file lists exist
    for any archive.org item — the metadata API's, the torrent's, and
    qBittorrent's pad-filtered view — and they do not agree on membership or
    ordering, so this table is populated from the torrent and matched to
    qBittorrent by name. Never by index.
    """

    romset = models.ForeignKey(RomSetDownload, on_delete=models.CASCADE, related_name="files")
    path = models.TextField()
    size = models.BigIntegerField(default=0)
    wanted = models.BooleanField(default=True)
    progress = models.FloatField(default=0.0)
    done = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["romset", "path"], name="romsetfile_path_uniq"),
        ]
        ordering = ["path"]

    def __str__(self) -> str:
        return self.path
