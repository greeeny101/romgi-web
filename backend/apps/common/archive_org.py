"""
Read-only archive.org client: item search, item metadata, the raw bytes of
an item's `_archive.torrent`, and a streaming fetch of one file out of an
item.

Shared by the two browsers built on archive.org items — the ROM-set browser
(apps.romsets), which takes an item as a torrent, and the BIOS browser
(apps.bios), which takes individual files out of one over HTTP. It lives in
apps.common rather than either of them because the search/metadata half is
identical for both and duplicating it would mean duplicating the credential
and caching behaviour with it.

Distinct from the ingestion pipeline's IA scraper
(apps/ingestion/pipeline/sources/internet_archive), which regex-scrapes the
HTML of `/download/<item>` directory listings to build per-ROM catalog rows.
This one talks to the JSON APIs and cares about the *item as a whole*.

Responses are cached in Django's shared Redis cache rather than the
pipeline's `cache_manager` — that one writes into a `cache/` directory
relative to the process's cwd and is deliberately framework-agnostic
pipeline-only code, which is the wrong lifetime and the wrong location for
request-path caching.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from dataclasses import dataclass
from urllib.parse import quote

import requests
from django.core.cache import cache

logger = logging.getLogger(__name__)

SEARCH_URL = "https://archive.org/advancedsearch.php"
METADATA_URL = "https://archive.org/metadata/{identifier}"
DOWNLOAD_URL = "https://archive.org/download/{identifier}/{name}"
TORRENT_URL = "https://archive.org/download/{identifier}/{identifier}_archive.torrent"

# The honest UA, matching credentials.services.internet_archive's requests
# path — these are documented public JSON APIs, not a bot-detection layer we
# have any reason to dress up for.
USER_AGENT = "romgi/1.0 (archive.org item browser; contact via project repo)"

REQUEST_TIMEOUT = 30
TORRENT_TIMEOUT = 60
DOWNLOAD_TIMEOUT = 60
DOWNLOAD_CHUNK_BYTES = 64 * 1024

# advancedsearch.php is the endpoint that 503s under load; item metadata and
# the torrent are cheap and effectively immutable, so they're held far longer.
SEARCH_CACHE_SECONDS = 600
METADATA_CACHE_SECONDS = 6 * 3600
TORRENT_CACHE_SECONDS = 6 * 3600

MAX_ROWS = 50

# archive.org's default relevance ranking is close to useless for this:
# searching "fbneo" unsorted returns a handheld's SD-card image and a "PS 3
# Emulators" item in the top five, while the set the user actually wants sits
# below the fold. Download count is a strong proxy for "the set people
# actually use" — sorted this way, the same query puts fbneo_1003_bestset
# (469k downloads) fourth, behind three other genuine arcade sets. Sorting by
# size instead just surfaces the largest unrelated dumps on the site.
DEFAULT_SORT = "downloads desc"


class ArchiveOrgError(Exception):
    """Anything that stopped us getting a usable answer out of archive.org."""


class ArchiveOrgAuthRequired(ArchiveOrgError):
    """The item is login-gated and we have no usable Internet Archive
    credentials for this user (archive.org's `loggedin` collection —
    `access-restricted-item: true` in the metadata).

    Distinct from the generic error so the API can answer 403 with a
    pointer at the settings page instead of a bare 502.
    """


@dataclass(frozen=True)
class SearchResult:
    identifier: str
    title: str
    size: int
    downloads: int
    published: str | None


def _session() -> requests.Session:
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    return session


def is_restricted(payload: dict) -> bool:
    """Whether the item is in archive.org's login-gated `loggedin`
    collection. `/metadata` stays readable anonymously for these — only
    `/download/` is gated — which is why a restricted set searches and
    previews fine and then fails at the torrent."""
    metadata = payload.get("metadata") or {}
    restricted = str(metadata.get("access-restricted-item", "")).lower() == "true"
    return restricted or "loggedin" in _as_list(metadata.get("collection"))


def _authenticated_get(url: str, user, timeout: int, *, stream: bool = False, extra_headers: dict | None = None):
    """GET a `/download/` URL with the user's Internet Archive credentials.

    Two things have to be right and both are easy to get wrong:

    * The credentials must survive the redirect. archive.org always
      redirects /download/ to a per-item node host, and requests drops
      Authorization and Cookie on a host change — so a plain requests.get
      arrives anonymous and 401s on exactly the restricted items that need
      it. apps.common.http_session exists for this.
    * Both credential kinds are sent, because they expire independently —
      see internet_archive.apply_headers.

    With `stream=True` the caller owns the response and must close it; 416
    is handed back unraised, because a Range request that starts at EOF is
    the normal outcome of resuming a file that already finished.
    """
    from apps.common.http_session import session_for
    from apps.credentials.models import EncryptedCredential
    from apps.credentials.services import internet_archive as ia

    headers = {"User-Agent": USER_AGENT}
    credential = (
        EncryptedCredential.objects.filter(user=user, provider="internet_archive").first()
        if user is not None
        else None
    )
    if credential is not None and ia.is_logged_in(credential):
        ia.ensure_fresh(credential)
        credential.refresh_from_db()
        ia.apply_headers(credential, headers)

    session = session_for(url, headers)
    if extra_headers:
        headers.update(extra_headers)
    response = session.get(url, headers=headers, timeout=timeout, stream=stream, allow_redirects=True)
    if response.status_code in (401, 403):
        response.close()
        if credential is not None and ia.is_logged_in(credential):
            ia.record_auth_failure(credential)
            raise ArchiveOrgAuthRequired(
                "Internet Archive rejected your login for this item. "
                "Re-authenticate under Settings → Internet Archive."
            )
        raise ArchiveOrgAuthRequired(
            "This item is restricted and needs an Internet Archive login. "
            "Add one under Settings → Internet Archive, then try again."
        )
    if stream and response.status_code == 416:
        return response
    response.raise_for_status()
    return response


def _as_int(value) -> int:
    """archive.org returns sizes as strings, and omits the key entirely on
    some derived files (`<id>_files.xml` has no `size` at all) — so this has
    to tolerate None, "", and a bare int equally."""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _as_list(value) -> list[str]:
    """`collection` is a list on multi-collection items and a bare string on
    single-collection ones."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    return [str(value)]


