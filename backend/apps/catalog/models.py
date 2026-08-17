"""
Mirrors the schema owned by romgi/db/database/db_manager.py (SQLite,
SCHEMA_VERSION=4). See the porting reference map in the plan for the exact
table -> model mapping. Postgres full-text search (search_vector + GIN
index) replaces the SQLite entries_fts FTS4 shadow table.

This app is read-mostly: only apps.ingestion writes to these tables.
"""

from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models


class CatalogBuild(models.Model):
    """
    One ingestion run. Entries/Links/Torrents/EntryGroups from a run are
    tagged with its FK and never mutate a previously-active build's rows —
    see the "generation-tagged writes" design in the plan (replaces the
    SQLite romdb_temp.db -> rename swap).
    """

    STATUS_CHOICES = [
        ("running", "running"),
        ("active", "active"),
        ("retired", "retired"),
        ("failed", "failed"),
    ]

    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="running", db_index=True)
    source_stats = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self) -> str:
        return f"CatalogBuild<{self.pk} {self.status}>"


class Platform(models.Model):
    id = models.CharField(primary_key=True, max_length=16)  # 'nes', 'ps1', ...
    brand = models.CharField(max_length=64)
    name = models.CharField(max_length=128)

    class Meta:
        ordering = ["brand", "name"]

    def __str__(self) -> str:
        return self.name


class Region(models.Model):
    id = models.CharField(primary_key=True, max_length=16)  # 'eu', 'us', 'jp', 'other'
    name = models.CharField(max_length=32)

    def __str__(self) -> str:
        return self.name


class Source(models.Model):
    KIND_CHOICES = [("catalog", "catalog"), ("host", "host"), ("hybrid", "hybrid")]

    id = models.CharField(primary_key=True, max_length=32)  # 'minerva', 'internet_archive', ...
    name = models.CharField(max_length=128)
    homepage = models.URLField(null=True, blank=True)
    kind = models.CharField(max_length=16, choices=KIND_CHOICES)
    auth_required = models.BooleanField(default=False)
    priority = models.IntegerField(default=0)
    manifest = models.JSONField(default=dict, blank=True)  # raw source.yml, round-tripped

    class Meta:
        ordering = ["-priority"]

    def __str__(self) -> str:
        return self.name


class SourceHealth(models.Model):
    STATUS_CHOICES = [("ok", "ok"), ("error", "error"), ("unknown", "unknown"), ("running", "running")]

    source = models.OneToOneField(Source, primary_key=True, on_delete=models.CASCADE, related_name="health")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="unknown")
    last_checked_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(null=True, blank=True)
    entry_count = models.IntegerField(default=0)
    link_count = models.IntegerField(default=0)

    def __str__(self) -> str:
        return f"SourceHealth<{self.source_id} {self.status}>"


class Entry(models.Model):
    # Surrogate PK, not `slug` — under generation-tagged writes, the *same*
    # real-world slug legitimately exists in multiple CatalogBuild rows at
    # once (the pending build being ingested alongside the still-active
    # previous one), so slug can only be unique *per build*, not globally.
    # (Discovered the hard way: a second ingestion run against a non-empty
    # table raised IntegrityError on the old slug-as-PK design.)
    id = models.BigAutoField(primary_key=True)
    # Derived from title (see create_slug() in the vendored pipeline) — a
    # long/garbage-heavy scraped title produces a long slug, so this is
    # TEXT rather than a bounded varchar; see the Link.name note above.
    slug = models.TextField(db_index=True)
    build = models.ForeignKey(CatalogBuild, on_delete=models.CASCADE, related_name="entries")
    rom_id = models.CharField(max_length=64, null=True, blank=True)
    # Scraped/parsed titles are not reliably boundable (source HTML/filename
    # garbage can slip through) — TEXT here matches the original SQLite
    # schema's unconstrained columns rather than risking ingestion crashes.
    title = models.TextField(db_index=True)
    search_vector = SearchVectorField(null=True, blank=True)
    platform = models.ForeignKey(Platform, on_delete=models.PROTECT, related_name="entries")
    regions = models.ManyToManyField(Region, through="RegionEntry", related_name="entries")
    # Widened from URLField's default max_length=200 — libretro/gametdb
    # boxart URLs (long title + path segments, percent-encoded) exceed it.
    boxart_url = models.URLField(max_length=2048, null=True, blank=True)
    ra_game_id = models.IntegerField(null=True, blank=True)
    ra_num_achievements = models.IntegerField(null=True, blank=True)

    class Meta:
        verbose_name_plural = "entries"
        constraints = [
            models.UniqueConstraint(fields=["slug", "build"], name="unique_entry_slug_per_build"),
        ]
        indexes = [
            GinIndex(fields=["search_vector"], name="entry_search_vector_gin"),
            models.Index(fields=["platform"], name="entry_platform_idx"),
            models.Index(fields=["build"], name="entry_build_idx"),
        ]

    def __str__(self) -> str:
        return self.title


