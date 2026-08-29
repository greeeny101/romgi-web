"""
A task does not always own the directory its own file lands in.

qBittorrent dedupes by infohash, and MiNERVA bundles thousands of games into
one torrent — so when a second task wants a different file out of a bundle
that is already present, add_torrent adopts the existing torrent instead of
re-adding it, and the torrent keeps the save path of whichever task added it
first. Resolving the finished file against _local_dir(task.id) therefore
looked in an empty directory for every adopting task.

The regression this guards is not silent, but it is actively misleading: the
task reports "Downloaded file missing on disk" after transferring every byte
correctly, which reads as a disk or network fault. Tracing it back to a
save-path assumption took an investigation through DHT, peer counts and
qBittorrent's state machine, none of which were involved. Hence a test.
"""

import os
import tempfile
from types import SimpleNamespace

import pytest

from apps.torrents.tasks import _find_downloaded_file, _local_from_remote, _remote_dir

BUNDLE_FILE = "Minerva_Myrient/No-Intro/Nintendo - Nintendo 64 (BigEndian)/game.zip"


@pytest.fixture
def mount(settings):
    root = tempfile.mkdtemp()
    settings.TORRENT_WORKING_DIR = root
    settings.QBITTORRENT_SAVE_PATH = "/downloads"
    return root


def _place(directory: str, name: str) -> str:
    path = os.path.join(directory, *name.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write("rom")
    return path


def test_translation_is_the_exact_inverse_of_remote_dir(mount):
    """The two must stay a pair. _remote_dir tells qBittorrent where to save;
    this reads that same location back in our own terms."""
    assert _local_from_remote(_remote_dir(134)) == os.path.join(mount, "134")


def test_a_trailing_slash_does_not_change_the_answer(mount):
    assert _local_from_remote("/downloads/134/") == os.path.join(mount, "134")


def test_the_save_root_maps_to_the_working_root(mount):
    assert _local_from_remote("/downloads") == mount


def test_a_path_outside_our_mount_has_no_local_equivalent(mount):
    """Better to admit we cannot place it than to invent a path — the caller
    falls back, and _sweep_torrent_dir refuses to delete."""
    assert _local_from_remote("/somewhere/else/134") is None
    assert _local_from_remote("") is None


def test_an_adopted_torrents_file_is_found_in_the_adding_tasks_directory(mount):
    """The actual bug: task 137 rode a torrent task 134 had added, so its
    file was under 134's save path the whole time."""
    expected = _place(os.path.join(mount, "134"), BUNDLE_FILE)
    adopting_task = SimpleNamespace(id=137)

    found = _find_downloaded_file(adopting_task, SimpleNamespace(save_path="/downloads/134"), BUNDLE_FILE)

    assert found == expected


def test_the_tasks_own_directory_is_still_searched(mount):
    """Fallback for a torrent this task added itself, and for anything
    registered before the translation existed."""
    expected = _place(os.path.join(mount, "140"), BUNDLE_FILE)
    task = SimpleNamespace(id=140)

    found = _find_downloaded_file(task, SimpleNamespace(save_path="/unmappable"), BUNDLE_FILE)

    assert found == expected


def test_the_torrents_save_path_wins_over_the_tasks_own_directory(mount):
    """Both can exist at once — a stale file left in the task's own directory
    must not shadow the one the torrent actually wrote."""
    _place(os.path.join(mount, "141"), BUNDLE_FILE)
    from_torrent = _place(os.path.join(mount, "134"), BUNDLE_FILE)
    task = SimpleNamespace(id=141)

    found = _find_downloaded_file(task, SimpleNamespace(save_path="/downloads/134"), BUNDLE_FILE)

    assert found == from_torrent


def test_a_genuinely_absent_file_still_reports_missing(mount):
    """The failure this fix removed was a false negative; the true negative
    has to survive."""
    task = SimpleNamespace(id=142)

    assert _find_downloaded_file(task, SimpleNamespace(save_path="/downloads/134"), BUNDLE_FILE) is None
