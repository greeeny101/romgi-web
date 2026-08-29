"""
BIOS/firmware downloads out of archive.org items, taken file-by-file over
plain HTTP.

Kept separate from apps.downloads.DownloadTask for the same reason
apps.romsets is (see that module's docstring): DownloadTask is one file per
task, keyed to a catalog slug, on a stage-then-claim-then-expire lifecycle
ending at an endpoint that serves exactly one file. A BIOS request is N
files, keyed by an archive.org identifier, landing in a server-side library
folder that nothing ever claims or expires.

Kept separate from apps.romsets despite the near-identical shape because the
transfer is genuinely a different mechanism: a set is a torrent handed to
qBittorrent, which owns the bytes out-of-process and needs polling,
infohash ownership arbitration and a carry-forward rule to stop deselection
deleting data. A BIOS file is a few hundred kilobytes fetched with an HTTP
GET the worker itself performs. Sharing a model would mean carrying every
one of those torrent concerns as dead weight on rows that can never have an
infohash.
"""

from django.conf import settings
from django.db import models

from apps.common.models import TimeStampedModel

ACTIVE_STATUSES = ("pending", "fetching_metadata", "downloading", "paused", "extracting")


class BiosDownload(TimeStampedModel):
    STATUS_CHOICES = [
        ("pending", "pending"),
        ("fetching_metadata", "fetching_metadata"),
        ("downloading", "downloading"),
        ("paused", "paused"),
        ("extracting", "extracting"),
        ("completed", "completed"),
        ("failed", "failed"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="bios_downloads")
    provider = models.CharField(max_length=32, default="internet_archive")
    identifier = models.CharField(max_length=255, db_index=True)
    title = models.TextField()
    # Static reference data, so a hard FK is right here — same reasoning as
    # romsets.RomSetDownload.platform. Null means "unsorted": the
    # multi-system BIOS packs aren't tied to one platform and still have to
    # land somewhere.
    platform = models.ForeignKey("catalog.Platform", on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    source_id = models.CharField(max_length=32, blank=True)

    # Relative to ROM_LIBRARY_DIR — "bios/<platform>/", or "bios/_unsorted/".
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
            # One row per user per item: re-requesting an item replaces the
            # previous attempt rather than stacking a second copy.
            models.UniqueConstraint(fields=["user", "identifier"], name="bios_user_identifier_uniq"),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.identifier} ({self.status})"


class BiosFile(models.Model):
    """One file inside the archive.org item.

    `name` is the name as the *metadata API* reports it, which is also the
    path segment `/download/<identifier>/<name>` needs — unlike romsets,
    where the list has to come from the torrent, here the metadata list is
    exactly the downloadable set, so there is only one file list in play.

    `md5` is archive.org's published checksum, carried on the row so the
    worker can verify a file without re-fetching the metadata payload.
    """

    bios = models.ForeignKey(BiosDownload, on_delete=models.CASCADE, related_name="files")
    name = models.TextField()
    size = models.BigIntegerField(default=0)
    md5 = models.CharField(max_length=32, blank=True)
    wanted = models.BooleanField(default=True)
    progress = models.FloatField(default=0.0)
    done = models.BooleanField(default=False)
    error = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["bios", "name"], name="biosfile_name_uniq"),
        ]
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name
