"""
Who owns a torrent, and which of its files anyone actually wants.

Two unrelated tables now put torrents into the same qBittorrent daemon —
downloads.DownloadTask (one wanted file out of a shared MiNERVA bundle) and
romsets.RomSetDownload (a whole archive.org item). qBittorrent dedupes by
infohash, so a single torrent can be owned by rows in either table or both,
and every stop/delete/priority decision has to consider all of them.

Before this module existed, all four decision points consulted DownloadTask
alone. Against a romset on the same infohash each one failed silently rather
than loudly: finalize and cancel would stop and delete a live set, and the
priority pass would set every one of its files to "do not download",
leaving a row stuck at "downloading" with no error and no progress.
"""

from __future__ import annotations

from apps.downloads.models import DownloadTask

from .client import PRIORITY_DOWNLOAD, PRIORITY_SKIP


def _active_romsets(torrent_hash: str, exclude_romset_id: int | None = None):
    # Imported lazily: apps.romsets imports this package's client, so a
    # module-scope import here would close the cycle.
    from apps.romsets.models import ACTIVE_STATUSES, RomSetDownload

    qs = RomSetDownload.objects.filter(status__in=ACTIVE_STATUSES, infohash=torrent_hash)
    if exclude_romset_id is not None:
        qs = qs.exclude(id=exclude_romset_id)
    return qs


def torrent_in_use(
    torrent_hash: str,
    *,
    exclude_task_id: int | None = None,
    exclude_romset_id: int | None = None,
) -> bool:
    """True if anything other than the excluded row still needs this torrent.

    Note the asymmetry: a *paused* DownloadTask does not hold its torrent
    (downloads.api pauses by stopping it), but a paused RomSetDownload does —
    it keeps its place and its partial data on disk, so removing the torrent
    under it would lose both.
    """
    if not torrent_hash:
        return False

    tasks = DownloadTask.objects.filter(status="downloading", torrent_hash=torrent_hash)
    if exclude_task_id is not None:
        tasks = tasks.exclude(id=exclude_task_id)
    if tasks.exists():
        return True

    return _active_romsets(torrent_hash, exclude_romset_id).exists()


def _romset_wanted_file_ids(romset, files) -> tuple[set[int], set[int]]:
    """`(wanted_ids, known_ids)` for one set against qBittorrent's file list.

    Matched by name, never by index: the metadata API, the raw torrent and
    qBittorrent's pad-filtered view disagree on both membership and ordering.
    qBittorrent reports paths prefixed with the torrent's root directory
    (which for an archive.org item is the identifier); RomSetFile.path stores
    them without it.
    """
    by_name = {f.name: f for f in files}
    wanted: set[int] = set()
    known: set[int] = set()
    for path, is_wanted in romset.files.values_list("path", "wanted"):
        match = by_name.get(f"{romset.identifier}/{path}") or by_name.get(path)
        if match is None:
            continue
        known.add(match.id)
        if is_wanted:
            wanted.add(match.id)
    return wanted, known


def desired_priorities(torrent_hash: str, files) -> dict[int, int]:
    """`{file_id: priority}` reflecting every owner of this torrent at once.

    Computed from all owners rather than just the caller: a shared torrent
    means another row may already have its own file selected, and setting
    that back to skip would stall it.
    """
    task_indexes = set(
        DownloadTask.objects.filter(status="downloading", torrent_hash=torrent_hash).values_list(
            "link_torrent_file_index", flat=True
        )
    )
    has_tasks = bool(task_indexes)
    download_everything = None in task_indexes

    wanted_ids: set[int] = set()
    known_ids: set[int] = set()
    if has_tasks:
        wanted_ids |= {f.id for f in files if f.index in task_indexes}

    romsets = list(_active_romsets(torrent_hash))
    for romset in romsets:
        romset_wanted, romset_known = _romset_wanted_file_ids(romset, files)
        wanted_ids |= romset_wanted
        known_ids |= romset_known

    # A file qBittorrent lists that no romset has a row for can only be one
    # the item gained after we recorded its contents — in practice a
    # thumbnail or a metadata sidecar, a couple of hundred KB. Fetching it is
    # free; skipping a file we simply failed to recognise is an
    # unrecoverable silent stall, because the set then never reaches 100%.
    #
    # This leniency is deliberately withheld when a DownloadTask shares the
    # torrent: those are MiNERVA bundles of thousands of games where an
    # unmatched file is a whole ROM, not a thumbnail, and "download it
    # anyway" would pull tens of gigabytes nobody asked for.
    lenient = bool(romsets) and not has_tasks

    def wanted(f) -> bool:
        if download_everything or f.id in wanted_ids:
            return True
        # Unrecognised file under the lenient rule above.
        return lenient and f.id not in known_ids

    return {f.id: (PRIORITY_DOWNLOAD if wanted(f) else PRIORITY_SKIP) for f in files}
