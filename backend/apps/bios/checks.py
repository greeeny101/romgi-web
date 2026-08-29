"""
System check that every `platform_id` in sources.yml is a real
catalog.Platform PK.

A typo there would otherwise surface as an IntegrityError partway through
starting a download — after the user picked files. Registered under the
database tag so it runs on `manage.py check --database default` and
`migrate`, and stays silent when no DB is reachable.
"""

from django.core.checks import Error, Tags, register

from .sources import load_sources


@register(Tags.database)
def check_bios_source_platforms(app_configs, databases=None, **kwargs):
    if not databases:
        return []

    from apps.catalog.models import Platform

    known = set(Platform.objects.values_list("id", flat=True))
    if not known:  # platforms are seeded by migration; nothing to check against yet
        return []

    return [
        Error(
            f"sources.yml entry '{source.id}' names unknown platform_id '{source.platform_id}'.",
            hint="platform_id must be a catalog.Platform primary key (e.g. 'ps1', 'sat'), or null.",
            id="bios.E001",
        )
        for source in load_sources()
        if source.platform_id and source.platform_id not in known
    ]
