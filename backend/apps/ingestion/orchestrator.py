"""
Django-native equivalent of romgi/db/make.py. Shared by the synchronous
management command (apps/ingestion/management/commands/ingest_catalog.py)
and the distributed Celery tasks (apps/ingestion/tasks.py) — both call the
same functions here, matching the plan's "same entry points called
synchronously" design.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Iterable

import yaml

from apps.catalog.models import CatalogBuild

from . import pipeline_path

pipeline_path.ensure()

from core import BuildContext, PlatformConfig, Source, load_registry  # noqa: E402
from grouping import EntryRef, build_groups, load_strategies  # noqa: E402
from parsers import gametdb, libretro, mame, no_intro, retroachievements, wii_rom_set_by_ghostware  # noqa: E402
from utils.scrape_utils import close_browser  # noqa: E402

from .writer import CatalogWriter  # noqa: E402

PIPELINE_ROOT = Path(__file__).resolve().parent / "pipeline"
DEFAULT_PLATFORMS_FILE = PIPELINE_ROOT / "platforms.yml"

PARSERS = {
    "no_intro": no_intro,
    "libretro": libretro,
    "gametdb": gametdb,
    "mame": mame,
    "wii_rom_set_by_ghostware": wii_rom_set_by_ghostware,
}


def load_platforms(file_path: str | Path = DEFAULT_PLATFORMS_FILE) -> dict[str, list[dict[str, Any]]]:
    with open(file_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{file_path} must be a mapping of platform -> list")
    return data


def build_platform_config(entry: dict[str, Any]) -> tuple[str, PlatformConfig]:
    extras = {
        k: v
        for k, v in entry.items()
        if k not in {"source", "format", "regions", "urls", "filter", "type", "parsers"}
    }
    config = PlatformConfig(
        format=entry["format"],
        regions=list(entry.get("regions") or []),
        urls=list(entry.get("urls") or []),
        type=entry.get("type", ""),
        parsers=dict(entry.get("parsers") or {}),
        filter=entry.get("filter"),
        extras=extras,
    )
    return entry["source"], config


def _tag_links(entries_out: list[dict[str, Any]], source: Source) -> tuple[int, int]:
    n_entries = 0
    n_links = 0
    for entry in entries_out:
        n_entries += 1
        for link in entry.get("links", []):
            n_links += 1
            link.setdefault("source_id", source.manifest.id)
            link.setdefault("requires_auth", int(bool(source.manifest.auth_required)))
    return n_entries, n_links


def load_registry_for_pipeline():
    return load_registry(PIPELINE_ROOT)


def scrape_platform_source(
    writer: CatalogWriter,
    registry,
    platform: str,
    platform_entry: dict[str, Any],
    ctx: BuildContext,
) -> tuple[str, int, int]:
    """Scrape -> parser chain -> RA enrichment -> write. Returns
    (source_id, entry_count, link_count) for source_health bookkeeping —
    the unit of work a Celery chord member runs."""
    source_id, config = build_platform_config(platform_entry)

    source = registry.get(source_id)
    if source is None:
        raise LookupError(f"Source '{source_id}' not found in registry.")

    entries_out = source.scrape(platform, config, ctx)

    # Playwright's sync API (used by the mariocube source) runs its driver
    # on this same thread via greenlets, and leaves CPython's per-thread
    # "current running loop" marker pointing at its own loop for as long as
    # the browser stays open. Left uncleared, every Django ORM call made
    # afterwards on this thread trips SynchronousOnlyOperation, since
    # asyncio.get_running_loop() no longer raises — including this same
    # platform's writer.insert_entry() calls below, and every other
    # platform's DB work for the rest of the run. Close right after
    # scraping, before any DB-touching code runs, not just once at the end.
    close_browser()

    for parser_name, parser_flags in config.parsers.items():
        parser = PARSERS.get(parser_name)
        if not parser:
            raise LookupError(f"Parser '{parser_name}' not found.")
        entries_out = parser.parse(entries_out, parser_flags)

    # Runs after the configured parsers so it sees the cleaned title;
    # no-ops for platforms RA doesn't support. See parsers/retroachievements.py.
    entries_out = retroachievements.parse(entries_out, {})

    entries_out = list(entries_out)
    n_entries, n_links = _tag_links(entries_out, source)

    for entry_out in entries_out:
        writer.insert_entry(entry_out)

    return source_id, n_entries, n_links


def run_entry_grouping(writer: CatalogWriter) -> int:
    strategies = load_strategies()
    if not strategies:
        return 0
    entries = writer.fetch_entries_for_grouping()
    groups = build_groups(entries, strategies)
    writer.store_entry_groups(groups)
    return sum(len(g.members) for g in groups)


def iter_platform_source_pairs(
    platforms: dict[str, list[dict[str, Any]]],
    source_filter: Iterable[str] | None = None,
) -> Iterable[tuple[str, dict[str, Any]]]:
    filter_set = set(source_filter) if source_filter else None
    for platform, entries in platforms.items():
        for entry in entries:
            if filter_set is not None and entry.get("source") not in filter_set:
                continue
            yield platform, entry


def run_ingestion_sync(
    build: CatalogBuild,
    *,
    use_cached: bool = False,
    platforms_file: str | Path = DEFAULT_PLATFORMS_FILE,
    source_filter: Iterable[str] | None = None,
    stdout=sys.stdout,
) -> dict[str, dict[str, int]]:
    """Runs the whole pipeline in-process (no Celery/Redis needed) — used by
    `python manage.py ingest_catalog`, mirroring db/make.py's CLI ergonomics."""
    registry = load_registry_for_pipeline()
    platforms = load_platforms(platforms_file)
    writer = CatalogWriter(build)

    for manifest in registry.manifests.values():
        writer.register_source(manifest)

    ctx = BuildContext(use_cached=use_cached)
    source_stats: dict[str, dict[str, int]] = {}

    for platform, platform_entry in iter_platform_source_pairs(platforms, source_filter):
        source_id, config = build_platform_config(platform_entry)
        print(f"  [{platform}] {source_id} ({config.format})...", file=stdout)
        try:
            source_id, n_entries, n_links = scrape_platform_source(
                writer, registry, platform, platform_entry, ctx
            )
        except Exception as exc:  # noqa: BLE001 - one bad source shouldn't kill the run
            print(f"    ERROR: {exc}", file=stdout)
            continue
        stats = source_stats.setdefault(source_id, {"entries": 0, "links": 0})
        stats["entries"] += n_entries
        stats["links"] += n_links

    # Belt-and-suspenders: scrape_platform_source() already closes the
    # browser after each platform's scrape, but close again in case a
    # source scraped without going through that path.
    close_browser()

    grouped = run_entry_grouping(writer)
    print(f"Grouping: {grouped} entries grouped.", file=stdout)

    writer.refresh_search_vectors()

    for source_id in registry.ids():
        stats = source_stats.get(source_id)
        if stats is None:
            writer.record_source_health(source_id, status="unknown", reason="not run in this build")
        else:
            writer.record_source_health(
                source_id, status="ok", entry_count=stats["entries"], link_count=stats["links"]
            )

    return source_stats


def finalize_build(build: CatalogBuild) -> None:
    """Atomically promote `build` to active and retire the previous one —
    the generation-FK equivalent of db_manager.close_database()'s
    temp-file-then-rename swap."""
    from django.db import transaction
    from django.utils import timezone

    with transaction.atomic():
        CatalogBuild.objects.filter(status="active").update(status="retired")
        build.status = "active"
        build.finished_at = timezone.now()
        build.save(update_fields=["status", "finished_at"])


def gc_old_builds(keep: int) -> int:
    """Delete retired builds beyond the retention count. Cascades to their
    Entry/Link/EntryGroup rows via the build FK."""
    retired_ids = list(
        CatalogBuild.objects.filter(status="retired").order_by("-started_at").values_list("id", flat=True)
    )
    to_delete = retired_ids[keep:]
    if not to_delete:
        return 0
    CatalogBuild.objects.filter(id__in=to_delete).delete()
    return len(to_delete)
