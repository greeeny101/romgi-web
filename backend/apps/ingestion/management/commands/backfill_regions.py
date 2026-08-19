"""
Re-derive entry regions from their titles on an already-built catalog.

The region vocabulary grew: Germany/France/Australia/United Kingdom were
folded into 'eu' and now stand on their own, and "(World)" mapped to nothing
at all. New builds pick that up from the pipeline, but a full re-ingest is a
long job and re-slugs entries, which costs a `remap_user_slugs` pass over
everyone's favorites and downloads. This command applies the same mapping to
the live build in place, touching only RegionEntry rows — Entry.slug is left
exactly as it was, so nothing saved is orphaned.

Dry-run by default: it rewrites catalog data, so the change has to be asked
for.

    python manage.py backfill_regions              # report what would change
    python manage.py backfill_regions --apply      # commit it

One thing it cannot recover: no_intro's get_clean_title strips bare
"(Europe)", "(USA)", "(Japan)" and "(World)" groups out of the stored title,
so a title that was once "Sonic (World)" reads "Sonic" here and has nothing
left to parse. Those pick up their region on the next full re-ingest.
"(Germany)", "(France)", "(Australia)" and "(United Kingdom)" are not on that
strip list and do survive in stored titles, which is what makes the four new
country regions backfillable today.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.catalog.models import CatalogBuild, Entry, Region, RegionEntry
from apps.catalog.regions import region_root
from apps.ingestion import pipeline_path

pipeline_path.ensure()

from parsers import region_titles  # noqa: E402


class Command(BaseCommand):
    help = "Re-derive entry regions from their titles on an existing catalog build."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Commit the changes (without this the command only reports).",
        )
        parser.add_argument(
            "--build",
            type=int,
            default=None,
            help="Build id to backfill (default: the active build).",
        )
        parser.add_argument(
            "--limit-examples",
            type=int,
            default=10,
            help="How many example changes to print (default: 10).",
        )

    def handle(self, *args, **options):
        if options["build"] is None:
            build = CatalogBuild.objects.filter(status="active").order_by("-started_at").first()
            if build is None:
                raise CommandError("No active catalog build to backfill.")
        else:
            try:
                build = CatalogBuild.objects.get(pk=options["build"])
            except CatalogBuild.DoesNotExist as exc:
                raise CommandError(f"No such build: {options['build']}") from exc

        known_regions = set(Region.objects.values_list("id", flat=True))

        current: dict[int, set[str]] = {}
        for entry_id, region_id in RegionEntry.objects.filter(entry__build=build).values_list(
            "entry_id", "region_id"
        ):
            current.setdefault(entry_id, set()).add(region_id)

        filled: list[tuple[str, list[str]]] = []
        changed: list[tuple[str, list[str], list[str]]] = []
        disagreed: list[tuple[str, list[str], list[str]]] = []
        unknown: set[str] = set()
        unchanged = 0
        no_title_regions = 0

        stale_entry_ids: list[int] = []
        new_rows: list[RegionEntry] = []

        for entry_id, title in (
            Entry.objects.filter(build=build).values_list("id", "title").iterator(chunk_size=2000)
        ):
            parsed = region_titles.parse_regions(title or "")
            if not parsed:
                # Nothing to say about this entry — leave whatever the
                # scrape config or a source's own metadata assigned it.
                no_title_regions += 1
                continue

            missing = [region for region in parsed if region not in known_regions]
            if missing:
                # Region.id is FK-constrained; a code with no seeded row would
                # blow up the whole transaction. Report and skip instead.
                unknown.update(missing)
                continue

            existing = current.get(entry_id, set())
            if existing == set(parsed):
                unchanged += 1
                continue

            if existing and not all(region_root(region) in existing for region in parsed):
                # The title disagrees with what the entry already has, rather
                # than refining it — "WWE Network (Asia)" is tagged 'jp' from
                # NoPayStation's own Region column, and that CSV knows better
                # than the name does. Only promotions within a group (an 'eu'
                # entry whose title says Germany) are ours to make.
                disagreed.append((title, sorted(existing), parsed))
                continue

            stale_entry_ids.append(entry_id)
            new_rows.extend(RegionEntry(entry_id=entry_id, region_id=region) for region in parsed)

            if existing:
                changed.append((title, sorted(existing), parsed))
            else:
                filled.append((title, parsed))

        with transaction.atomic():
            for start in range(0, len(stale_entry_ids), 2000):
                RegionEntry.objects.filter(entry_id__in=stale_entry_ids[start : start + 2000]).delete()
            RegionEntry.objects.bulk_create(new_rows, batch_size=2000, ignore_conflicts=True)

            if not options["apply"]:
                transaction.set_rollback(True)

        self.stdout.write(f"Build {build.pk}:")
        self.stdout.write(f"  {len(filled)} entrie(s) gained a region")
        self.stdout.write(f"  {len(changed)} entrie(s) had their region changed")
        self.stdout.write(f"  {unchanged} already correct")
        self.stdout.write(f"  {no_title_regions} with no region in the title (left alone)")
        self.stdout.write(f"  {len(disagreed)} where the title contradicts the source (left alone)")

        limit = options["limit_examples"]
        for title, regions in filled[:limit]:
            self.stdout.write(f"    + {title!r} -> {regions}")
        for title, old, new in changed[:limit]:
            self.stdout.write(f"    ~ {title!r}: {old} -> {new}")
        for title, old, new in disagreed[:limit]:
            self.stdout.write(f"    ! {title!r}: kept {old}, title says {new}")

        if unknown:
            self.stdout.write(
                self.style.WARNING(
                    f"  skipped entries mapping to unseeded region id(s): {sorted(unknown)} "
                    "— run migrate first"
                )
            )

        total = len(filled) + len(changed)
        if options["apply"]:
            self.stdout.write(self.style.SUCCESS(f"Updated {total} entrie(s)."))
        else:
            self.stdout.write(
                self.style.WARNING(f"Dry run — {total} entrie(s) would change. Re-run with --apply.")
            )
