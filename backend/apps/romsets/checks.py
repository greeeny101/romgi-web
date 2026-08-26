"""
System check that every `platform_id` in emulators.yml is a real
catalog.Platform PK.

A typo there would otherwise surface as an IntegrityError partway through
starting a download — after the user picked files and passed the space
check. Registered under the database tag so it runs on `manage.py check
--database default` and `migrate`, and stays silent when no DB is reachable.
"""

from django.core.checks import Error, Tags, register

from .emulators import load_emulators


@register(Tags.database)
def check_emulator_platforms(app_configs, databases=None, **kwargs):
    if not databases:
        return []

    from apps.catalog.models import Platform

    known = set(Platform.objects.values_list("id", flat=True))
    if not known:  # platforms are seeded by migration; nothing to check against yet
        return []

    return [
        Error(
            f"emulators.yml entry '{emulator.id}' names unknown platform_id '{emulator.platform_id}'.",
            hint="platform_id must be a catalog.Platform primary key (e.g. 'fbneo', 'mame'), or null.",
            id="romsets.E001",
        )
        for emulator in load_emulators()
        if emulator.platform_id and emulator.platform_id not in known
    ]
