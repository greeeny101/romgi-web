"""Ports lib/services/metadata/metadata_registry.dart. Both providers are
always registered — "enabled" really means "configured with credentials",
checked per-provider via is_configured(), not a separate on/off switch."""

from .screenscraper import ScreenScraperProvider
from .steamgriddb import SteamGridDbProvider


class MetadataProviderRegistry:
    def __init__(self):
        self._providers = [ScreenScraperProvider(), SteamGridDbProvider()]

    @property
    def available(self):
        return [p.info for p in self._providers]

    def by_id(self, provider_id: str | None):
        for p in self._providers:
            if p.info.id == provider_id:
                return p
        return None

    def __iter__(self):
        return iter(self._providers)


registry = MetadataProviderRegistry()
