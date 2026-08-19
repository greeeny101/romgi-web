# Known issues / outstanding verification

Everything in the 6-phase build plan is implemented. This file lists what
has **not** been verified against the real thing (usually for lack of
credentials or network access in the sandbox this was built in), what was
**deliberately left unimplemented**, and what's only been **smoke-tested**
rather than exercised at real scale/duration. Treat this as a punch list
before relying on any of it in production.

## Never verified against the real external service

These were built as faithful ports of the original app's logic and, where
possible, tested against the *real* API with intentionally-invalid
credentials (confirming request shapes and error parsing are correct) —
but the actual success path was never observed, because no real
credentials were available.

- **Real-Debrid / TorBox** (`backend/apps/downloads/debrid/`). Auth-failure
  and not-configured paths were verified live against both real APIs. The
  full happy path — add a real magnet, poll until cached, unrestrict,
  get a `DebridReady` result — was never observed. **Needs testing with a
  real Real-Debrid or TorBox subscription.**
- **ScreenScraper / SteamGridDB** (`backend/apps/metadata/providers/`).
  Same situation: invalid-credential error paths confirmed live, but no
  real successful game lookup was ever performed. **Needs testing with a
  real registered ScreenScraper account and/or SteamGridDB API key.**
- **A real BitTorrent download to completion.** qBittorrent mechanics
  (selective per-file download, never-seed-after-completion, torrent
  removal) were proven with a deterministic locally-built torrent with no
  network dependency. Peer connectivity is now fully proven live too — a
  well-known control torrent (an official Ubuntu ISO) downloaded with
  real peers once the DNS bug below was fixed, *and* a real MiNERVA
  magnet was confirmed working end-to-end afterward (the one MiNERVA
  torrent that stayed at zero peers this session, `1942`/FBNeo, turned
  out to just have no current seeders for that specific file — a
  different MiNERVA entry downloaded correctly). Still not watched all
  the way to 100% completion, but the download-in-progress path is now
  solidly verified.

## Deliberately unimplemented / scoped down

- **Torrent `.torrent`-file fallback.** The debrid and qBittorrent paths
  are both magnet-only. If a `catalog.Torrent` row ever has no `magnet`
  (only a `.torrent` file), downloads for it will fail outright. MiNERVA,
  the only torrent source in scope, always provides a magnet, so this
  hasn't mattered in practice — but it's a real gap if that assumption
  changes.
- **Myrient-specific download headers.** The original Dart app
  special-cased `myrient.erista.me` URLs with extra `Referer`/`Origin`
  headers and a different HTTP client to dodge anti-bot throttling on that
  host specifically. This was not ported — `backend/apps/downloads/tasks.py`
  treats every HTTP host identically. If a source ever links to
  myrient.erista.me, downloads from it may fail or get throttled where the
  original app succeeded. (MarioCube, the only source with real ingested
  data in this environment, is unaffected — downloads from it were
  verified working end-to-end.)
- **Staged downloads are always on local disk**, in dev *and* production,
  even though `production.py` configures S3-compatible object storage for
  Django's general-purpose file storage. The download/staging pipeline was
  never wired to use it: HTTP Range-resumable, incrementally-written
  downloads don't map cleanly onto S3's write-once object model, and there
  was no real S3/MinIO endpoint available to build and verify that against
  safely. **In production, `STAGED_FILES_DIR` and `TORRENT_WORKING_DIR`
  must sit on real persistent volumes** (the bundled `docker-compose.yml`
  already does this via named volumes) — a single-node assumption that
  won't survive horizontally scaling the downloads worker across multiple
  machines without further work.
- **`.7z` zip-slip guard is all-or-nothing.** For `.zip` archives, a
  path-traversal entry is skipped individually. For `.7z`, py7zr has no
  streaming per-entry writer to interrupt mid-extraction, so the *whole*
  archive is rejected if *any* entry's path would escape the output
  directory. Strictly safer, just less granular than the original Kotlin
  implementation. Verified against a real path-traversal payload.
