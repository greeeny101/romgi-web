"""
Read-only archive.org client for the ROM-set browser: item search, item
metadata, and the raw bytes of an item's `_archive.torrent`.

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

import logging
from dataclasses import dataclass

import requests
from django.core.cache import cache

logger = logging.getLogger(__name__)

SEARCH_URL = "https://archive.org/advancedsearch.php"
METADATA_URL = "https://archive.org/metadata/{identifier}"
TORRENT_URL = "https://archive.org/download/{identifier}/{identifier}_archive.torrent"

# The honest UA, matching credentials.services.internet_archive's requests
# path — these are documented public JSON APIs, not a bot-detection layer we
# have any reason to dress up for.
USER_AGENT = "romgi/1.0 (ROM set browser; contact via project repo)"

REQUEST_TIMEOUT = 30
TORRENT_TIMEOUT = 60

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


def _authenticated_get(url: str, user, timeout: int):
    """GET a `/download/` URL with the user's Internet Archive credentials.

    Two things have to be right and both are easy to get wrong:

    * The credentials must survive the redirect. archive.org always
      redirects /download/ to a per-item node host, and requests drops
      Authorization and Cookie on a host change — so a plain requests.get
      arrives anonymous and 401s on exactly the restricted items that need
      it. apps.common.http_session exists for this.
    * Both credential kinds are sent, because they expire independently —
      see internet_archive.apply_headers.
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
    response = session.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    if response.status_code in (401, 403):
        if credential is not None and ia.is_logged_in(credential):
            ia.record_auth_failure(credential)
            raise ArchiveOrgAuthRequired(
                "Internet Archive rejected your login for this item. "
                "Re-authenticate under Settings → Internet Archive."
            )
        raise ArchiveOrgAuthRequired(
            "This set is restricted and needs an Internet Archive login. "
            "Add one under Settings → Internet Archive, then try again."
        )
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
    cache_key = f"romsets:search:{query}:{rows}:{page}:{DEFAULT_SORT}"

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
    cache_key = f"romsets:item:{identifier}"
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
    cache_key = f"romsets:torrent:{identifier}"
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