class RegionEntry(models.Model):
    entry = models.ForeignKey(Entry, on_delete=models.CASCADE)
    region = models.ForeignKey(Region, on_delete=models.CASCADE)

    class Meta:
        indexes = [
            models.Index(fields=["entry"], name="region_entry_entry_idx"),
            models.Index(fields=["region"], name="region_entry_region_idx"),
        ]
        constraints = [
            models.UniqueConstraint(fields=["entry", "region"], name="unique_region_entry"),
        ]


class Torrent(models.Model):
    infohash = models.CharField(primary_key=True, max_length=40)
    source = models.ForeignKey(Source, on_delete=models.CASCADE, related_name="torrents")
    name = models.CharField(max_length=512, null=True, blank=True)
    magnet = models.TextField(null=True, blank=True)
    torrent_file = models.FileField(upload_to="torrents/", null=True, blank=True)
    total_size = models.BigIntegerField(null=True, blank=True)
    piece_length = models.IntegerField(null=True, blank=True)
    file_count = models.IntegerField(null=True, blank=True)
    trackers = models.JSONField(null=True, blank=True)
    added_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.name or self.infohash


class Link(models.Model):
    entry = models.ForeignKey(Entry, on_delete=models.CASCADE, related_name="links")
    # name/filename/url are scraper output, not reliably boundable (see
    # Entry.title) — TEXT/generous URLField instead of a tight varchar.
    name = models.TextField()
    type = models.CharField(max_length=32, blank=True)
    format = models.CharField(max_length=16, blank=True)
    url = models.URLField(max_length=4096)
    filename = models.TextField(blank=True)
    host = models.CharField(max_length=255, blank=True)
    size = models.BigIntegerField(default=0)
    size_str = models.CharField(max_length=32, blank=True)
    source_url = models.URLField(max_length=4096, null=True, blank=True)
    source = models.ForeignKey(Source, on_delete=models.SET_NULL, null=True, related_name="links")
    requires_auth = models.BooleanField(default=False)
    torrent = models.ForeignKey(
        Torrent, on_delete=models.SET_NULL, null=True, blank=True, related_name="links"
    )
    torrent_file_index = models.IntegerField(null=True, blank=True)
    torrent_file_path = models.TextField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["entry"], name="link_entry_idx"),
            models.Index(fields=["source"], name="link_source_idx"),
            models.Index(fields=["torrent"], name="link_torrent_idx"),
        ]

    def __str__(self) -> str:
        return self.name


class EntryGroup(models.Model):
    """Multi-disc sets today; `kind` leaves room for future strategies."""

    # Surrogate PK — same generation-tagging reasoning as Entry.id above.
    id = models.BigAutoField(primary_key=True)
    # f"{kind}:{key}" where key is itself a title-derived slug — unique per
    # build (see `constraints` below), not globally.
    group_key = models.TextField()
    build = models.ForeignKey(CatalogBuild, on_delete=models.CASCADE, related_name="entry_groups")
    kind = models.CharField(max_length=32, db_index=True)
    title = models.TextField(null=True, blank=True)
    platform = models.ForeignKey(Platform, on_delete=models.CASCADE, related_name="entry_groups")
    member_count = models.IntegerField()
    metadata = models.JSONField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["group_key", "build"], name="unique_entry_group_key_per_build"),
        ]

    def __str__(self) -> str:
        return self.title or self.group_key


class EntryGroupMember(models.Model):
    group = models.ForeignKey(EntryGroup, on_delete=models.CASCADE, related_name="members")
    entry = models.ForeignKey(Entry, on_delete=models.CASCADE, related_name="group_memberships")
    member_index = models.IntegerField(null=True, blank=True)
    member_label = models.CharField(max_length=64, null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["group", "entry"], name="unique_group_member"),
        ]
        ordering = ["member_index"]
