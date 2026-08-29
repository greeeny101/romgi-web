from django.apps import AppConfig


class BiosConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.bios"
    label = "bios"

    def ready(self):
        from . import checks  # noqa: F401  (registers the sources.yml system check)
