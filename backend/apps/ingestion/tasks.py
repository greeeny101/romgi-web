"""
Celery equivalent of the weekly GitHub Actions cron
(.github/workflows/generate-database.yml) that used to rebuild
db/romdb.db.gz and commit it back to the repo. Same pipeline as
apps.ingestion.orchestrator / the `ingest_catalog` management command,
fanned out across workers via a chord instead of running in one process.
"""

from __future__ import annotations

from celery import chord, shared_task
from django.conf import settings

from apps.catalog.models import CatalogBuild

from . import orchestrator
from .writer import CatalogWriter


@shared_task
def run_full_ingestion(source_filter: list[str] | None = None, use_cached: bool = False) -> int:
    """Beat entry point, weekly. Creates the pending build and fans out one
    `scrape_source_platform` task per (platform, source) pair from
    platforms.yml, with `_after_ingestion` as the chord callback."""
    build = CatalogBuild.objects.create(status="running")

    registry = orchestrator.load_registry_for_pipeline()
    writer = CatalogWriter(build)
    for manifest in registry.manifests.values():
        writer.register_source(manifest)

    platforms = orchestrator.load_platforms()
    work = list(orchestrator.iter_platform_source_pairs(platforms, source_filter))

    header = [
        scrape_source_platform.s(build.pk, platform, platform_entry, use_cached)
        for platform, platform_entry in work
    ]
    chord(header)(_after_ingestion.s(build.pk))
    return build.pk


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def scrape_source_platform(self, build_id: int, platform: str, platform_entry: dict, use_cached: bool):
    """One chord member: scrape -> parse chain -> RA enrichment -> write,
    for a single (platform, source) pair."""
    from core import BuildContext  # vendored pipeline

    build = CatalogBuild.objects.get(pk=build_id)
    writer = CatalogWriter(build)
    registry = orchestrator.load_registry_for_pipeline()
    ctx = BuildContext(use_cached=use_cached)

    source_id, n_entries, n_links = orchestrator.scrape_platform_source_with_progress(
        writer, registry, platform, platform_entry, ctx
    )
    return {"source_id": source_id, "entries": n_entries, "links": n_links}


@shared_task
def _after_ingestion(results: list[dict], build_id: int) -> None:
    """Chord callback: aggregate per-source stats, run grouping, refresh
    search vectors, record health for every registered source, finalize."""
    build = CatalogBuild.objects.get(pk=build_id)
    writer = CatalogWriter(build)

    source_stats: dict[str, dict[str, int]] = {}
    for result in results:
        if not result:
            continue
        stats = source_stats.setdefault(result["source_id"], {"entries": 0, "links": 0})
        stats["entries"] += result["entries"]
        stats["links"] += result["links"]

    run_entry_grouping.run(build_id)
    writer.refresh_search_vectors()

    registry = orchestrator.load_registry_for_pipeline()
    for source_id in registry.ids():
        stats = source_stats.get(source_id)
        if stats is None:
            writer.record_source_health(source_id, status="unknown", notes="not run in this build")
        else:
            writer.record_source_health(
                source_id,
                status="ok",
                notes=f"Completed: {stats['entries']} entries, {stats['links']} links",
                entry_count=stats["entries"],
                link_count=stats["links"],
            )

    finalize_catalog_build.run(build_id)


@shared_task
def run_entry_grouping(build_id: int) -> int:
    build = CatalogBuild.objects.get(pk=build_id)
    writer = CatalogWriter(build)
    return orchestrator.run_entry_grouping(writer)


@shared_task
def finalize_catalog_build(build_id: int) -> None:
    build = CatalogBuild.objects.get(pk=build_id)
    orchestrator.finalize_build(build)


@shared_task
def gc_old_builds() -> int:
    return orchestrator.gc_old_builds(keep=settings.CATALOG_BUILD_RETENTION)


@shared_task
def run_single_source(source_id: str) -> int:
    """Manual per-source re-run, triggered from the Sources page's "Run"
    button (apps.ingestion.api.run_source). Unlike run_full_ingestion,
    this must not wipe out every other source's catalog data — see
    orchestrator.carry_forward_other_sources."""
    build = CatalogBuild.objects.create(status="running")
    try:
        orchestrator.run_single_source_sync(build, source_id)
    except Exception:
        build.status = "failed"
        build.save(update_fields=["status"])
        raise
    orchestrator.finalize_build(build)
    return build.pk
