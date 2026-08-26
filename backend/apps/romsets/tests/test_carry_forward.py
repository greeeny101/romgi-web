"""
Re-requesting a set must never delete what it already downloaded.

Deselecting a file is not a passive act: qBittorrent is handed "do not
download" for it, and when the torrent's data is already on disk it removes
that data. Asking for a MAME set's `roms/` after a run that fetched
`samples/` therefore deleted the samples — and the same two requests in the
other order would have destroyed 30GB of ROMs.

There is no error and no warning when this happens; the set reports success
with the files quietly gone. Hence a test.
"""

from dataclasses import dataclass, field

from apps.romsets.api import carried_forward_paths


@dataclass
class FakeFiles:
    rows: list[tuple[str, bool]]  # (path, done)

    def filter(self, **kwargs):
        done = kwargs.get("done")
        return FakeFiles([r for r in self.rows if done is None or r[1] == done])

    def values_list(self, *_fields, flat=False):
        return [r[0] for r in self.rows]


@dataclass
class FakeRomSet:
    """Only `.files` is consulted, so this needs no database."""

    rows: list[tuple[str, bool]] = field(default_factory=list)

    @property
    def files(self):
        return FakeFiles(self.rows)


AVAILABLE = {"roms/1941.zip", "roms/1942.zip", "samples/berzerk.zip", "samples/armora.zip"}


def test_downloaded_files_survive_a_narrower_re_request():
    existing = FakeRomSet([("samples/berzerk.zip", True), ("samples/armora.zip", True), ("roms/1941.zip", False)])

    assert carried_forward_paths(existing, AVAILABLE) == {"samples/berzerk.zip", "samples/armora.zip"}


def test_unfinished_files_are_not_carried_forward():
    """A half-downloaded file has nothing worth protecting, and keeping it
    selected would silently widen a request the user deliberately narrowed."""
    existing = FakeRomSet([("roms/1941.zip", False), ("roms/1942.zip", False)])

    assert carried_forward_paths(existing, AVAILABLE) == set()


def test_files_no_longer_in_the_torrent_are_dropped():
    """archive.org items gain and lose files. A path that isn't in the
    current torrent can't be selected in it, and passing it through would
    fail validation on a set the user can otherwise download fine."""
    existing = FakeRomSet([("samples/gone.zip", True), ("roms/1941.zip", True)])

    assert carried_forward_paths(existing, AVAILABLE) == {"roms/1941.zip"}


def test_first_download_of_a_set_carries_nothing():
    assert carried_forward_paths(None, AVAILABLE) == set()