- **No email/password-reset flow.** `EMAIL_BACKEND`/`EMAIL_HOST`/etc. are
  configured in `production.py` but nothing in the app sends email yet —
  no password reset, no email verification, no notifications. These
  settings exist for future use only.
- **Choosing a download folder is Chromium-only.** The Library's Downloaded
  tab can save straight into a folder the user picks once
  (`frontend/src/lib/downloadTarget.ts`), which needs the File System Access
  API — Chrome/Edge. Firefox and Safari have no `showDirectoryPicker`, so
  the picker hides itself there and saving falls back to the blob-URL anchor
  download into the browser's own download directory. There is no polyfill
  worth having: the alternative would be a per-file "Save as" dialog, which
  is what the picker exists to avoid.
- **No integrity checking of downloaded ROMs.** There is no checksum
  anywhere — `DownloadTask` and `catalog.Link` have no hash field, and the
  No-Intro parser reads titles only, not DAT `crc/md5/sha1` attributes. The
  Library's old "Verify" button implied otherwise but was a bare
  `os.path.exists()` (removed — see below). The one real integrity check in
  the pipeline is the `Content-Length` comparison at the end of
  `http_download`, and even that is skipped when the server sends no
  `Content-Length`. Note `link_size` can never substitute for it: it comes
  from a rounded human string ("1.4G"), as the comment on
  `SIZE_ESTIMATE_TOLERANCE` explains at length.

## Smoke-tested, not exercised at real scale or duration

- **Catalog ingestion**: all four sources have now been run against live
  data and confirmed `ok` on the Sources page — MarioCube (3,062 entries),
  NoPayStation (14,268 entries / 28,528 links, `psv`), Internet Archive
  (303 entries, `gc`), MiNERVA (11,170 entries, `ps1`). Each of the first
  three had a real, silently-broken bug fixed along the way (a live
  third-party site/API having drifted from what the scraper assumed —
  not something introduced during the port), fixed and re-verified before
  being marked working here:
  - **MarioCube**: the row-parsing regex no longer matched the site's
    current table markup — every fetch silently parsed zero entries.
  - **NoPayStation**: generated RAP/ZRIF key files used to link to
    `raw.githubusercontent.com/caprado/romgi/...` — the *original* app's
    fork, matching its now-abandoned "commit the built catalog back to
    GitHub" model. Every generated link 404ed. Fixed: keys are now written
    to `NOPAYSTATION_KEYS_DIR` and proxied by a new endpoint,
    `apps.ingestion.api.get_ingestion_key` — same "always proxy, never
    expose the raw path" pattern `apps.downloads.api` uses for staged
    downloads.
  - **MiNERVA**: the separate `assets/index.txt.gz` artefact 404s now —
    MiNERVA rebuilt their site around a REST API and dropped it. Its only
    job was filtering paths before querying `hashes.db` (still mirrors
    fine, unaffected) for metadata, and `hashes.db` already has the same
    `full_path` column — so the scraper now reads the path list straight
    out of `hashes.db` instead, no separate index file needed at all.
  - Internet Archive's *catalog* scraper (`apps/ingestion/pipeline/sources/internet_archive/`)
    needed no fixes — only the unrelated *login* flow did (see below).
- **The full Docker Compose stack together.** Every service (all 4
  `celery-worker*` split by queue, `django`, `qbittorrent`, `sveltekit`)
  was individually confirmed to build and serve/respond correctly this
  session, including bringing several up concurrently — but there's been
  no sustained/concurrent load test (ingestion + downloads + torrents +
  credential/metadata calls all happening at once).
