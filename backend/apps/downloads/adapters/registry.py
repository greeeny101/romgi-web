"""Ports lib/services/host_adapter.dart's `HostAdapterRegistry.adapterFor`
dispatch order exactly: torrent check first, then Internet Archive by
source id or URL, else the default HTTP adapter."""

from .http import DefaultHttpAdapter
from .internet_archive import InternetArchiveAdapter
from .torrent import TorrentAdapter


def _is_internet_archive_url(url: str) -> bool:
    return "archive.org" in url


class HostAdapterRegistry:
    def __init__(self):
        self._default = DefaultHttpAdapter()
        self._internet_archive = InternetArchiveAdapter()
        self._torrent = TorrentAdapter()

    def adapter_for(self, task):
        if task.link_is_torrent:
            return self._torrent
        if task.link_source_id == "internet_archive" or _is_internet_archive_url(task.link_url):
            return self._internet_archive
        return self._default


registry = HostAdapterRegistry()
