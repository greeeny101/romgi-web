"""
finalize stops the torrent before reading its file, and _await_stopped is
what makes that ordering mean anything.

client.stop() only asks. Without waiting for the daemon to confirm, the read
lands back inside the window the stop was added to close — and the result is
not an error but a file of exactly the right length whose middle is wrong,
which surfaces much later as a corrupt archive (task 135: valid PK header,
no trailing zeros, "invalid stored block lengths" partway through inflate).
Nothing between here and there reports a problem.

The timeout behaviour is equally worth pinning: it must fall through and let
the download finish rather than raise, because abandoning a fully
transferred torrent over a slow daemon would be a worse failure than the one
being guarded against.
"""

from types import SimpleNamespace

import pytest

from apps.torrents import tasks


class FakeClient:
    """Reports `states` in order, one per info() call, then repeats the last."""

    def __init__(self, states):
        self.states = list(states)
        self.calls = 0

    def info(self, torrent_hash):
        self.calls += 1
        state = self.states[min(self.calls - 1, len(self.states) - 1)]
        return None if state is None else SimpleNamespace(state=state)


@pytest.fixture
def fake(monkeypatch):
    def install(states):
        client = FakeClient(states)
        monkeypatch.setattr(tasks, "client", client)
        monkeypatch.setattr(tasks.time, "sleep", lambda _s: None)
        return client

    return install


def test_returns_as_soon_as_the_daemon_reports_stopped(fake):
    client = fake(["stoppedUP"])

    assert tasks._await_stopped("abc") is True
    assert client.calls == 1


def test_waits_through_the_states_before_the_stop_lands(fake):
    """stop() is asynchronous — the torrent is still uploading for a moment
    after the request is accepted."""
    client = fake(["stalledUP", "stalledUP", "stoppedUP"])

    assert tasks._await_stopped("abc") is True
    assert client.calls == 3


def test_a_torrent_already_gone_counts_as_stopped(fake):
    """Nothing is holding the file open if the torrent isn't there."""
    fake([None])

    assert tasks._await_stopped("abc") is True


def test_the_paused_spelling_is_accepted(fake):
    """qBittorrent 5.x renamed paused* to stopped*; an older daemon must not
    hang here for the full timeout on every single download."""
    fake(["pausedUP"])

    assert tasks._await_stopped("abc") is True


def test_a_timeout_falls_through_instead_of_raising(fake):
    """A copy that might be stale still beats abandoning a download that has
    already transferred — extraction is the backstop."""
    fake(["stalledUP"])

    assert tasks._await_stopped("abc", timeout=0.01) is False
