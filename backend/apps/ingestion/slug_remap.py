"""
Carries a user's saved rows across a catalog rebuild that renames entries.

Favorite/RecentlyViewed/DownloadTask deliberately hold a portable
(slug, title, boxart_url) snapshot rather than an FK to catalog.Entry, so
they survive the build their entry came from being garbage-collected (see
apps.library.models). The cost of that design is that a rename breaks the
link silently: the arcade parsers now turn `10yard` into
"10-Yard Fight (World, set 1)", the slug follows the title, and every saved
row still pointing at `10yard` becomes unreachable.

This can't be a Django data migration — at migrate time the new build
doesn't exist, so the new slugs don't either. It runs after
orchestrator.finalize_build, joining the retired build to the active one on
(platform, ROM short name), which is stable across the rename precisely
because the mame parser preserves it in Entry.rom_id.
"""

from dataclasses import dataclass, field

from django.db import transaction

from apps.catalog.models import CatalogBuild, Entry
from apps.downloads.models import DownloadTask
from apps.library.models import Favorite, RecentlyViewed

# Every model holding a slug snapshot. All three carry a unique
# (user, slug) constraint, which is what makes collisions possible below.
REMAPPED_MODELS = (Favorite, RecentlyViewed, DownloadTask)


@dataclass
class RemapReport:
    from_build: int | None = None
    to_build: int | None = None
    mapped_slugs: int = 0
    updated: dict[str, int] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)
    orphaned: list[str] = field(default_factory=list)

    @property
    def total_updated(self) -> int:
        return sum(self.updated.values())


def _previous_build(active: CatalogBuild) -> CatalogBuild | None:
    return (
        CatalogBuild.objects.filter(status="retired", started_at__lt=active.started_at)
        .order_by("-started_at")
        .first()
    )


def build_slug_map(old_build: CatalogBuild, new_build: CatalogBuild) -> dict[tuple[str, str], tuple[str, str, str | None]]:
    """(platform_id, old_slug) -> (new_slug, new_title, new_boxart_url).

    Joined on the ROM short name. In the old build that's `title` (the
    source filename, pre-rename); once a build has been through the arcade
    parsers it's in `rom_id`, so accept either — the second rebuild after
    this change has rom_id populated on both sides.
    """
    new_by_rom: dict[tuple[str, str], tuple[str, str, str | None]] = {}
    for platform_id, rom_id, slug, title, boxart_url in Entry.objects.filter(
        build=new_build, rom_id__isnull=False
    ).values_list("platform_id", "rom_id", "slug", "title", "boxart_url"):
        # First writer wins: two ROM sets can share a description, and an
        # arbitrary-but-stable choice beats a last-one-in race.
        new_by_rom.setdefault((platform_id, rom_id), (slug, title, boxart_url))

    mapping: dict[tuple[str, str], tuple[str, str, str | None]] = {}
    for platform_id, rom_id, slug, title in Entry.objects.filter(build=old_build).values_list(
        "platform_id", "rom_id", "slug", "title"
    ):
        target = new_by_rom.get((platform_id, rom_id or title))
        if target and target[0] != slug:
            mapping[(platform_id, slug)] = target
    return mapping


def remap(
    to_build: CatalogBuild | None = None,
    from_build: CatalogBuild | None = None,
    *,
    commit: bool = False,
) -> RemapReport:
    report = RemapReport()

    to_build = to_build or CatalogBuild.objects.filter(status="active").order_by("-started_at").first()
    if to_build is None:
        return report
    from_build = from_build or _previous_build(to_build)
    if from_build is None:
        return report

    report.from_build, report.to_build = from_build.pk, to_build.pk
    mapping = build_slug_map(from_build, to_build)
    report.mapped_slugs = len(mapping)
    if not mapping:
        return report

    live_slugs = set(
        Entry.objects.filter(build=to_build).values_list("platform_id", "slug")
    )

    with transaction.atomic():
        for model in REMAPPED_MODELS:
            label = model.__name__
            report.updated[label] = 0

            # (user, slug) is unique per model, so a many-to-one rename can
            # collide with a row the user already has. Skip those rather
            # than deleting either side — an in-flight DownloadTask is not
            # ours to throw away.
            taken = {(user_id, slug) for user_id, slug in model.objects.values_list("user_id", "slug")}

            for row in model.objects.select_for_update():
                target = mapping.get((row.platform_id, row.slug))
                if target is None:
                    # Nothing to rename it to. Either it already points at a
                    # live entry (the common case), or its entry is gone:
                    # deleted upstream, or one of the handful of variant ROM
                    # sets the writer merges into a sibling's slug, where only
                    # the first set's short name survives in rom_id. Name
                    # those rather than let them disappear quietly.
                    if (row.platform_id, row.slug) not in live_slugs:
                        report.orphaned.append(f"{label} #{row.pk}: {row.slug!r} has no entry in the new build")
                    continue
                new_slug, new_title, new_boxart_url = target
                if (row.user_id, new_slug) in taken:
                    report.skipped.append(f"{label} #{row.pk}: {row.slug!r} -> {new_slug!r} already saved by this user")
                    continue

                taken.discard((row.user_id, row.slug))
                taken.add((row.user_id, new_slug))

                fields = ["slug", "title"]
                row.slug, row.title = new_slug, new_title
                # DownloadTask snapshots the link, not the artwork.
                if hasattr(row, "boxart_url"):
                    row.boxart_url = new_boxart_url
                    fields.append("boxart_url")
                row.save(update_fields=fields)
                report.updated[label] += 1

        if not commit:
            transaction.set_rollback(True)

    return report
