"""
Ports lib/services/host_adapter.dart's `HostAdapter` ABC 1:1 — every method
operates on a `DownloadTask` here (which already carries the snapshotted
link_* fields) rather than a live catalog Link, since after a failover the
task *is* the current link.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apps.accounts.models import User
    from apps.downloads.models import DownloadTask


class HostAdapter:
    is_torrent = False
    auth_error = "Authentication required"

    def prepare_headers(self, headers: dict, task: "DownloadTask") -> None:
        """Mutate `headers` in place before the request is made."""

    def can_start_download(self, task: "DownloadTask", user: "User") -> bool:
        return True

    def on_auth_failure(self, task: "DownloadTask", user: "User") -> None:
        """Called when a request comes back 401/403 mid-download."""
