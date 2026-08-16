"""
GET /metadata/entries/{slug} eagerly fetches (or serves from cache) the
merged ScreenScraper+SteamGridDB result for an entry — mirrors the Dart
app's eager on-screen-load Riverpod provider (`gameMetadataProvider`,
watched directly in entry_detail_screen.dart, no explicit "fetch" button).
Gated by the caller's UserSettings.metadata_enabled, same as the original
app's global toggle.
"""

from django.shortcuts import get_object_or_404
from ninja import Router
from ninja_jwt.authentication import JWTAuth

from apps.accounts.models import UserSettings
from apps.catalog.models import CatalogBuild, Entry

from .schemas import GameMetadataOut
from .service import get_metadata

router = Router(tags=["metadata"], auth=JWTAuth())


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
        description=result.description, screenshot_urls=result.screenshot_urls, artwork_urls=result.artwork_urls
    )