def search(query: str, *, page: int = 1, rows: int = 25) -> tuple[list[SearchResult], int]:
    """Item search. Returns `(results, total_found)`."""
    rows = max(1, min(rows, MAX_ROWS))
    page = max(1, page)
    cache_key = f"ia:search:{query}:{rows}:{page}:{DEFAULT_SORT}"

    cached = cache.get(cache_key)
    if cached is None:
        params = [
            ("q", query),
            ("rows", str(rows)),
            ("page", str(page)),
            ("sort[]", DEFAULT_SORT),
            ("output", "json"),
            ("fl[]", "identifier"),
            ("fl[]", "title"),
            ("fl[]", "item_size"),
            ("fl[]", "downloads"),
            ("fl[]", "publicdate"),
        ]
        try:
            response = _session().get(SEARCH_URL, params=params, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            cached = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise ArchiveOrgError(f"archive.org search failed: {exc}") from exc
        cache.set(cache_key, cached, SEARCH_CACHE_SECONDS)

    payload = cached.get("response") or {}
    results = [
        SearchResult(
            identifier=doc.get("identifier", ""),
            title=str(doc.get("title") or doc.get("identifier") or ""),
            size=_as_int(doc.get("item_size")),
            downloads=_as_int(doc.get("downloads")),
            published=(str(doc["publicdate"])[:10] if doc.get("publicdate") else None),
        )
        for doc in payload.get("docs", [])
        if doc.get("identifier")
    ]
    return results, _as_int(payload.get("numFound"))


def item(identifier: str) -> dict:
    """Raw `/metadata/<id>` payload. Empty `{}` means no such item."""
    cache_key = f"ia:item:{identifier}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        response = _session().get(METADATA_URL.format(identifier=identifier), timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise ArchiveOrgError(f"Could not read archive.org item {identifier}: {exc}") from exc

    cache.set(cache_key, payload, METADATA_CACHE_SECONDS)
    return payload


def item_summary(payload: dict) -> dict:
    """The handful of fields the UI shows, normalised out of `/metadata`."""
    metadata = payload.get("metadata") or {}
    return {
        "identifier": metadata.get("identifier", ""),
        "title": str(metadata.get("title") or metadata.get("identifier") or ""),
        "description": str(metadata.get("description") or ""),
        "collections": _as_list(metadata.get("collection")),
        "published": (str(metadata["publicdate"])[:10] if metadata.get("publicdate") else None),
        "item_size": _as_int(payload.get("item_size")),
    }


def file_details(payload: dict) -> dict[str, dict]:
    """`{filename: {size, md5, sha1, format}}` from a `/metadata` payload.

    Only ever used to *enrich* the torrent's file list — never as the file
    list itself, which is a different and non-overlapping set (the metadata
    API lists `_files.xml`/`_reviews.xml`/`_archive.torrent`, none of which
    are in the torrent).
    """
    return {
        f["name"]: {
            "size": _as_int(f.get("size")),
            "md5": f.get("md5"),
            "sha1": f.get("sha1"),
            "format": f.get("format"),
        }
        for f in payload.get("files", [])
        if f.get("name")
    }


def published_infohash(payload: dict) -> str | None:
    """archive.org publishes each item's infohash as `btih` on the
    `_archive.torrent` file entry, so the hash is known before the torrent is
    ever fetched or added — which is what makes dedupe, adopt-existing and
    cancel correct rather than best-effort."""
    for f in payload.get("files", []):
        if f.get("name", "").endswith("_archive.torrent") and f.get("btih"):
            return str(f["btih"]).lower()
    return None


def torrent_bytes(identifier: str, user=None) -> bytes:
    """The item's `.torrent`, fetched as `user` so login-gated items work.

    Cached without reference to the user: the bytes are identical whoever
    fetches them, and the cache is only ever populated by someone who was
    allowed to read them.
    """
    cache_key = f"ia:torrent:{identifier}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        response = _authenticated_get(TORRENT_URL.format(identifier=identifier), user, TORRENT_TIMEOUT)
        data = response.content
    except ArchiveOrgError:
        raise
    except requests.RequestException as exc:
        raise ArchiveOrgError(f"Could not fetch the torrent for {identifier}: {exc}") from exc

    if not data:
        raise ArchiveOrgError(f"archive.org returned an empty torrent for {identifier}")

    cache.set(cache_key, data, TORRENT_CACHE_SECONDS)
    return data


def _md5_of(path: str) -> str:
    # md5 because that is what archive.org publishes; it's an integrity
    # check against a truncated transfer, not a security boundary.
    digest = hashlib.md5()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stream_file(
    identifier: str,
    name: str,
    dest_path: str,
    *,
    user=None,
    expected_size: int = 0,
    md5: str | None = None,
    on_progress=None,
    should_abort=None,
) -> tuple[int, bool]:
    """Stream one file out of an item to `dest_path`.

    Returns `(bytes_on_disk, completed)`. `completed` is False only when
    `should_abort()` asked us to stop, in which case the partial file is
    left in place — the next call resumes from it with a `Range` header.

    `on_progress(received, total)` is called per chunk and is expected to do
    its own throttling; `should_abort()` is polled on the same cadence.

    `md5` is archive.org's published checksum for the file. Verifying it
    matters more here than for a ROM: a corrupt BIOS doesn't fail loudly,
    it makes an emulator boot to a black screen with nothing to point at.
    """
    url = DOWNLOAD_URL.format(identifier=identifier, name=quote(name))
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)

    current = os.path.getsize(dest_path) if os.path.exists(dest_path) else 0
    if expected_size and current == expected_size:
        if md5 and _md5_of(dest_path) != md5.lower():
            os.remove(dest_path)
            current = 0
        else:
            if on_progress:
                on_progress(current, current)
            return current, True
    # A file larger than archive.org says it is can only be junk left by a
    # previous run against a different item revision — there is no rounding
    # tolerance to allow here, unlike the catalog's link_size estimates.
    if expected_size and current > expected_size:
        os.remove(dest_path)
        current = 0

    extra = {"Range": f"bytes={current}-"} if current else None
    try:
        response = _authenticated_get(url, user, DOWNLOAD_TIMEOUT, stream=True, extra_headers=extra)
    except ArchiveOrgError:
        raise
    except requests.RequestException as exc:
        raise ArchiveOrgError(f"Could not fetch {name} from {identifier}: {exc}") from exc

    aborted = False
    with response:
        if response.status_code == 416:
            # The range starts at or past EOF, so what's on disk is whole —
            # the normal outcome of resuming a file that already finished.
            # 416 carries the real total in "Content-Range: bytes */<total>".
            match = re.search(r"/(\d+)\s*$", response.headers.get("Content-Range", ""))
            if match and current == int(match.group(1)):
                if on_progress:
                    on_progress(current, current)
                return current, True
            os.remove(dest_path)
            raise ArchiveOrgError(f"archive.org rejected the resume of {name}; the partial file was discarded.")

        range_honored = response.status_code == 206
        mode = "ab" if (current and range_honored) else "wb"
        received = current if range_honored else 0

        # Content-Length counts the bytes on the wire, while iter_content
        # yields decoded ones — so it's only a true size when the body isn't
        # content-encoded.
        length = response.headers.get("Content-Length")
        encoding = (response.headers.get("Content-Encoding") or "identity").lower()
        total = (int(length) + received) if (length and encoding == "identity") else expected_size

        try:
            with open(dest_path, mode) as fh:
                for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_BYTES):
                    if not chunk:
                        continue
                    fh.write(chunk)
                    received += len(chunk)
                    if on_progress:
                        on_progress(received, total)
                    if should_abort and should_abort():
                        aborted = True
                        break
        except requests.RequestException as exc:
            raise ArchiveOrgError(f"Transfer of {name} from {identifier} failed: {exc}") from exc

    if aborted:
        return received, False

    if expected_size and received != expected_size:
        raise ArchiveOrgError(f"{name} came back {received} bytes, but archive.org lists it as {expected_size}.")
    if md5:
        actual = _md5_of(dest_path)
        if actual != md5.lower():
            os.remove(dest_path)
            raise ArchiveOrgError(
                f"{name} failed its checksum (archive.org says {md5.lower()}, got {actual}). "
                "The partial download was removed; try again."
            )
    return received, True
