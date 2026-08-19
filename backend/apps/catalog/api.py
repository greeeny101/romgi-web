"""
Read-only catalog API (Phase 1). Always queries the currently *active*
CatalogBuild — see apps.catalog.models.CatalogBuild / the generation-tagged
writes design. No auth required yet: full JWT gating + settings-aware link
ranking (LinkResolver) land with the `downloads` app in Phase 3.
"""

from django.contrib.postgres.search import SearchQuery, SearchRank
from django.db.models import Q
from django.shortcuts import get_object_or_404
from ninja import Query, Router

from .models import CatalogBuild, Entry, EntryGroup, Platform, Region, Source, SourceHealth
from .regions import expand_region_filter
from .schemas import (
    EntryDetailOut,
    EntryGroupMemberOut,
    EntryGroupOut,
    EntrySummaryOut,
    LinkOut,
    PaginatedEntries,
    PlatformOut,
    RegionOut,
    SourceHealthOut,
    SourceOut,
)

router = Router(tags=["catalog"])


def _active_entries():
    build = CatalogBuild.objects.filter(status="active").order_by("-started_at").first()
    if build is None:
        return Entry.objects.none()
    return Entry.objects.filter(build=build)


@router.get("/platforms", response=list[PlatformOut])
def list_platforms(request):
    return list(Platform.objects.all())


@router.get("/regions", response=list[RegionOut])
def list_regions(request):
    return list(Region.objects.all())


@router.get("/sources", response=list[SourceOut])
def list_sources(request):
    return list(Source.objects.all())


@router.get("/sources/health", response=list[SourceHealthOut])
def list_source_health(request):
    return [
        SourceHealthOut(
            source_id=h.source_id,
            status=h.status,
            last_checked_at=h.last_checked_at.isoformat() if h.last_checked_at else None,
            notes=h.notes,
            entry_count=h.entry_count,
            link_count=h.link_count,
        )
        for h in SourceHealth.objects.select_related("source").all()
    ]


@router.get("/entries", response=PaginatedEntries)
def list_entries(
    request,
    q: str = Query(None),
    platform: str = Query(None),
    region: str = Query(None),
    source: str = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(40, ge=1, le=100),
):
    qs = _active_entries().select_related("platform").prefetch_related("regions")

    if q:
        query = SearchQuery(q, search_type="websearch")
        qs = qs.filter(search_vector=query).annotate(rank=SearchRank("search_vector", query)).order_by("-rank")
    else:
        qs = qs.order_by("title")

    if platform:
        qs = qs.filter(platform_id=platform)
    if region:
        # Widened to the region's group — picking Germany also returns plain
        # Europe releases, picking Europe returns its countries, and 'World'
        # releases match everything. .distinct() because an entry tagged with
        # two ids in that set would otherwise duplicate across the M2M join
        # and throw off both `total` and the slice below.
        qs = qs.filter(regions__id__in=expand_region_filter(region)).distinct()
    if source:
        qs = qs.filter(links__source_id=source).distinct()

    total = qs.count()
    start = (page - 1) * page_size
    items = list(qs[start : start + page_size])

    return PaginatedEntries(
        items=[
            EntrySummaryOut(
                slug=e.slug,
                title=e.title,
                platform_id=e.platform_id,
                boxart_url=e.boxart_url,
                ra_game_id=e.ra_game_id,
                # .all() so this reads the prefetch cache rather than one query per row
                regions=[r.id for r in e.regions.all()],
            )
            for e in items
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/entries/{slug}", response=EntryDetailOut)
def get_entry(request, slug: str):
    entry = get_object_or_404(_active_entries(), slug=slug)
    membership = entry.group_memberships.select_related("group").first()
    return EntryDetailOut(
        slug=entry.slug,
        title=entry.title,
        rom_id=entry.rom_id,
        platform_id=entry.platform_id,
        boxart_url=entry.boxart_url,
        ra_game_id=entry.ra_game_id,
        ra_num_achievements=entry.ra_num_achievements,
        regions=list(entry.regions.values_list("id", flat=True)),
        group_id=membership.group_id if membership else None,
    )


@router.get("/entries/{slug}/links", response=list[LinkOut])
def get_entry_links(request, slug: str):
    entry = get_object_or_404(_active_entries(), slug=slug)
    # Simple source-priority ordering for now. Replaced in Phase 3 by
    # downloads.link_resolver.LinkResolver, which also weighs the caller's
    # UserSettings (preferred/disabled sources, torrents-disabled, IA login).
    links = entry.links.select_related("source").order_by("-source__priority", "name")
    return [
        LinkOut(
            id=link.id,
            name=link.name,
            type=link.type,
            format=link.format,
            url=link.url,
            filename=link.filename,
            host=link.host,
            size=link.size,
            size_str=link.size_str,
            source_id=link.source_id,
            requires_auth=link.requires_auth,
            is_torrent=link.torrent_id is not None,
            torrent_file_index=link.torrent_file_index,
        )
        for link in links
    ]


@router.get("/groups/{group_id}", response=EntryGroupOut)
def get_group(request, group_id: int):
    group = get_object_or_404(EntryGroup, id=group_id)
    members = group.members.select_related("entry").order_by("member_index")
    return EntryGroupOut(
        id=group.id,
        kind=group.kind,
        title=group.title,
        platform_id=group.platform_id,
        member_count=group.member_count,
        members=[
            EntryGroupMemberOut(
                slug=m.entry.slug,
                title=m.entry.title,
                member_index=m.member_index,
                member_label=m.member_label,
            )
            for m in members
        ],
    )
