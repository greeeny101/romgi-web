"""
Disk-space admission control for ROM sets.

A set is the only thing in this app that can write tens of gigabytes on one
user action, and it writes them to a volume the rest of the stack shares.
Filling that volume to the last hundred megabytes doesn't just fail the
download — Postgres and Redis stop being able to write too. So every check
here reserves headroom a set is never allowed to consume, and every check
subtracts what other in-flight sets have already promised to write: without
that term, three concurrent 18 GB sets each pass individually and the volume
still fills.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass

from django.conf import settings as django_settings

from .models import ACTIVE_STATUSES, RomSetDownload


class InsufficientSpace(Exception):
    pass


def human_bytes(value: int) -> str:
    step = 1024.0
    amount = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(amount) < step or unit == "TB":
            return f"{amount:.1f} {unit}" if unit != "B" else f"{int(amount)} B"
        amount /= step
    return f"{amount:.1f} TB"


def _measurable_path(path: str) -> str:
    """`shutil.disk_usage` needs a path that exists. The library directory is
    a mount point in Compose so it always will, but in a dev checkout or a
    test run it may not exist yet — and we deliberately don't create it
    ourselves (qBittorrent runs as uid 1000 and could not write into a
    root-created directory). Walk up to the nearest existing ancestor, which
    is on the same filesystem anyway."""
    candidate = os.path.abspath(path)
    while candidate and not os.path.exists(candidate):
        parent = os.path.dirname(candidate)
        if parent == candidate:
            break
        candidate = parent
    return candidate or os.path.abspath(os.sep)


def free_bytes() -> int:
    return shutil.disk_usage(_measurable_path(django_settings.ROM_LIBRARY_DIR)).free


def committed_bytes(*, exclude_romset_id: int | None = None) -> int:
    """Bytes other in-flight sets still have left to write."""
    qs = RomSetDownload.objects.filter(status__in=ACTIVE_STATUSES)
    if exclude_romset_id is not None:
        qs = qs.exclude(id=exclude_romset_id)
    return sum(max(0, row.total_bytes - row.downloaded_bytes) for row in qs.only("total_bytes", "downloaded_bytes"))


@dataclass(frozen=True)
class SpaceReport:
    free: int
    committed: int
    needed: int
    reserve: int

    @property
    def available(self) -> int:
        return self.free - self.committed - self.reserve

    @property
    def ok(self) -> bool:
        return self.available >= self.needed

    def message(self) -> str:
        return (
            f"Not enough space in the ROM library: needs {human_bytes(self.needed)}, "
            f"{human_bytes(self.available)} usable "
            f"({human_bytes(self.free)} free, {human_bytes(self.committed)} already promised to other sets, "
            f"{human_bytes(self.reserve)} reserved for the system)."
        )


def check_space(needed: int, *, exclude_romset_id: int | None = None) -> SpaceReport:
    return SpaceReport(
        free=free_bytes(),
        committed=committed_bytes(exclude_romset_id=exclude_romset_id),
        needed=max(0, needed),
        reserve=django_settings.ROM_LIBRARY_MIN_FREE_BYTES,
    )


def ensure_space(needed: int, *, exclude_romset_id: int | None = None) -> SpaceReport:
    report = check_space(needed, exclude_romset_id=exclude_romset_id)
    if not report.ok:
        raise InsufficientSpace(report.message())
    return report
