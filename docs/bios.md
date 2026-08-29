# BIOS files

[← back to README](../README.md)

A PlayStation, Saturn, Dreamcast, CD-i or 3DO emulator will not boot without
the console's BIOS, and the catalog has no way to express one. **BIOS**
(`/bios`) is the sibling of [ROM Sets](romsets.md) for exactly that: pick a
system, see what archive.org publishes, tick the files you need, and they
land in your library ready to drop into an emulator's system folder.

**Discovery** is live `advancedsearch.php`, narrowed by a curated
system→query map in `backend/apps/bios/sources.yml`. The trick that makes
the results usable is scoping the term to the *title*: `bios AND (playstation
OR psx OR ps1)` returns 530 items whose top five include two Redump romsets
and a MAME reference set, while `title:(bios) AND (…)` returns 120 of which
every one on the first page is a genuine BIOS item. Adding a system is a
YAML edit; its `platform_id` must be a real `catalog.Platform` PK, which a
system check enforces rather than letting it fail mid-download.

**Transfer is plain HTTP**, one `GET` per file straight from
`archive.org/download/`, performed by the Celery worker itself. This is the
main thing that differs from ROM sets: a BIOS file is kilobytes to a few
megabytes, and a torrent's handshake and peer discovery would dwarf the
transfer. It also means there is no qBittorrent involved, no infohash to
arbitrate, and no periodic poll — the task owns the bytes, so it reports its
own progress over the `ws/bios/` WebSocket.

**Files land in `<ROM_LIBRARY_DIR>/bios/<platform>/`** — a single tree you
can point an emulator at or rsync to a handheld, kept out of the way of the
per-platform romset folders. An item with no single platform (the
multi-system packs) goes to `bios/_unsorted/`. Turning on **Extract** unpacks
any `.zip`/`.7z` in place and removes the archive, which is the common case:
a lot of BIOS items ship as one zip whose *contents* are what the emulator
wants.

**Every file is checksummed.** archive.org publishes an md5 per file and it
is verified after the transfer; a mismatch removes the file and fails the
request loudly. This matters more here than for a ROM — a corrupt BIOS
doesn't announce itself, it makes an emulator boot to a black screen with
nothing to point at. The same check means a re-request of an item you
already have verifies what's on disk instead of re-fetching it.

**A stalled transfer recovers itself.** Each file gets three retries on a
retryable error before the request gives up, and a retry resumes from the
partial rather than restarting the file — a pack is many small transfers, so
it gets many independent chances to hit an archive.org stall, and one 60s
read timeout at file 42 of 115 should not throw away the first 41. Separately,
a beat task (`dispatch_pending_bios`, every 5 minutes) re-dispatches any
request left sitting in `pending`, which is what happens when the broker
hiccups or a worker is killed holding the start message. Re-dispatching is
safe: the task claims its row with a conditional `UPDATE`, so a duplicate
returns instead of starting a second transfer. The same safety net exists for
single-ROM downloads.

**Pausing and cancelling** work on the running transfer: the worker polls
its own row between chunks, so pausing stops it and leaves the partial file
for a `Range` resume rather than starting over. Cancelling removes the queue
entry and leaves whatever was already downloaded — the library folder is
yours, and deleting files is never a side effect of changing your mind about
a selection. Unlike a ROM set, deselecting a file really is passive here:
nothing on disk is ever removed to satisfy a narrower request.

**Restricted items** (archive.org's `loggedin` collection) use the Internet
Archive credentials from Settings → Internet Archive, through the same
credential-preserving session the rest of the app uses. Their metadata is
public but `/download/` is gated, so an item can look browsable and then
fail without a login.

**There is no disk-space admission control here, deliberately.** ROM sets
have one because a set is the only thing in this app that writes tens of
gigabytes on one click onto the volume Postgres and Redis share. BIOS items
are megabytes; guarding them would mean carrying that machinery for a risk
that isn't present.

| Setting | What it is |
|---|---|
| `ROM_LIBRARY_DIR` | The library as Django/Celery see it; BIOS files go under `bios/` inside it |
| `ROM_LIBRARY_HOST_PATH` | Where that folder lives on the host (root `.env`, no default) |
