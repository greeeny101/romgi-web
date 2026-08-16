"""Extracts a torrent's infohash from its magnet URI, for building the
DebridFileRequest passed to a provider's find-or-add-by-hash flow."""

import re

_INFOHASH_RE = re.compile(r"btih:([A-Za-z0-9]+)", re.IGNORECASE)


def infohash_from_magnet(magnet: str) -> str | None:
    match = _INFOHASH_RE.search(magnet)
    return match.group(1).lower() if match else None
