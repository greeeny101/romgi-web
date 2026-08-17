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

- **Internet Archive login** (`backend/apps/credentials/services/internet_archive.py`).
  archive.org was completely unreachable from the dev sandbox (connection
  refused on every attempt, including via a separate fetch tool). The
  login form field names (`username`/`password`/`remember`) are based on
  the long-standing `internetarchive` Python package's conventions, not
  confirmed against archive.org's live markup. The S3-key-scraping step
  (`GET`/`POST /account/s3.php`) that runs after login was also never
  exercised. **Needs a real login attempt with real IA credentials** before
  you trust it.
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
  network dependency. Separately, a real magnet add + metadata resolution
  + file-priority-setting was verified against a real, live, well-seeded
  torrent. The two were never combined — no full multi-peer download was
  watched all the way to completion over the real internet. Lower risk
  than the items above since both halves were proven independently.

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

## Smoke-tested, not exercised at real scale or duration

- **Catalog ingestion**: MarioCube (3,062 entries — since re-verified after
  a stale-HTML-regex fix) and NoPayStation (14,268 entries / 28,528 links,
  `psv` platform) have been run against live data and confirmed `ok` on
  the Sources page. MiNERVA and Internet Archive scrapers exist (ported
  from the original app) but have never been run end-to-end here. Run
  `python manage.py ingest_catalog --sources <id>` for each before relying
  on them.
  - NoPayStation's generated RAP/ZRIF key files used to link to
    `raw.githubusercontent.com/caprado/romgi/...` — the *original* app's
    fork, matching its now-abandoned "commit the built catalog back to
    GitHub" model. Every generated link 404ed. Fixed: keys are now written
    to `NOPAYSTATION_KEYS_DIR` and proxied by a new endpoint,
    `apps.ingestion.api.get_ingestion_key` — same "always proxy, never
    expose the raw path" pattern `apps.downloads.api` uses for staged
    downloads.
- **The full Docker Compose stack together.** Every service (all 4
  `celery-worker*` split by queue, `django`, `qbittorrent`, `sveltekit`)
  was individually confirmed to build and serve/respond correctly this
  session, including bringing several up concurrently — but there's been
  no sustained/concurrent load test (ingestion + downloads + torrents +
  credential/metadata calls all happening at once).
- **Beat-scheduled cadences.** `poll_active_torrents` (3s),
  `dispatch_pending_downloads` (5min), `cleanup_expired_staged_files`
  (hourly), `run_full_ingestion` (weekly, Sun 03:00 UTC), `gc_old_builds`
  (daily, 04:00 UTC), `internet_archive_revalidate` (daily, 05:00 UTC) —
  all confirmed to *fire* correctly via a short-duration Beat smoke test,
  but none observed running unattended over their real-world interval.

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

- `qbittorrent-api` is pinned to `>=2026.8` — an older pin
  (`<2025.0`, the original guess) can't parse a successful login response
  from qBittorrent 5.x, which is what `linuxserver/qbittorrent:latest`
  currently pulls. If that image jumps to a qBittorrent version with
  further Web API changes, this may need re-verifying.
