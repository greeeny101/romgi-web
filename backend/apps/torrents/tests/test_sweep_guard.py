"""
_sweep_torrent_dir removes a directory tree, so its guard is the one thing
here that can destroy data rather than merely fail.

It is handed a path qBittorrent reported, translated back to our mount, and
then deletes it. Every failure mode is silent and unrecoverable: pointed at
the working root it would take every in-flight torrent's data with it, and
pointed outside the mount it would delete something that was never ours.
Nothing downstream would report an error — the files would simply be gone.

Hence a test. The guard is four lines and looks obviously correct, which is
exactly why a later refactor would feel safe removing it.
"""

import os
import tempfile
from types import SimpleNamespace

import pytest

from apps.torrents.tasks import _sweep_torrent_dir


@pytest.fixture
def mount(settings):
    """A throwaway TORRENT_WORKING_DIR standing in for the shared volume."""
    root = tempfile.mkdtemp()
    settings.TORRENT_WORKING_DIR = root
    settings.QBITTORRENT_SAVE_PATH = "/downloads"
    return root


def _populate(directory: str) -> str:
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, "leftover.bin")
    with open(path, "w") as fh:
        fh.write("x")
    return path


def test_a_released_torrents_own_directory_is_swept(mount):
    leftover = _populate(os.path.join(mount, "134"))

    _sweep_torrent_dir(SimpleNamespace(save_path="/downloads/134"))

    assert not os.path.exists(leftover)
    assert os.path.exists(mount), "only the torrent's directory, never the mount itself"


def test_the_working_root_itself_is_never_removed(mount):
    """A torrent saved straight to the root — a misconfiguration, not an
    impossibility — must not take every other torrent's data with it."""
    other_torrents_data = _populate(os.path.join(mount, "still-downloading"))

    _sweep_torrent_dir(SimpleNamespace(save_path="/downloads"))

    assert os.path.exists(other_torrents_data)


def test_a_path_outside_our_mount_is_refused(mount):
    outside = tempfile.mkdtemp()
    precious = _populate(outside)

    _sweep_torrent_dir(SimpleNamespace(save_path="/somewhere/else/134"))

    assert os.path.exists(precious)


def test_traversal_out_of_the_mount_is_refused(mount):
    """The save path is remote input. It is qBittorrent's own report rather
    than a user's, but it is still a string from another process being
    turned into a delete.

    The `..` sequence is computed rather than hardcoded so this genuinely
    resolves to `outside`. A fixed number of `..` segments depends on how
    deep the temp directory happens to sit, and lands on a path that does not
    exist — which rmtree ignores, so the test would pass without the guard
    doing anything.
    """
    outside = tempfile.mkdtemp()
    precious = _populate(outside)
    escape = os.path.relpath(outside, mount)
    assert escape.startswith(".."), "the relative path must really leave the mount"

    _sweep_torrent_dir(SimpleNamespace(save_path=f"/downloads/{escape}"))

    assert os.path.exists(precious)


def test_an_unreported_save_path_is_a_no_op(mount):
    survivor = _populate(os.path.join(mount, "134"))

    _sweep_torrent_dir(SimpleNamespace(save_path=""))

    assert os.path.exists(survivor)
