"""
Adds the country-level regions (Germany/France/Australia/United Kingdom) and
'world' to the set seeded by 0002.

The four countries used to collapse into 'eu' at parse time; they are their
own regions now, grouped back under Europe when a filter is applied (see
apps.catalog.regions). 'world' covers the "(World)" tag common in arcade
titles, which previously matched nothing and left those entries flagless.

Existing entries keep their old region rows until either a full re-ingest or
`manage.py backfill_regions` — nothing here rewrites RegionEntry, so no
Entry.slug changes and no saved favorite/download is orphaned.
"""

from django.db import migrations

REGIONS = {
    "de": "Germany",
    "fr": "France",
    "au": "Australia",
    "uk": "United Kingdom",
    "world": "World",
}


def seed(apps, schema_editor):
    Region = apps.get_model("catalog", "Region")
    Region.objects.bulk_create(
        [Region(id=rid, name=name) for rid, name in REGIONS.items()],
        ignore_conflicts=True,
    )


def unseed(apps, schema_editor):
    Region = apps.get_model("catalog", "Region")
    Region.objects.filter(id__in=REGIONS.keys()).delete()


class Migration(migrations.Migration):
    dependencies = [("catalog", "0003_sourcehealth_notes_running")]
    operations = [
        migrations.AlterModelOptions(name="region", options={"ordering": ["name"]}),
        migrations.RunPython(seed, unseed),
    ]
