"""
One-off backfill for Link rows written before the MarioCube scraper started
HTML-unescaping hrefs (e.g. "&amp;" left literal instead of "&"), which made
those download URLs 404 against repo.mariocube.com.
"""

import html

from django.core.management.base import BaseCommand

from apps.catalog.models import Link

HOST_NAME = "MarioCube"


class Command(BaseCommand):
    help = "Re-unescape HTML entities in stored MarioCube Link.url values (e.g. '&amp;' -> '&')."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report how many rows would change without writing anything.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        candidates = Link.objects.filter(host=HOST_NAME, url__contains="&amp;")

        changed = []
        for link in candidates.iterator():
            new_url = html.unescape(link.url)
            if new_url != link.url:
                link.url = new_url
                changed.append(link)

        if dry_run:
            self.stdout.write(self.style.WARNING(f"{len(changed)} MarioCube link(s) would be fixed."))
            return

        if changed:
            Link.objects.bulk_update(changed, ["url"], batch_size=500)

        self.stdout.write(self.style.SUCCESS(f"Fixed {len(changed)} MarioCube link(s)."))
