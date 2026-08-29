"""
_reported_progress decides what a downloading row shows, and every way it
can go wrong is quiet.

Reverting it to qBittorrent's per-file figure doesn't break anything that
fails a check — the download still completes, the bytes are still right at
the end. It just goes back to reading as frozen at zero for the whole
transfer, which is what it was written for and is indistinguishable from a
stalled swarm. Letting the estimate reach 1.0, on the other hand, would
finish the task while pieces were still being verified, and letting it fall
below the file's own verified progress would run the bar backwards.

The numbers below are one real transfer: three ROMs queued together out of
MiNERVA's 1,193-file N64 bundle, sampled every two seconds. The three
selected files total 27,604,950 bytes and share a 48MiB piece region.
"""

from dataclasses import dataclass

from apps.torrents.tasks import _reported_progress

REGION = 50_331_648  # info.size — the piece region the selection spans
FILE_SIZE = 6_863_396  # smaller than the 8MiB piece, so its own progress is 0.0 or 1.0


@dataclass
class FakeInfo:
    size: int
    completed: int


@dataclass
class FakeFile:
    size: int
    progress: float


def test_a_file_smaller_than_a_piece_still_advances():
    """The case with no per-file signal at all.

    Every sample below reported file progress of exactly 0.0 — that is the
    observation, not a simplification — while the region went from 819KB to
    45MB.
    """
    ours = FakeFile(size=FILE_SIZE, progress=0.0)
    seen = [
        _reported_progress(FakeInfo(REGION, done), ours)
        for done in (819_200, 4_063_232, 11_206_656, 24_215_552, 45_350_912)
    ]

    assert seen == sorted(seen)
    assert seen[0] > 0.0, "the row must not sit at zero while the region fills"
    assert seen[-1] > seen[0] * 4


def test_the_files_own_verified_progress_is_a_floor():
    """A piece this file has actually verified is never given back, even
    when the region as a whole is further behind. Measured: file 164 read
    0.588 while the region was at 0.94, but the reverse ordering is what
    this guards."""
    ours = FakeFile(size=14_269_685, progress=0.588)

    assert _reported_progress(FakeInfo(REGION, 10_846_208), ours) == 0.588


def test_the_estimate_never_reaches_completion_on_its_own():
    """The region hit 100% at 22:47:20 while two of the three files still
    read 0.0; they verified 6 and 13 seconds later. progress == 1.0 marks
    the task finished, so reporting it here would copy a file out mid-write.
    """
    ours = FakeFile(size=FILE_SIZE, progress=0.0)

    assert _reported_progress(FakeInfo(REGION, REGION), ours) < 1.0


def test_a_verified_file_reports_exactly_complete():
    ours = FakeFile(size=FILE_SIZE, progress=1.0)

    assert _reported_progress(FakeInfo(REGION, REGION), ours) == 1.0


def test_a_torrent_with_no_wanted_size_yet_falls_back():
    """Between the add and the priority pass there is no selection, so the
    ratio has nothing to say."""
    ours = FakeFile(size=FILE_SIZE, progress=0.0)

    assert _reported_progress(FakeInfo(0, 0), ours) == 0.0
