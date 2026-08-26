# ROM sets

[← back to README](../README.md)

The catalog is per-ROM; **ROM Sets** (`/sets`) is per-*item*. Pick an
emulator, see the romsets published on archive.org, choose what you want out
of one, and it downloads as a unit. Independent of the catalog — a set needs
no ingestion run and creates no `Entry` rows.

**Discovery** is live `advancedsearch.php`, narrowed by a curated
emulator→query map in `backend/apps/romsets/emulators.yml`. Results are
sorted by download count: archive.org's own relevance ranking puts SD-card
images and unrelated shovelware above the set you actually want. Adding an
emulator is a YAML edit; its `platform_id` must be a real `catalog.Platform`
PK, which a system check enforces rather than letting it fail mid-download.

**Transfer is BitTorrent**, using each item's `<identifier>_archive.torrent`
through the same qBittorrent daemon. Selection maps onto per-file priorities,
so deselecting a 5GB file genuinely doesn't fetch it.

**Files land in the library folder directly** — qBittorrent's save path *is*
`<ROM_LIBRARY_DIR>/<platform>/<identifier>/`, so nothing is copied at the end
and a 30GB set doesn't need 60GB of disk to finish. (Extraction is the
exception: `extract_archive` doesn't remove its source, so an extracted set
does need room for both until the archive is deleted — which the space check
accounts for.) Unlike `STAGED_FILES_DIR`, nothing ever sweeps this directory;
it's a library, not a staging area.

| Setting | What it is |
|---|---|
| `ROM_LIBRARY_DIR` | The library as Django/Celery see it |
| `QBITTORRENT_LIBRARY_PATH` | The same directory as qBittorrent sees it — never conflate the two |
| `ROM_LIBRARY_MIN_FREE_BYTES` | Free space a set may never consume (default 2GiB) |

The reserve is enforced on admission, at task start, before extraction, and
continuously while transferring. It matters because a set is the only thing
here that writes tens of gigabytes on one click, onto the same physical disk
Postgres and Redis are writing to — filling it takes the whole stack down
rather than just failing the transfer.

**Restricted items** (archive.org's `loggedin` collection) work, using the
Internet Archive credentials from Settings → Internet Archive. Their metadata
is public but `/download/` is gated, so a set can look browsable and then
fail without a login. archive.org's webseeds are gated too, so these transfer
from peers only — fine when the item is well seeded, stalled when it isn't.

**Re-requesting a set never deletes what it already downloaded.** Deselecting
a file is not passive: qBittorrent is told "do not download", and when the
data is already on disk it removes it. So anything a previous run completed
stays selected regardless of the new request. Removing files is a filesystem
operation you do yourself, never a side effect of asking for a different part
of a set.

Where the library folder lives on the host is set by `ROM_LIBRARY_HOST_PATH` —
see [Installation](installation.md#the-library-folder).
