"""
GET /metadata/entries/{slug} eagerly fetches (or serves from cache) the
merged ScreenScraper+SteamGridDB result for an entry — mirrors the Dart
app's eager on-screen-load Riverpod provider (`gameMetadataProvider`,
watched directly in entry_detail_screen.dart, no explicit "fetch" button).
Gated by the caller's UserSettings.metadata_enabled, same as the original
app's global toggle.

GET /metadata/media/{token} exists because ScreenScraper's media URLs are
authenticated: the API returns them with devid/devpassword/ssid/sspassword
in the query string, and those would otherwise travel through the shared
metadata cache into an <img src> in every viewer's browser. The provider
strips them (providers/screenscraper.py:_strip_auth) and this endpoint
re-attaches them server-side, so the credentials never leave the backend.
"""

from urllib.parse import urlparse

import requests
from django.core import signing
from django.http import StreamingHttpResponse
from django.shortcuts import get_object_or_404
from ninja import Router
from ninja.errors import HttpError
from ninja_jwt.authentication import JWTAuth

from apps.accounts.models import UserSettings
from apps.catalog.models import CatalogBuild, Entry
from apps.credentials.models import EncryptedCredential

from .providers.base import MediaItem
from .providers.screenscraper import MEDIA_HOSTS as SCREENSCRAPER_MEDIA_HOSTS
from .providers.screenscraper import TIMEOUT as SCREENSCRAPER_TIMEOUT
from .providers.screenscraper import build_auth_params
from .schemas import GameMetadataOut, MediaOut
from .service import get_metadata

router = Router(tags=["metadata"], auth=JWTAuth())

MEDIA_SALT = "metadata.media"
# Tokens are minted fresh on every entry-metadata response, so this only has
# to outlive a page someone left open — deliberately far shorter than the
# 14-day cache row the underlying URL came from.
MEDIA_TOKEN_MAX_AGE = 60 * 60 * 24
MEDIA_CHUNK = 64 * 1024


@router.get("/entries/{slug}", response={200: GameMetadataOut, 204: None})
def get_entry_metadata(request, slug: str):
    settings_obj = UserSettings.objects.filter(user=request.user).first()
    if settings_obj is None or not settings_obj.metadata_enabled:
        return 204, None

    build = CatalogBuild.objects.filter(status="active").order_by("-started_at").first()
    if build is None:
        return 204, None
    entry = get_object_or_404(Entry, build=build, slug=slug)

    result = get_metadata(request.user, entry.title, entry.platform_id)
    if result is None:
        return 204, None
    return 200, GameMetadataOut(
        description=result.description,
        screenshots=[_media_out(request, m) for m in result.screenshots],
        artwork=[_media_out(request, m) for m in result.artwork],
    )


def _media_out(request, media: MediaItem) -> MediaOut:
    return MediaOut(full=_proxied(request, media.full), thumb=_proxied(request, media.thumb))


def _proxied(request, url: str) -> str:
    """Rewrites only ScreenScraper-hosted media. SteamGridDB's are plain
    unauthenticated CDN links and must reach the browser untouched.

    Done here rather than in the provider so the cache stays portable: these
    tokens expire, and a signed URL must never be what gets written into a
    GameMetadataCache row that outlives it by two weeks.
    """
    if not url or urlparse(url).hostname not in SCREENSCRAPER_MEDIA_HOSTS:
        return url
    token = signing.dumps({"u": request.user.id, "url": url}, salt=MEDIA_SALT)
    # Absolute: the browser resolves <img src> against the frontend origin
    # (:5173 in dev), not against the API it fetched the JSON from.
    return request.build_absolute_uri(f"/api/metadata/media/{token}")


@router.get("/media/{token}", auth=None, response=None)
def get_media(request, token: str):
    """Unauthenticated by necessity — an <img src> cannot carry the router's
    JWT header. The signature *is* the capability instead (following the
    unauthenticated ingestion router's precedent), and the token carries the
    user it was minted for so media fetches keep counting against that
    user's ScreenScraper quota rather than the instance's.
    """
    try:
        payload = signing.loads(token, salt=MEDIA_SALT, max_age=MEDIA_TOKEN_MAX_AGE)
    except signing.BadSignature as exc:  # covers SignatureExpired
        raise HttpError(400, "Invalid or expired media link.") from exc

    url = payload.get("url") or ""
    parsed = urlparse(url)
    # Belt and braces beside the signature: without this, anyone who ever
    # obtains a signing key turns this into an open proxy onto the internal
    # network. A signed token is not a reason to skip the allowlist.
    if parsed.scheme != "https" or parsed.hostname not in SCREENSCRAPER_MEDIA_HOSTS:
        raise HttpError(400, "Unsupported media host.")

    auth = build_auth_params(_creds_for_id(payload.get("u")))
    try:
        upstream = requests.get(url, params=auth, stream=True, timeout=SCREENSCRAPER_TIMEOUT)
    except requests.RequestException as exc:
        raise HttpError(502, "Could not reach ScreenScraper.") from exc

    content_type = upstream.headers.get("Content-Type", "")
    # ScreenScraper answers auth/quota failures as plain text under HTTP 200,
    # so status alone doesn't tell us whether this is an image. Never pass
    # that body through — it can name the account in its error text.
    if upstream.status_code != 200 or not content_type.startswith("image/"):
        upstream.close()
        raise HttpError(502, "ScreenScraper did not return an image.")

    response = StreamingHttpResponse(
        upstream.iter_content(chunk_size=MEDIA_CHUNK),
        content_type=content_type,
    )
    # Game art for a fixed game id never changes, so this is capped by the
    # token's own lifetime rather than by staleness — caching past that point
    # would just hold an entry keyed by a URL nothing will request again.
    response["Cache-Control"] = f"private, max-age={MEDIA_TOKEN_MAX_AGE}"
    return response


def _creds_for_id(user_id) -> dict:
    """service._creds_for's sibling, keyed by id — the token carries a user
    id, and there's no reason to load the user row just to filter on it.
    An empty dict is fine: build_auth_params omits ssid/sspassword when blank, so
    the fetch falls back to the instance's developer quota."""
    if not user_id:
        return {}
    credential = EncryptedCredential.objects.filter(user_id=user_id, provider="screenscraper").first()
    return (credential.data or {}) if credential else {}
