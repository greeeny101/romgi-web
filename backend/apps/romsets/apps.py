from django.apps import AppConfig


class RomsetsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.romsets"
    label = "romsets"

    def ready(self):
        from . import checks  # noqa: F401  (registers the emulators.yml system check)
