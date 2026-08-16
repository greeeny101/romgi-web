"""Ports lib/services/metadata/metadata_provider.dart's abstract interface.

Notably: the Dart model has no release date, rating, or genre field —
despite those existing in ScreenScraper's real API response, the source
app never parses them. The entire fetched surface is description +
screenshot URLs + artwork URLs, so that's all this ports too."""

from dataclasses import dataclass, field


@dataclass
class MetadataProviderInfo:
    id: str
    name: str


@dataclass
class CredentialField:
    key: str
    label: str
    obscure: bool = False
    optional: bool = False


@dataclass
class MetadataFound:
    description: str | None = None
    screenshot_urls: list[str] = field(default_factory=list)
    artwork_urls: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.description and not self.screenshot_urls and not self.artwork_urls


@dataclass
class MetadataNoMatch:
    pass


@dataclass
class MetadataError:
    message: str
    auth_error: bool = False


MetadataResult = MetadataFound | MetadataNoMatch | MetadataError


class MetadataProvider:
    info: MetadataProviderInfo
    credential_fields: list[CredentialField] = []

    def is_configured(self, creds: dict | None) -> bool:
        creds = creds or {}
        return all((creds.get(f.key) or "").strip() for f in self.credential_fields if not f.optional)

    def validate_credentials(self, creds: dict) -> str | None:
        raise NotImplementedError

    def fetch(self, title: str, platform: str, creds: dict) -> MetadataResult:
        raise NotImplementedError
