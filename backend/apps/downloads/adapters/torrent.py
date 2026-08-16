from .base import HostAdapter


class TorrentAdapter(HostAdapter):
    """Ports Dart's TorrentAdapter shape. Dispatch itself lives in
    apps.torrents.tasks.add_torrent (qBittorrent), routed there from
    downloads.tasks.start_download."""

    is_torrent = True
    auth_error = "This torrent has no magnet link available"

    def can_start_download(self, task, user) -> bool:
        return bool(task.link_torrent_magnet)