- **CHD conversion of disc downloads.** All 15 affected downloads converted
  successfully and three were spot-checked with `chdman verify` (raw and
  overall SHA1 both pass). The four extraction outcomes — disc set → `.chd`,
  single ROM → the ROM, multi-file set → the archive, ROM-plus-documentation
  → the ROM rather than the larger image — are covered by a scratch-database
  run of `extract_archive_task` inside the container. What that does *not*
  prove: that a converted `.chd` boots in an emulator (never launched one),
  or that conversion behaves under load. It runs on the `downloads` queue and
  is CPU-heavy and minutes-long per disc, so several concurrent completions
  will contend with active transfers. Note also that conversion writes the
  `.chd` beside the extracted tracks and only deletes them on success, so
  **peak disk use is roughly the extracted set plus the finished image** —
  `STAGED_FILES_DIR` needs headroom for that, not just the final file.
- **CHD is applied to any platform whose archive carries a disc sheet**, not
  to an allowlist of platforms known to want it. That is a deliberate
  simplification: a `.cue`/`.gdi`/`.toc` means the content is a CD by
  definition, and the mainstream CD cores read `.chd` directly. Only
  confirmed against Dreamcast rips, which is all the live data covers — if a
  platform's core turns out to want the raw sheet and tracks, this needs a
  per-platform opt-out alongside `extract_disabled_platforms`.
- **The reworked Library "Downloaded" tab has not been driven in a browser.**
  Sorting, the Downloaded/Saved badges, the availability state and the folder
  picker all pass `svelte-check` and a production build, and their backend
  fields are verified against a scratch database — but no part of that UI has
  been clicked. Specifically unproven: that the folder picker's handle
  survives a page reload (Chrome drops a directory grant when the tab closes,
  so `ensureFolder` re-prompts — the reprompt path is untested), and that the
  `Content-Disposition` fix above actually lands a correctly-named file in a
  real browser.
- **The `Saved` badge records retrieval, not local presence.** It reads
  `first_retrieved_at`, stamped server-side when the bytes are pulled, so it
  says *you have fetched this* rather than *this file is on this machine*.
  Saving on one computer shows as saved on another, and deleting the file
  afterwards doesn't clear it. With a chosen save folder the app could check
  that folder for the file and reflect real presence, which would be
  accurate but Chromium-only and only once a folder is picked.
- **Beat-scheduled cadences.** `poll_active_torrents` (3s),
  `dispatch_pending_downloads` (5min), `cleanup_expired_staged_files`
  (hourly), `run_full_ingestion` (weekly, Sun 03:00 UTC), `gc_old_builds`
  (daily, 04:00 UTC), `internet_archive_revalidate` (daily, 05:00 UTC) —
  all confirmed to *fire* correctly via a short-duration Beat smoke test,
  but none observed running unattended over their real-world interval.

## Fixed since the original build — verified against live data

