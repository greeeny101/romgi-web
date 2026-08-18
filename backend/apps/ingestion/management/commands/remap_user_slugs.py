"""
Repoint saved favorites, recently-viewed and downloads at their renamed
catalog entries after a rebuild. See apps.ingestion.slug_remap for why this
is a command rather than a data migration.

Dry-run by default: it touches user data, so the change has to be asked for.

    python manage.py remap_user_slugs              # report what would change
    python manage.py remap_user_slugs --apply      # commit it
"""

from django.core.management.base import BaseCommand, CommandError

from apps.catalog.models import CatalogBuild
from apps.ingestion import slug_remap


class Command(BaseCommand):
    help = "Remap saved user rows onto renamed catalog slugs after a rebuild."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Commit the changes (without this the command only reports).",
        )
        parser.add_argument(
            "--to-build",
            type=int,
            default=None,
            help="Build id to remap onto (default: the active build).",
        )
        parser.add_argument(
            "--from-build",
            type=int,
            default=None,
            help="Build id to remap from (default: the most recent retired build).",
        )

    def _build(self, build_id: int | None, label: str) -> CatalogBuild | None:
        if build_id is None:
            return None
        try:
            return CatalogBuild.objects.get(pk=build_id)
        except CatalogBuild.DoesNotExist as exc:
            raise CommandError(f"No such {label} build: {build_id}") from exc

    def handle(self, *args, **options):
        report = slug_remap.remap(
            to_build=self._build(options["to_build"], "target"),
            from_build=self._build(options["from_build"], "source"),
            commit=options["apply"],
        )

        if report.to_build is None:
            raise CommandError("No active catalog build to remap onto.")
        if report.from_build is None:
            raise CommandError("No retired build to remap from — nothing to compare against.")

        self.stdout.write(f"Build {report.from_build} -> {report.to_build}: {report.mapped_slugs} renamed slugs")
        for label, count in sorted(report.updated.items()):
            self.stdout.write(f"  {label}: {count} row(s)")
        for note in report.skipped:
            self.stdout.write(self.style.WARNING(f"  skipped {note}"))
        for note in report.orphaned:
            self.stdout.write(self.style.WARNING(f"  orphaned {note}"))

        if options["apply"]:
            self.stdout.write(self.style.SUCCESS(f"Updated {report.total_updated} row(s)."))
        else:
            self.stdout.write(
                self.style.WARNING(f"Dry run — {report.total_updated} row(s) would change. Re-run with --apply.")
            )
