"""
Run the catalog ingestion pipeline synchronously, without Celery/Redis —
the local-dev equivalent of `cd db && python workflow.py` /
`python make.py --sources ... --platforms ...` in the original repo.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.catalog.models import CatalogBuild
from apps.ingestion.orchestrator import (
    DEFAULT_PLATFORMS_FILE,
    finalize_build,
    run_ingestion_sync,
)


class Command(BaseCommand):
    help = "Scrape all configured sources and (re)build the catalog into a new CatalogBuild."

    def add_arguments(self, parser):
        parser.add_argument(
            "--sources",
            "--scrapers",
            dest="sources",
            default=None,
            help="Comma-separated source ids to run (default: all).",
        )
        parser.add_argument(
            "--platforms",
            dest="platforms_file",
            default=str(DEFAULT_PLATFORMS_FILE),
            help="Path to platforms.yml (default: the vendored pipeline's copy).",
        )
        parser.add_argument("--use-cached", action="store_true", help="Reuse cached HTTP responses.")
        parser.add_argument(
            "--no-activate",
            action="store_true",
            help="Leave the build in 'running' status instead of flipping it active "
            "(useful for inspecting a test run before it goes live).",
        )

    def handle(self, *args, **options):
        source_filter = None
        if options["sources"]:
            source_filter = [s.strip() for s in options["sources"].split(",") if s.strip()]

        build = CatalogBuild.objects.create(status="running")
        self.stdout.write(f"Started CatalogBuild #{build.pk}")

        try:
            stats = run_ingestion_sync(
                build,
                use_cached=options["use_cached"],
                platforms_file=options["platforms_file"],
                source_filter=source_filter,
                stdout=self.stdout,
            )
        except Exception as exc:
            build.status = "failed"
            build.save(update_fields=["status"])
            raise CommandError(f"Ingestion failed: {exc}") from exc

        if options["no_activate"]:
            self.stdout.write(self.style.WARNING(f"Build #{build.pk} left as 'running' (--no-activate)."))
        else:
            finalize_build(build)
            self.stdout.write(self.style.SUCCESS(f"Build #{build.pk} is now active."))

        for source_id, s in stats.items():
            self.stdout.write(f"  {source_id}: {s['entries']} entries, {s['links']} links")
