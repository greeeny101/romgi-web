"""Ports lib/services/metadata/metadata_provider.dart's abstract interface.

Notably: the Dart model has no release date, rating, or genre field —
despite those existing in ScreenScraper's real API response, the source
app never parses them. The entire fetched surface is description +
screenshots + artwork, so that's all this ports too.

Media is carried as MediaItem rather than a bare URL — the source app
displayed originals throughout, but a full-size SteamGridDB hero is
megabytes of PNG rendered into a 128px-tall strip, so the web client
needs the thumbnail alongside the original it links out to."""

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
class MediaItem:
    """`thumb` falls back to `full` for providers that return no
    thumbnail of their own (ScreenScraper), so consumers can always read
    `thumb` for display and `full` for the click-through."""

    full: str
    thumb: str = ""

    def __post_init__(self):
        self.thumb = self.thumb or self.full

    def as_dict(self) -> dict:
        return {"full": self.full, "thumb": self.thumb}

    @classmethod
    def from_cached(cls, value) -> "MediaItem | None":
        # Rows written before media carried thumbnails hold a bare URL
        # string; they stay readable until their TTL ages them out.
        if isinstance(value, str):
            return cls(full=value) if value else None
        if isinstance(value, dict) and value.get("full"):
            return cls(full=value["full"], thumb=value.get("thumb") or "")
        return None


@dataclass
class MetadataFound:
    description: str | None = None
    screenshots: list[MediaItem] = field(default_factory=list)
    artwork: list[MediaItem] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.description and not self.screenshots and not self.artwork


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
