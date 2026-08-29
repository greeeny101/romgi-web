"""
What counts as a downloadable file inside an archive.org item, and where it
is allowed to land.

Both questions are answered here rather than in api.py because the answers
have to agree in two places: the API decides what the user may select, and
the task decides what it may write. A name accepted by one and rejected by
the other is a download that fails after the user has already committed to
it.
"""

from __future__ import annotations

import os

# archive.org generates these alongside every item. They are not part of what
# was uploaded, they are useless in an emulator's system folder, and on some
# of them the metadata API doesn't even report a size — so they are dropped
# before the user ever sees a file list. `history/` holds the item's own
# edit log.
DERIVED_SUFFIXES = (
    "_files.xml",
    "_meta.xml",
    "_meta.sqlite",
    "_reviews.xml",
    "_archive.torrent",
    "_itemimage.jpg",
    "__ia_thumb.jpg",
)


def is_derived(name: str) -> bool:
    return name.startswith("history/") or name.endswith(DERIVED_SUFFIXES)


def is_safe(name: str) -> bool:
    """Whether `name` stays inside the directory it's joined to.

    A file name from the metadata API is item-relative and may contain
    subdirectories, so it can't simply be flattened — but it is remote input
    reaching `os.path.join`, and `../../` in it would write outside the
    library entirely. Same guard as extraction._safe_target, which exists
    for the identical reason one layer down.
    """
    if not name or name.startswith("/") or os.path.isabs(name):
        return False
    return os.path.normpath(os.path.join("/base", name)).startswith("/base/")


def selectable(name: str) -> bool:
    return not is_derived(name) and is_safe(name)


def destination(directory: str, name: str) -> str:
    """Absolute path `name` writes to, having been vetted by `is_safe`."""
    return os.path.join(directory, name)
