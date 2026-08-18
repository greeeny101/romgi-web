from django.shortcuts import get_object_or_404
from ninja import Router, Schema
from ninja.errors import HttpError
from ninja_jwt.authentication import JWTAuth

from apps.catalog.models import CatalogBuild, Entry, RegionEntry

from .models import Favorite, RecentlyViewed
from .schemas import FavoriteOut, RecentlyViewedOut

router = Router(tags=["library"], auth=JWTAuth())

RECENTLY_VIEWED_CAP = 50


class SlugIn(Schema):
    slug: str


def _active_entry(slug: str) -> Entry:
    build = CatalogBuild.objects.filter(status="active").order_by("-started_at").first()
    if build is None:
        raise HttpError(404, "No active catalog build.")
    return get_object_or_404(Entry, slug=slug, build=build)


def _regions_by_slug(slugs: list[str]) -> dict[str, list[str]]:
    """
    Favorite/RecentlyViewed snapshot title/platform/boxart but not region, and they
    outlive the catalog build they were created from. Join back by slug rather than
    denormalizing a fifth field; an entry dropped from the catalog just yields [].
    """
    build = CatalogBuild.objects.filter(status="active").order_by("-started_at").first()
    if build is None:
        return {}

    out: dict[str, list[str]] = {}
    for slug, region_id in RegionEntry.objects.filter(
        entry__build=build, entry__slug__in=slugs
    ).values_list("entry__slug", "region_id"):
        out.setdefault(slug, []).append(region_id)
    return out


@router.get("/favorites", response=list[FavoriteOut])
def list_favorites(request):
    favorites = list(Favorite.objects.filter(user=request.user).select_related("platform"))
    regions = _regions_by_slug([f.slug for f in favorites])
    return [
        FavoriteOut(
            slug=f.slug,
            title=f.title,
            platform_id=f.platform_id,
            boxart_url=f.boxart_url,
            regions=regions.get(f.slug, []),
            created_at=f.created_at.isoformat(),
        )
        for f in favorites
    ]


@router.post("/favorites", response=FavoriteOut)
def add_favorite(request, payload: SlugIn):
    entry = _active_entry(payload.slug)
    favorite, _ = Favorite.objects.update_or_create(
        user=request.user,
        slug=entry.slug,
        defaults=dict(title=entry.title, platform_id=entry.platform_id, boxart_url=entry.boxart_url),
    )
    return FavoriteOut(
        slug=favorite.slug,
        title=favorite.title,
        platform_id=favorite.platform_id,
        boxart_url=favorite.boxart_url,
        regions=list(entry.regions.values_list("id", flat=True)),
        created_at=favorite.created_at.isoformat(),
    )


@router.delete("/favorites/{slug}", response={204: None})
def remove_favorite(request, slug: str):
    Favorite.objects.filter(user=request.user, slug=slug).delete()
    return 204, None


@router.get("/recently-viewed", response=list[RecentlyViewedOut])
def list_recently_viewed(request):
    recent = list(
        RecentlyViewed.objects.filter(user=request.user).select_related("platform")[
            :RECENTLY_VIEWED_CAP
        ]
    )
    regions = _regions_by_slug([r.slug for r in recent])
    return [
        RecentlyViewedOut(
            slug=r.slug,
            title=r.title,
            platform_id=r.platform_id,
            boxart_url=r.boxart_url,
            regions=regions.get(r.slug, []),
            viewed_at=r.viewed_at.isoformat(),
        )
        for r in recent
    ]


@router.post("/recently-viewed/{slug}", response={204: None})
def record_recently_viewed(request, slug: str):
    entry = _active_entry(slug)
    RecentlyViewed.objects.update_or_create(
        user=request.user,
        slug=entry.slug,
        defaults=dict(title=entry.title, platform_id=entry.platform_id, boxart_url=entry.boxart_url),
    )
    # Trim to the cap — same "last 50" behavior as the original app's local DB.
    stale_ids = list(
        RecentlyViewed.objects.filter(user=request.user)
        .order_by("-viewed_at")
        .values_list("id", flat=True)[RECENTLY_VIEWED_CAP:]
    )
    if stale_ids:
        RecentlyViewed.objects.filter(id__in=stale_ids).delete()
    return 204, None
