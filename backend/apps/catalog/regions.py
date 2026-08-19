"""
The region taxonomy: which of the seeded catalog.Region ids are grouped under
which, and what a user's single-select region filter should actually match.

Regions are stored flat (one Region row per id, no self-FK) because the
grouping is a fixed editorial fact, not per-row data — the same reason
PLATFORMS/REGIONS live in a seed migration rather than a table the app
writes to. Keeping the hierarchy here means adding a country is a code
change plus a seed migration, with no schema churn.

Mirrored on the client by frontend/src/lib/regions.ts — keep the two in sync.
"""

# Country regions that are also part of Europe/PAL. Selecting one of these
# has to include plain 'eu' too: a pan-European release is the same disc a
# German user wants, it just isn't labelled Germany.
REGION_PARENTS = {
    "de": "eu",
    "fr": "eu",
    "au": "eu",
    "uk": "eu",
}

REGION_CHILDREN: dict[str, list[str]] = {}
for _child, _parent in REGION_PARENTS.items():
    REGION_CHILDREN.setdefault(_parent, []).append(_child)

# A 'World' release carries no region lockout, so it belongs in the results
# for every *real* region. Not for 'other', which means "none of the ones we
# model" — folding World into it would make that bucket meaningless.
WORLD_REGION = "world"
_NO_WORLD = {"other", WORLD_REGION}


def region_root(region_id: str) -> str:
    """The group a region belongs to — itself, unless it has a parent."""
    return REGION_PARENTS.get(region_id, region_id)


def expand_region_filter(region_id: str) -> list[str]:
    """The set of region ids a filter on `region_id` should match."""
    ids = {region_id}

    parent = REGION_PARENTS.get(region_id)
    if parent:
        ids.add(parent)
    ids.update(REGION_CHILDREN.get(region_id, ()))

    if region_id not in _NO_WORLD:
        ids.add(WORLD_REGION)

    return sorted(ids)
