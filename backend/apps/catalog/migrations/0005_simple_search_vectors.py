"""Rebuild Entry.search_vector with the 'simple' text search config.

The vectors were built with the default 'english' config, which stems every
lexeme. That made the catalog search whole-word only — typing "c" produced
the lexeme 'c' and matched a "(Rev C)" tag rather than "Crazy Taxi" — and it
blocked the prefix matching the search box needs, since a half-typed word
stems to something that is not a prefix of the stored stem.

Rebuilt per build rather than in one statement: the table holds every
generation ever ingested (~1M rows across builds), and one UPDATE of that
size holds a lock on the table the live API is reading from for the whole
run. atomic=False so each build's UPDATE commits on its own.
"""

from django.contrib.postgres.search import SearchVector
from django.db import migrations


def _rebuild(apps, config):
    Entry = apps.get_model("catalog", "Entry")
    CatalogBuild = apps.get_model("catalog", "CatalogBuild")
    for build_id in CatalogBuild.objects.values_list("id", flat=True):
        Entry.objects.filter(build_id=build_id).update(
            search_vector=SearchVector("title", config=config)
        )


def to_simple(apps, schema_editor):
    _rebuild(apps, "simple")


def to_english(apps, schema_editor):
    _rebuild(apps, "english")


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("catalog", "0004_seed_country_regions"),
    ]

    operations = [
        migrations.RunPython(to_simple, to_english),
    ]
