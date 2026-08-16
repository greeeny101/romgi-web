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
    size: int
    dlspeed: int
    num_seeds: int
    num_leechs: int
    save_path: str


@dataclass
class TorrentFile:
    id: int
    index: int
    name: str
    size: int
    priority: int


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

    def find_by_tag(self, tag: str) -> TorrentHandle | None:
        results = self._client.torrents_info(tag=tag)
        return self._to_handle(results[0]) if results else None

    def info(self, torrent_hash: str) -> TorrentHandle | None:
        results = self._client.torrents_info(torrent_hashes=torrent_hash)
        return self._to_handle(results[0]) if results else None

    def files(self, torrent_hash: str) -> list[TorrentFile]:
        return [
            TorrentFile(id=i, index=i, name=f.name, size=f.size, priority=f.priority)
            for i, f in enumerate(self._client.torrents_files(torrent_hash=torrent_hash))
        ]

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
            size=t.size,
            dlspeed=t.dlspeed,
            num_seeds=t.num_seeds,
            num_leechs=t.num_leechs,
            save_path=t.save_path,
        )


client = TorrentClient()