- **Internet Archive login** (`backend/apps/credentials/services/internet_archive.py`)
  is now verified end-to-end with a real account: login succeeds, S3 keys
  are scraped from `s3.php`, and the resulting `EncryptedCredential` row
  persists with `status: ok`. Two real, unrelated bugs had to be fixed to
  get there:
  - `archive.org/account/login` had been rewritten as a client-rendered
    SPA at some point after this was first ported — a plain
    `requests.post()` of the old form-POST shape no longer works at all
    (confirmed live: the page has no `<form>`/`<input>` markup until JS
    renders it; the real submit target is a JSON endpoint,
    `POST /services/account/login/`, gated by a CSRF JWT only minted
    client-side). Login now drives the real page with Playwright instead.
    `s3.php` itself is still classic server-rendered HTML and was
    unaffected.
  - The Playwright browser's default fingerprint (`navigator.webdriver =
    true`, `"HeadlessChrome"` in the User-Agent) got login attempts
    silently rejected with the *same generic error* a genuinely wrong
    password gets — confirmed by re-testing with credentials already
    verified to work in a real browser. Fixed with a real desktop Chrome
    UA, `--disable-blink-features=AutomationControlled`, and an init
    script masking `navigator.webdriver`.

## Fixed while debugging a real stuck download

A user report ("MiNERVA torrent stuck at 0%, downloads page shows nothing
happening") led to three real, unrelated bugs:

- **qBittorrent's WebUI password drifts from `.env` on every fresh
  container** — it auto-generates a new random temp password each time
  (see the README's "first qBittorrent login" step), and if that's never
  synced to match `QBITTORRENT_PASSWORD`, every download attempt fails
  auth. qBittorrent's own brute-force protection then bans the caller's
  IP after 5 failed attempts (`web_ui_max_auth_fail_count`, 1hr ban by
  default) — and since `apps.torrents.tasks.add_torrent` had no error
  handling around the qBittorrent client call, that ban crashed the task
  silently, leaving the `DownloadTask` stuck at `status="downloading"`
  forever: no error shown, no automatic retry, and no way to manually
  retry either (the retry endpoint only accepts `status="failed"`). Fixed
  `add_torrent` to catch any qBittorrent error and fail the task cleanly
  (and therefore retryably) instead.
- **Internet Archive login state was never actually checked during
  download failover.** `apps.downloads.tasks._find_failover_link` called
  `rank_links(links, settings_obj)` — omitting the third argument,
  `ia_logged_in`, which silently defaulted to `False`. Every IA-gated link
  was treated as unusable even for a user with a valid, working IA
  session (confirmed live: a real logged-in user's torrent failover
  landed on an IA link and was rejected with "Internet Archive login
  required" anyway). Fixed to look up the user's real
  `EncryptedCredential`/`internet_archive.is_logged_in()` state.
- **`linuxserver/qbittorrent` (Alpine/musl) couldn't resolve any external
  DNS at all under Docker Desktop for Mac's networking** — confirmed live
  by a raw UDP packet to Docker's own embedded resolver (127.0.0.11:53)
  getting zero response from that container specifically, while the same
  test from the Debian-based `django` container worked fine. This broke
  *every* peer-discovery mechanism silently (DHT bootstrap node lookups
  and HTTP/UDP tracker announces both need DNS), not just MiNERVA's
  trackerless magnets — even a real, heavily-seeded control torrent (an
  Ubuntu ISO, added directly with its real tracker list) got zero peers
  until this was fixed. This is a known class of issue (Alpine/musl DNS
  resolution under Docker Desktop's network virtualization); worked
  around by pointing the `qbittorrent` service at public DNS directly
  (`dns: [1.1.1.1, 8.8.8.8]` in `docker-compose.yml`) rather than relying
  on Docker's embedded resolver. Also published the BitTorrent peer port
  (6881, TCP+UDP) — was previously not published at all — though the DNS
  fix turned out to be the actual root cause.

## Fixed while testing what a saved download actually gives you

A user report ("I've downloaded a load of ROMs and can't tell what I've
saved") turned into three real bugs, all of which made a download *look*
complete while handing over something unusable.

- **Every saved file lost its extension.** `Virtua Tennis (USA).chd` saved
  as `Virtua Tennis` — the display title, which carries no extension by
  design. The server was never at fault: `download_file` sets
  `Content-Disposition` correctly and it is on the wire. But the SPA and the
  API are different origins and `Content-Disposition` is not a
  CORS-safelisted response header, so `res.headers.get()` returned `null` to
  JavaScript regardless, `apiDownload`'s filename came back `null` on every
  save, and both callers fell back to `DownloadTask.title`. Fixed with
  `CORS_EXPOSE_HEADERS = ["Content-Disposition"]`. Worth internalising: a
  header the browser refuses to reveal is indistinguishable, from the
  client, from one that was never sent — nothing in the frontend could have
  detected this.
- **Multi-file ROM sets were served one member at a time.** A download
  serves exactly one file, but extraction ended in
  `extraction._pick_result` — the largest extracted file. Correct for an
  archive holding a single ROM, silently wrong for anything whose members
  are only usable together. Two shapes hit this:
  - *CD rips.* A `.cue` plus N `.bin` tracks came out as the biggest track,
    orphaning the sheet and every other track. Confirmed live: 15 of the 16
    extracted downloads were in this state, and the user reported that
    `.chd` titles played while `.bin` ones did not. Disc sets are now
    collapsed into a single `.chd` by `chdman` (`apps/downloads/chd.py`,
    `mame-tools` in the Dockerfile), which is both one file and a fraction
    of the size — Ready 2 Rumble Boxing went from 1.2GB of loose tracks to
    376MB.
  - *Arcade sets.* A zip of numbered chip dumps (`3.bin`, `5.bin`, …) with
    no sheet, where the emulator wants the zip itself under those exact
    filenames. Nothing to collapse those into, so the rule is now general:
    if extraction yields several files that belong together, the archive
    *is* the deliverable and the extracted copy is discarded. This required
    deleting the archive *after* that decision rather than before it.
  - A quieter variant fell out of the same line of code: choosing by size
    meant a small ROM shipped beside a large screenshot served the
    **screenshot**.
    Selection now ignores documentation (`.txt`, `.nfo`, `.jpg`, …), so a
    readme can't make a single-ROM archive look like a set.
- **"Verify" did nothing useful and reported nothing.** It was a bare
  `os.path.exists()` on the staged file — no checksum, no DAT comparison —
  and the UI dropped its `message` on the floor, so success looked like
  nothing had happened and failure made the row silently vanish. Removed.
  The state it was checking is now always visible instead (`file_available`
  / `expires_at`: "expires in 6h", or "File removed from server" with Save
  disabled). `download_file` blanks `staged_file` on a 404, which is the
  self-correction the endpoint used to provide — `cleanup_expired_staged_files`
  is hourly and can't see a file removed out from under it.

`manage.py convert_disc_downloads` repairs downloads that finished before
this. Everything was still on disk under `extracted/`, so all 15 converted
in place with nothing re-downloaded.

## Fixed while writing this document — worth a second look

Two real gaps surfaced while double-checking the "how do I run this"
instructions, both now fixed and verified:

- **`frontend/Dockerfile` didn't exist at all.** `docker compose up` would
  have failed outright trying to build the `sveltekit` service. Added; the
  image now builds and serves correctly on port 5174.
- **The full Compose stack had never actually been brought up together**
  before this pass — every phase up to now was verified via local
  host processes (venv/npm) against only Postgres/Redis in Docker. It's
  now confirmed working end-to-end: `django` migrates, registers the Beat
  schedule, and serves the API; a `celery-worker` connects and registers
  all tasks; `sveltekit` serves the frontend — all via `docker compose up`.

## Also worth knowing

- **Manual per-source ingestion re-runs** (a "Run" button per row on the
  Sources page) are now supported — `POST /api/ingestion/sources/{id}/run`,
  `apps.ingestion.tasks.run_single_source`. Since `CatalogBuild` is
  normally an atomic full-catalog snapshot (every ingestion run is
  expected to cover every source), a naive single-source run would wipe
  out every other source's data. `orchestrator.carry_forward_other_sources`
  avoids that by seeding the new build with every other source's
  Entry/Link data from the current active build before re-scraping just
  the requested source — verified live: re-running `mariocube` alone
  produced a build with byte-identical entry counts across all four
  sources (226,573 total, unchanged) except mariocube's own fresh scrape.
- **Arcade downloads taken before the extraction fix must be re-downloaded.**
  Disc sets were repairable in place because their tracks were still on disk,
  but an arcade set's archive had already been deleted after extraction, so
  only one chip dump survives and the zip cannot be reconstructed. One row is
  in this state in the dev data (`1942 (Revision A, bootleg)`, `fbneo`, still
  pointing at `extracted/14.bin`). Re-downloading replaces the row in place —
  `enqueue` discards the previous attempt — so there's nothing to clean up
  first.
- `qbittorrent-api` is pinned to `>=2026.8` — an older pin
  (`<2025.0`, the original guess) can't parse a successful login response
  from qBittorrent 5.x, which is what `linuxserver/qbittorrent:latest`
  currently pulls. If that image jumps to a qBittorrent version with
  further Web API changes, this may need re-verifying.
