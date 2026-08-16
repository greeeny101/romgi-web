"""Ports lib/services/debrid/debrid_registry.dart. Adding a new provider is
a one-line change here; no other pipeline code needs editing."""

from .realdebrid import RealDebridProvider
from .torbox import TorboxProvider


class DebridProviderRegistry:
    def __init__(self):
        # TorBox first — matches Dart's default provider order.
        self._providers = [TorboxProvider(), RealDebridProvider()]

    @property
    def available(self):
        return [p.info for p in self._providers]

    def by_id(self, provider_id: str | None):
        for p in self._providers:
            if p.info.id == provider_id:
                return p
        return None


registry = DebridProviderRegistry()
