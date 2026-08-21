"""
Django ORM equivalent of romgi/db/database/db_manager.py's write path
(insert_entry / register_torrent / register_source / record_source_health /
store_entry_groups), scoped to one CatalogBuild instead of a fresh SQLite
file. See the "generation-tagged writes" design in the plan.
"""

from __future__ import annotations

from typing import Any

from django.contrib.postgres.search import SearchVector
from django.db import transaction
from django.utils import timezone

from apps.catalog.models import (
    CatalogBuild,
    Entry,
    EntryGroup,
    EntryGroupMember,
    Link,
    RegionEntry,
    Source,
    SourceHealth,
    Torrent,
)

from . import pipeline_path
from . import progress as ingestion_progress

pipeline_path.ensure()

from utils.parse_utils import create_slug  # noqa: E402  (vendored pipeline)


class CatalogWriter:
    """One instance per ingestion run, bound to the pending CatalogBuild."""

    def __init__(self, build: CatalogBuild):
        self.build = build

    # -- sources / health --------------------------------------------------

    def register_source(self, manifest) -> None:
        Source.objects.update_or_create(
            id=manifest.id,
            defaults=dict(
                name=manifest.name,
                homepage=manifest.homepage,
                kind=manifest.kind,
                auth_required=manifest.auth_required,
                priority=manifest.priority,
                manifest=manifest.raw,
            ),
        )

    def _update_health(self, source_id: str, defaults: dict[str, Any]) -> None:
        """Single choke point for every SourceHealth write: persists the
        row, then broadcasts it. Omitting entry_count/link_count from
        `defaults` (as record_source_progress does) leaves those columns
        untouched on an existing row, since update_or_create only sets keys
        present in `defaults`."""
        obj, _ = SourceHealth.objects.update_or_create(source_id=source_id, defaults=defaults)
        ingestion_progress.push_source_health(obj)

    def record_source_progress(self, source_id: str, *, notes: str, status: str = "running") -> None:
        """Live, per-(platform, source)-pair update — called many times
        across a run. Never touches entry_count/link_count."""
        self._update_health(source_id, dict(status=status, notes=notes, last_checked_at=timezone.now()))

    def record_source_health(
        self,
        source_id: str,
        status: str,
        *,
        notes: str | None = None,
        entry_count: int = 0,
        link_count: int = 0,
    ) -> None:
        self._update_health(
            source_id,
            dict(
                status=status,
                last_checked_at=timezone.now(),
                notes=notes,
                entry_count=entry_count,
                link_count=link_count,
            ),
        )

    # -- torrents ------------------------------------------------------------

    def register_torrent(
        self,
        *,
        infohash: str,
        source_id: str,
        name: str | None = None,
        magnet: str | None = None,
        total_size: int | None = None,
        piece_length: int | None = None,
        file_count: int | None = None,
        trackers: list[str] | None = None,
        **_ignored: Any,
    ) -> Torrent:
        torrent, _ = Torrent.objects.get_or_create(
            infohash=infohash.lower(),
            defaults=dict(
                source_id=source_id,
                name=name,
                magnet=magnet,
                total_size=total_size,
                piece_length=piece_length,
                file_count=file_count,
                trackers=trackers,
            ),
        )
        return torrent

    # -- entries / links -------------------------------------------------------

    @transaction.atomic
    def insert_entry(self, entry: dict[str, Any]) -> None:
        """Insert or, within this build, COALESCE-merge an entry — same
        semantics as db_manager.insert_entry, scoped to self.build instead
        of "the whole (single) database"."""
        slug = create_slug(entry)
        entry["slug"] = slug

        obj, created = Entry.objects.get_or_create(
            slug=slug,
            build=self.build,
            defaults=dict(
                rom_id=entry.get("rom_id"),
                title=entry.get("title") or "",
                platform_id=entry.get("platform"),
                boxart_url=entry.get("boxart_url"),
                ra_game_id=entry.get("ra_game_id"),
                ra_num_achievements=entry.get("ra_num_achievements"),
            ),
        )

        if not created:
            dirty = False
            for field in ("rom_id", "boxart_url", "ra_game_id", "ra_num_achievements"):
                if getattr(obj, field) is None and entry.get(field) is not None:
                    setattr(obj, field, entry[field])
                    dirty = True
            if dirty:
                obj.save(update_fields=["rom_id", "boxart_url", "ra_game_id", "ra_num_achievements"])

        if created:
            for region_id in entry.get("regions", []):
                RegionEntry.objects.get_or_create(entry=obj, region_id=region_id)

        for link in entry.get("links", []):
            self._insert_link(obj, link)

    def _insert_link(self, entry: Entry, link: dict[str, Any]) -> None:
        torrent = None
        meta = link.get("_torrent_meta")
        if meta is not None:
            torrent = self.register_torrent(**meta)
        elif link.get("torrent_infohash"):
            torrent = Torrent.objects.filter(infohash=link["torrent_infohash"].lower()).first()

        Link.objects.create(
            entry=entry,
            name=link.get("name") or "",
            type=link.get("type") or "",
            format=link.get("format") or "",
            url=link.get("url") or "",
            filename=link.get("filename") or "",
            host=link.get("host") or "",
            size=link.get("size") or 0,
            size_str=link.get("size_str") or "",
            source_url=link.get("source_url"),
            source_id=link.get("source_id"),
            requires_auth=bool(link.get("requires_auth")),
            torrent=torrent,
            torrent_file_index=link.get("torrent_file_index"),
            torrent_file_path=link.get("torrent_file_path"),
        )

    # -- grouping --------------------------------------------------------------

    def fetch_entries_for_grouping(self):
        from grouping.base import EntryRef  # vendored pipeline

        # Keyed by Entry.id (the surrogate PK), not slug — slug is only
        # unique per build now, not globally, so it can't key a dict safely
        # across the whole table. EntryRef itself still carries `slug` as
        # the portable identifier the grouping strategies operate on.
        region_map: dict[int, set[str]] = {}
        for entry_id, region_id in RegionEntry.objects.filter(
            entry__build=self.build
        ).values_list("entry_id", "region_id"):
            region_map.setdefault(entry_id, set()).add(region_id)

        out = []
        for entry_id, slug, title, platform_id in Entry.objects.filter(build=self.build).values_list(
            "id", "slug", "title", "platform_id"
        ):
            out.append(
                EntryRef(
                    slug=slug,
                    title=title,
                    platform=platform_id,
                    regions=tuple(sorted(region_map.get(entry_id, ()))),
                )
            )
        return out

    def store_entry_groups(self, groups) -> None:
        # slug is only unique per build, so resolve each member's Entry PK
        # via a single (slug -> id) map for this build rather than a
        # per-member query.
        slug_to_id = dict(Entry.objects.filter(build=self.build).values_list("slug", "id"))

        for group in groups:
            eg, _ = EntryGroup.objects.update_or_create(
                group_key=group.id,
                build=self.build,
                defaults=dict(
                    kind=group.kind,
                    title=group.title,
                    platform_id=group.platform,
                    member_count=len(group.members),
                    metadata=group.metadata or None,
                ),
            )
            for member in group.members:
                entry_pk = slug_to_id.get(member.slug)
                if entry_pk is None:
                    continue
                EntryGroupMember.objects.get_or_create(
                    group=eg,
                    entry_id=entry_pk,
                    defaults=dict(member_index=member.index, member_label=member.label),
                )

    # -- finalize --------------------------------------------------------------

    def refresh_search_vectors(self) -> None:
        """Bulk-populate Postgres FTS — the equivalent of the SQLite
        entries_fts shadow table, done once at the end rather than per-row.

        'simple', not the default 'english': game titles are proper nouns, so
        stemming buys nothing and costs a lot. It also lets the catalog API
        match on prefixes as the user types (see catalog.api._search_query) —
        stemmed lexemes can't be prefix-matched reliably, because a
        half-typed word stems to something that isn't a prefix of the stored
        stem. Stop words matter too: 'english' drops them, which would make
        "The Simpsons" unfindable by "the"."""
        Entry.objects.filter(build=self.build).update(
            search_vector=SearchVector("title", config="simple")
        )
