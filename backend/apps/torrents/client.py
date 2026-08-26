"""
Thin wrapper around qbittorrent-api, isolating the Web API surface the rest
of the app touches. This is the server-side stand-in for the on-device
libtorrent4j engine (TorrentServiceImpl.kt) — see apps.torrents.tasks for
where the selective-per-file-download and never-seed-after-completion
semantics it ported are actually enforced (this module just exposes the
qBittorrent calls those behaviors are built from).
"""

from __future__ import annotations

from dataclasses import dataclass

import qbittorrentapi
from django.conf import settings


@dataclass
class TorrentHandle:
    hash: str
    name: str
    state: str
    progress: float
    downloaded: int
    # Bytes of the *selected* files present on disk. Distinct from
    # `downloaded`, which is qBittorrent's lifetime payload counter and never
    # shrinks even after file priorities narrow the selection back down —
    # only this one is meaningful as "how much of what we asked for is here".
    completed: int
    size: int
    dlspeed: int
    num_seeds: int
    num_leechs: int
    save_path: str


# States a torrent lands in when it can no longer make progress on its own:
# a disk that filled up, or files that vanished underneath it. Neither is in
# FINISHED_STATES, so without an explicit branch a torrent in one of these
# sits at "downloading" forever with no error.
ERROR_STATES = {"error", "missingFiles"}


@dataclass
class TorrentFile:
    id: int
    index: int
    name: str
    size: int
    priority: int
    progress: float


# qBittorrent's file-priority scale (0/1/6/7) — distinct from libtorrent4j's
# 0-7 range used by TorrentServiceImpl.kt.
PRIORITY_SKIP = 0
PRIORITY_DOWNLOAD = 1

# States qBittorrent reports once a torrent has finished downloading and is
# sitting idle or (if something raced our stop() call) actively seeding.
FINISHED_STATES = {"stalledUP", "uploading", "queuedUP", "forcedUP", "pausedUP", "stoppedUP"}


class TorrentClient:
    def __init__(self):
        self._client = qbittorrentapi.Client(
            host=settings.QBITTORRENT_HOST,
            username=settings.QBITTORRENT_USERNAME,
            password=settings.QBITTORRENT_PASSWORD,
        )

    def add(self, *, magnet: str, tag: str, save_path: str) -> None:
        self._client.torrents_add(
            urls=magnet,
            save_path=save_path,
            tags=tag,
            is_paused=False,
            # Belt-and-braces alongside the explicit stop() in
            # finalize_completed_torrent — never seed after completion.
            ratio_limit=0,
            seeding_time_limit=0,
        )

    def add_torrent_file(
        self,
        *,
        data: bytes,
        tag: str,
        save_path: str,
        is_paused: bool = False,
    ) -> None:
        """Add a torrent from its raw `.torrent` bytes rather than a magnet.

        archive.org publishes one per item and no magnet at all, so this is
        the only way in for a ROM set.

        `content_layout="Original"` is pinned rather than left to the
        daemon's default: with `NoSubfolder` configured globally, qBittorrent
        drops the torrent's root directory, and every file path we match
        against by name silently stops matching.

        Note there is no `file_priorities` argument — qbittorrent-api
        documents it as unusable when uploading torrent files, which is why
        callers add paused, set priorities, then resume.
        """
        self._client.torrents_add(
            torrent_files=data,
            save_path=save_path,
            tags=tag,
            is_paused=is_paused,
            content_layout="Original",
            # Same belt-and-braces as add() — never seed after completion.
            ratio_limit=0,
            seeding_time_limit=0,
        )

    def find_by_tag(self, tag: str) -> TorrentHandle | None:
        results = self._client.torrents_info(tag=tag)
        return self._to_handle(results[0]) if results else None

    def info(self, torrent_hash: str) -> TorrentHandle | None:
        results = self._client.torrents_info(torrent_hashes=torrent_hash)
        return self._to_handle(results[0]) if results else None

    def files(self, torrent_hash: str) -> list[TorrentFile]:
        """qBittorrent's own file indexes, not this list's ordinals.

        The two agree today (the daemon returns a dense, index-ordered list),
        but only the daemon's index is addressable by set_file_priority, and
        it is the one qbittorrent-api itself copies into `id`. Note the index
        space has BEP-47 padding files removed — qBittorrent filters them out
        entirely — so it lines up with neither the raw torrent's file list
        nor archive.org's metadata listing. Match by name, not position.
        """
        return [
            TorrentFile(id=f.id, index=f.index, name=f.name, size=f.size, priority=f.priority, progress=f.progress)
            for f in self._client.torrents_files(torrent_hash=torrent_hash)
        ]

    def list_by_tag(self, tag: str) -> list[TorrentHandle]:
        """Every torrent carrying `tag`, in one call.

        Lets the ROM-set poll beat fetch all active sets per tick instead of
        one round trip per set against a single-threaded WebUI.
        """
        return [self._to_handle(t) for t in self._client.torrents_info(tag=tag)]

    def set_file_priority(self, torrent_hash: str, file_id: int, priority: int) -> None:
        self._client.torrents_file_priority(torrent_hash=torrent_hash, file_ids=file_id, priority=priority)

    def stop(self, torrent_hash: str) -> None:
        self._client.torrents_stop(torrent_hashes=torrent_hash)

    def resume(self, torrent_hash: str) -> None:
        self._client.torrents_start(torrent_hashes=torrent_hash)

    def delete(self, torrent_hash: str, delete_files: bool = False) -> None:
        self._client.torrents_delete(torrent_hashes=torrent_hash, delete_files=delete_files)

    @staticmethod
    def _to_handle(t) -> TorrentHandle:
        return TorrentHandle(
            hash=t.hash,
            name=t.name,
            state=t.state,
            progress=t.progress,
            downloaded=t.downloaded,
            completed=getattr(t, "completed", 0) or 0,
            size=t.size,
            dlspeed=t.dlspeed,
            num_seeds=t.num_seeds,
            num_leechs=t.num_leechs,
            save_path=t.save_path,
        )


client = TorrentClient()
