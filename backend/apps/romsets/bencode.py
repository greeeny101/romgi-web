"""
Minimal bdecoder, just enough to read an archive.org `_archive.torrent`.

Deliberately not a dependency: the only things we need out of a .torrent are
the file list and (as a fallback) the infohash, and every bencode library on
PyPI brings an encoder, a stream API and a metadata model we'd never touch.

The decoder tracks byte offsets so `infohash()` can SHA-1 the *original*
bytes of the `info` value. Re-encoding a decoded dict would produce a
different digest the moment a real-world torrent's keys aren't in canonical
order — which is exactly the case bencode's spec allows and trackers ignore.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

# BEP-47 padding files exist only to align the *next* real file with a piece
# boundary. qBittorrent filters them out of its own index space entirely
# (see TorrentInfo's pad_file_at check), so they can never be selected,
# skipped, or matched by name — they must not reach the UI or the DB.
PADDING_PREFIX = ".____padding_file"
PADDING_ATTR = b"p"


class BencodeError(ValueError):
    pass


def _decode(data: bytes, pos: int) -> tuple[object, int]:
    if pos >= len(data):
        raise BencodeError("Unexpected end of data")
    marker = data[pos : pos + 1]

    if marker == b"d":
        pos += 1
        result: dict[bytes, object] = {}
        while data[pos : pos + 1] != b"e":
            key, pos = _decode(data, pos)
            if not isinstance(key, bytes):
                raise BencodeError("Dictionary keys must be byte strings")
            value, pos = _decode(data, pos)
            result[key] = value
        return result, pos + 1

    if marker == b"l":
        pos += 1
        items: list[object] = []
        while data[pos : pos + 1] != b"e":
            value, pos = _decode(data, pos)
            items.append(value)
        return items, pos + 1

    if marker == b"i":
        end = data.index(b"e", pos)
        return int(data[pos + 1 : end]), end + 1

    if marker.isdigit():
        colon = data.index(b":", pos)
        length = int(data[pos:colon])
        start = colon + 1
        return data[start : start + length], start + length

    raise BencodeError(f"Unexpected byte {marker!r} at offset {pos}")


def bdecode(data: bytes) -> object:
    value, _ = _decode(data, 0)
    return value


def infohash_from_torrent(data: bytes) -> str:
    """SHA-1 of the raw bytes of the `info` value, lowercase hex.

    Only a fallback: archive.org publishes the same digest as `btih` on the
    `_archive.torrent` entry of its metadata API, so we normally never have
    to fetch the torrent just to learn its hash.
    """
    top, _ = _decode(data, 0)
    if not isinstance(top, dict):
        raise BencodeError("Torrent is not a dictionary")

    # Re-walk the top level tracking offsets, so the `info` span is exact.
    pos = 1
    while data[pos : pos + 1] != b"e":
        key, pos = _decode(data, pos)
        start = pos
        _, pos = _decode(data, pos)
        if key == b"info":
            return hashlib.sha1(data[start:pos]).hexdigest()
    raise BencodeError("Torrent has no info dictionary")


@dataclass(frozen=True)
class TorrentEntry:
    path: str
    size: int


def torrent_files(data: bytes) -> tuple[str, list[TorrentEntry]]:
    """`(root_name, entries)` for a decoded torrent, padding files removed.

    `root_name` matters as much as the list does: qBittorrent reports every
    file path prefixed with it, while archive.org's metadata API does not,
    so it's the difference between a name match and a silent zero-byte
    "complete" download.
    """
    top = bdecode(data)
    if not isinstance(top, dict) or b"info" not in top:
        raise BencodeError("Torrent has no info dictionary")
    info = top[b"info"]
    if not isinstance(info, dict):
        raise BencodeError("Torrent info is not a dictionary")

    root = info[b"name"].decode("utf-8", "replace")

    files = info.get(b"files")
    if files is None:  # single-file torrent — the root name IS the file
        return root, [TorrentEntry(path=root, size=int(info[b"length"]))]

    entries: list[TorrentEntry] = []
    for entry in files:
        path = "/".join(part.decode("utf-8", "replace") for part in entry[b"path"])
        attr = entry.get(b"attr") or b""
        if PADDING_ATTR in attr or path.startswith(PADDING_PREFIX):
            continue
        entries.append(TorrentEntry(path=path, size=int(entry[b"length"])))
    return root, entries
