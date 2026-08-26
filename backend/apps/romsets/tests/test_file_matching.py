"""
Matching a set's recorded files to qBittorrent's file listing.

This is the highest-consequence mapping in the feature and it fails
silently in both directions. qBittorrent reports every path prefixed with
the torrent's root directory (for an archive.org item, the identifier);
RomSetFile stores them without it. Match on the bare path and nothing is
selected — which qBittorrent reports not as an error but as an instantly
"complete" torrent that transferred zero bytes.
"""

from dataclasses import dataclass

from apps.torrents.client import TorrentFile
from apps.torrents.ownership import _romset_wanted_file_ids

IDENTIFIER = "fbneo_1003_bestset"


@dataclass
class FakeRomSet:
    """Stands in for a RomSetDownload — only `identifier` and the
    `(path, wanted)` pairs are consulted, so this needs no database."""

    identifier: str
    rows: list[tuple[str, bool]]

    @property
    def files(self):
        return self

    def values_list(self, *_fields):
        return self.rows


def qb_file(file_id: int, name: str, size: int = 1) -> TorrentFile:
    return TorrentFile(id=file_id, index=file_id, name=name, size=size, priority=1, progress=0.0)


# What qBittorrent actually returns for this item: root-prefixed, and with
# the BEP-47 padding entries already filtered out of its index space.
QB_FILES = [
    qb_file(0, f"{IDENTIFIER}/__ia_thumb.jpg"),
    qb_file(1, f"{IDENTIFIER}/{IDENTIFIER}_meta.xml"),
    qb_file(2, f"{IDENTIFIER}/fbneo_1_0_0_3_best.zip", size=5010379875),
]


def test_root_prefixed_paths_match_the_unprefixed_records():
    romset = FakeRomSet(IDENTIFIER, [("fbneo_1_0_0_3_best.zip", True), ("__ia_thumb.jpg", True)])

    wanted, known = _romset_wanted_file_ids(romset, QB_FILES)

    assert wanted == {0, 2}
    assert known == {0, 2}


def test_deselected_files_are_known_but_not_wanted():
    """The distinction is what lets the priority pass skip a 5GB zip the
    user deselected while still not skipping files it merely failed to
    recognise."""
    romset = FakeRomSet(
        IDENTIFIER,
        [("fbneo_1_0_0_3_best.zip", False), ("__ia_thumb.jpg", True), (f"{IDENTIFIER}_meta.xml", True)],
    )

    wanted, known = _romset_wanted_file_ids(romset, QB_FILES)

    assert wanted == {0, 1}
    assert known == {0, 1, 2}


def test_unprefixed_listing_still_matches():
    """A daemon configured with content_layout=NoSubfolder drops the root
    directory. We pin content_layout at add time so this shouldn't happen,
    but falling back costs nothing and the alternative is a silent
    zero-byte download."""
    romset = FakeRomSet(IDENTIFIER, [("game.zip", True)])

    wanted, _known = _romset_wanted_file_ids(romset, [qb_file(0, "game.zip")])

    assert wanted == {0}


def test_files_absent_from_the_listing_are_simply_unmatched():
    """The torrent and the metadata API disagree on membership, so a
    recorded path that qBittorrent has never heard of must not raise, and
    must not be reported as known."""
    romset = FakeRomSet(IDENTIFIER, [("fbneo_1003_bestset_files.xml", True)])

    wanted, known = _romset_wanted_file_ids(romset, QB_FILES)

    assert wanted == set()
    assert known == set()


def test_nested_paths_match():
    romset = FakeRomSet("fbneo-1.0.3", [("FBNeo - Arcade Games/parents.zip", True)])
    files = [qb_file(0, "fbneo-1.0.3/FBNeo - Arcade Games/parents.zip")]

    wanted, _known = _romset_wanted_file_ids(romset, files)

    assert wanted == {0}
