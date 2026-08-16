"""Ports lib/services/debrid/debrid_provider.dart's abstract interface."""

from dataclasses import dataclass


@dataclass
class DebridProviderInfo:
    id: str
    name: str


@dataclass
class DebridFileRequest:
    infohash: str
    magnet: str
    file_index: int
    file_path: str
    expected_size: int = 0


@dataclass
class DebridReady:
    url: str
    filename: str | None = None
    size: int | None = None


@dataclass
class DebridCaching:
    progress: float | None = None


@dataclass
class DebridNotCached:
    pass


@dataclass
class DebridError:
    message: str
    auth_error: bool = False
    rate_limited: bool = False
    permanent: bool = False


DebridResult = DebridReady | DebridCaching | DebridNotCached | DebridError


class DebridProvider:
    info: DebridProviderInfo

    def is_configured(self, api_key: str | None) -> bool:
        return bool(api_key and api_key.strip())

    def validate_key(self, api_key: str) -> str | None:
        raise NotImplementedError

    def resolve_file(self, req: DebridFileRequest, api_key: str) -> DebridResult:
        raise NotImplementedError


def sizes_close(a: int, b: int) -> bool:
    """5% tolerance, ceil-rounded — ports both providers' _sizesClose."""
    larger = max(a, b)
    return abs(a - b) <= -(-larger * 5 // 100)
