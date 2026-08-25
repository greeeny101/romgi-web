# romgi-web

A Django + SvelteKit web port of [romgi](https://github.com/caprado/romgi),
a Flutter/Android ROM downloader. Users browse a catalog of ROMs they
legally own and download them — over plain HTTP, BitTorrent (via
qBittorrent), or a debrid provider (Real-Debrid/TorBox) — with live
progress, optional archive extraction, Internet Archive login for
restricted content, and optional game metadata enrichment
(ScreenScraper/SteamGridDB).

Beyond the per-ROM catalog, **ROM Sets** browses whole published romsets on
archive.org by emulator (FBNeo, MAME, …), so a set that would otherwise be
fetched a file at a time arrives in one go — see [ROM sets](#rom-sets).

See [`KNOWN_ISSUES.md`](KNOWN_ISSUES.md) for what's unverified, deliberately
unimplemented, or worth a second look before relying on this in production.

## Credits

Ported from [caprado/romgi](https://github.com/caprado/romgi) (MIT
License, © 2025 Christian Prado) — the catalog ingestion pipeline, download
state machine, link-ranking/failover logic, torrent handling, debrid
resolution, Internet Archive login flow, and metadata provider integrations
are all adapted from that project's Dart/Kotlin/Python source, reimplemented
here in Python (Django/Celery) and TypeScript (SvelteKit). The original
project isn't vendored in this repo (it's reference material, not a runtime
dependency) — see its GitHub page for the original Android app.

## Architecture

- **Backend**: Django 5.1 + Django Ninja (REST API) + Django Channels
  (WebSocket progress) + Celery (background work: ingestion, downloads,
  torrents, credential/metadata calls) + PostgreSQL + Redis.
- **Frontend**: SvelteKit (Svelte 5, CSR-only) + FlowbiteSvelte + Tailwind CSS v4.
- **Torrents**: a qBittorrent-nox daemon, driven via its Web API. Both the
  per-ROM downloads and the ROM-set downloads drive it, and qBittorrent
  dedupes by infohash — so `apps/torrents/ownership.py` is the single place
  that decides whether a torrent is still wanted before anything stops or
  deletes it.
- **Catalog ingestion**: a vendored copy of the original app's Python ETL
  pipeline (`backend/apps/ingestion/pipeline/`), writing into Postgres
  instead of a SQLite file.

```
backend/apps/
  accounts/     JWT auth, per-user settings
  catalog/      read-mostly ROM catalog (platforms, entries, links, sources)
  ingestion/    catalog scraping pipeline + Celery orchestration
  library/      favorites, recently-viewed
  downloads/    HTTP download pipeline, adapters, debrid resolution
  torrents/     qBittorrent integration + cross-app torrent ownership guard
  romsets/      whole-archive.org-item downloads into a server-side library
  credentials/  encrypted-at-rest vault (IA session, debrid/metadata keys)
  metadata/     ScreenScraper/SteamGridDB enrichment + cache
  realtime/     Channels WebSocket consumer (download progress)
  common/       shared fields/models/management commands

frontend/src/
  routes/       pages (browse, entry detail, downloads, sets, library, settings, sources)
  lib/api/      typed fetch wrappers per backend router
  lib/stores/   Svelte stores (auth, session, downloads, romsets, favorites, theme)
  lib/components/
```

## Quick start (Docker Compose — recommended)

Requires Docker and Docker Compose.

```bash
cp backend/.env.example backend/.env
```

Edit `backend/.env` and set at minimum:
- `SECRET_KEY` — generate with:
  `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"`
- `ENCRYPTION_KEY` — generate with:
  `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`

**If the generated value contains a `$`, escape it as `$$`** — Docker
Compose interpolates every value in `.env`, and an unescaped `$word` gets
silently stripped out (you'd see `The "word" variable is not set.
Defaulting to a blank string.` warnings and, less obviously, a corrupted
key). See the header comment in `backend/.env.example` for details.

The rest of `backend/.env.example`'s defaults (`DATABASE_URL`, `REDIS_URL`,
etc.) already point at the other Compose services by their service names —
leave those as-is for Compose use.

```bash
docker compose up --build
```

This starts: `postgres`, `redis`, `django` (runs migrations + registers the
Celery Beat schedule on boot, then serves the API + WebSocket on 8001),
five `celery-worker*` services split by queue, `celery-beat`, `qbittorrent`,
and `sveltekit`.

Downloaded ROM sets land in the `rom_library` volume, which is bind-mounted
to a real host folder so you can actually reach the files — set
`ROM_LIBRARY_HOST_PATH` in a `.env` next to `docker-compose.yml` to point it
wherever you want (an absolute path that already exists). Leave it unset and
it uses the default baked into `docker-compose.yml`.

| Service | URL |
|---|---|
| Frontend | http://localhost:5174 |
| Backend API | http://localhost:8001/api |
| Backend admin | http://localhost:8001/admin |
| qBittorrent WebUI | http://localhost:8080 |

**First account**: registration is invite-only — there is no open signup, so
the first account has to come from the shell. Create the admin, then invite
everyone else:

```bash
docker compose exec django python manage.py createsuperuser

# Prints a signup link to send to the new user. --email binds the invite to
# that address so a leaked link is useless to anyone else.
docker compose exec django python manage.py createinvite --email someone@example.com
```

Invites can also be issued from the Django admin (Accounts → Invites), which
shows the signup link for each unused one.

**Forgotten passwords**: if `EMAIL_HOST` is configured, users self-serve from
the "Forgot your password?" link. If it isn't — email is optional here — the
reset endpoint deliberately does nothing, and you issue links by hand:

```bash
docker compose exec django python manage.py resetlink someone@example.com
```

That link grants access to the account, so send it over something private.

**First qBittorrent login**: it generates a random temporary password on
first boot — check `docker compose logs qbittorrent` for it, log in as
`admin`, then set the password to match `QBITTORRENT_PASSWORD` in your
`.env` (Preferences → Web UI) so the backend can authenticate.

That setting persists in the `qbittorrent_config` volume, so you only do it
once. Delete that volume (or run an older compose file that lacks it) and
qBittorrent comes back with a fresh random password that no longer matches
`.env` — every API call then fails to authenticate, and qBittorrent bans the
caller's IP for retrying, which surfaces as downloads failing with *"Your IP
address has been banned"*. Recreate the container to clear the ban, then set
the password again.

**Loading a catalog**: the database starts empty. Run ingestion for a
source once the stack is up:

```bash
docker compose exec django python manage.py ingest_catalog --sources mariocube
```

(Swap `mariocube` for `minerva`/`nopaystation`/`internet_archive`, or omit
`--sources` to run all of them — see `KNOWN_ISSUES.md` for which of these
have actually been run against live data.)

## ROM sets

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

## Manual / local development

Useful for editing backend or frontend code with fast reload, without
rebuilding Docker images each time. Needs Postgres and Redis running
somewhere reachable (Docker Compose's `postgres`/`redis` services work
fine for this — just run those two via Compose and everything else on the
host).

```bash
docker compose up -d postgres redis
```

**Backend:** uses [uv](https://docs.astral.sh/uv/) for dependency management
— install it first if you don't have it (`curl -LsSf https://astral.sh/uv/install.sh | sh`
or `brew install uv`).

```bash
cd backend
uv sync                # creates .venv, installs base deps + dev tooling (pytest, ruff, ...)
source .venv/bin/activate
```

(`uv sync` with no flags installs the `dev` dependency group by default —
see the comment in `pyproject.toml`. Production installs use
`uv sync --no-default-groups --extra production` instead, which is what the
`Dockerfile` does for a prod image build.)

`backend/.env`'s default `DATABASE_URL`/`REDIS_URL`/etc. use Docker service
names (`postgres`, `redis`), which only resolve *inside* the Compose
network. Running the backend directly on the host instead, override them
to the host-mapped ports (see the comment above `DATABASE_URL` in
`backend/.env.example` for the exact values — `localhost:5434`/`:6380`).

```bash
export DATABASE_URL="postgres://romgi:romgi@localhost:5434/romgi"
export REDIS_URL="redis://localhost:6380/0"
export CELERY_BROKER_URL="redis://localhost:6380/1"
export CELERY_RESULT_BACKEND="redis://localhost:6380/1"
export CHANNELS_REDIS_URL="redis://localhost:6380/2"
export DJANGO_SETTINGS_MODULE=config.settings.development

python manage.py migrate
python manage.py setup_periodic_tasks
python manage.py createsuperuser   # optional, for /admin

daphne -b 127.0.0.1 -p 8001 config.asgi:application
```

(Port 8001 matches `frontend/.env.example`'s default `VITE_API_BASE_URL` —
use it rather than 8000 so the frontend needs no extra configuration. This
is a drop-in alternative to the Compose `django` service, not something to
run alongside it — both bind the same port.)

In separate terminals (same env vars, same venv), run at least one Celery
worker and Beat — nothing runs in the background without both:

```bash
celery -A config worker -l info -Q celery,downloads,torrents,romsets,credentials,metadata
celery -A config beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
```

**Frontend:**

```bash
cd frontend
npm install
cp .env.example .env   # already points at localhost:8001, matching the daphne command above
npm run dev
```

### Debugging in VS Code

`.vscode/launch.json` wraps all of the above into one-click debug configs
(breakpoints work in Python and, via the Chrome config, in `.svelte`/`.ts`
files too). They all assume Postgres + Redis are reachable at the
host-mapped ports above — the Python configs' `preLaunchTask` starts them
via Docker automatically (`.vscode/tasks.json`), so you don't need to run
`docker compose up -d postgres redis` yourself first.

| Config | What it runs |
|---|---|
| **Django: Daphne (ASGI + WebSocket)** | The API + WS server on :8001 |
| **Celery: Worker (debug, solo pool)** | A worker consuming every queue, `--pool=solo` so breakpoints actually stop execution (prefork's default forking pool can't be attached to the same way) |
| **Celery: Beat** | The periodic-task scheduler |
| **Django: Migrate** / **Shell** / **Setup Periodic Tasks** / **Ingest Catalog (MarioCube)** | One-shot `manage.py` commands, runnable under the debugger |
| **SvelteKit: Dev Server** | `npm run dev` |
| **Chrome: Debug Frontend** | Launches Chrome at http://localhost:5173 with source maps wired up |

Two **compounds** start several of these together with one click:
`Full Stack (Daphne + Celery + Frontend)` and
`Frontend: Dev Server + Chrome Debugger`.

**Stop the debug worker when you're done.** It consumes the same Redis queues
as the Compose `celery-worker*` services, so leaving it running means the two
compete for every task — and because it runs whatever code was on disk when
it started, it will fail tasks it doesn't recognise (`Received unregistered
task of type ...`) while the Docker workers sit idle. A debug worker left
running overnight looks exactly like a broken feature.

Torrent work needs qBittorrent too, which none of these start by default
(most day-to-day work doesn't need it) — run the
**Start Postgres + Redis + qBittorrent** task manually first
(⇧⌘P → "Tasks: Run Task"), or `docker compose up -d qbittorrent`.

If port 5173 is already taken (e.g. by another project), Vite will pick a
different port automatically — update the Chrome config's `url` to match
if you're debugging in-browser.

## Tests / checks

```bash
# Backend
cd backend && python manage.py check && python manage.py makemigrations --check --dry-run

# Frontend
cd frontend && npm run check
```

Tests exist only where clicking around genuinely cannot tell you the answer:

```bash
docker compose exec django python -m pytest -q
```

- `apps/accounts/tests/` — "the lockout still works" is not observable from
  the UI, and a regression here is a security regression.
- `apps/romsets/tests/` — three things that fail *plausibly* rather than
  loudly: a bdecoder leaking BEP-47 padding entries into the file picker;
  file matching that ignores the torrent's root directory, which selects
  nothing and reports an instantly "complete" 0-byte download; and a
  re-request that deselects already-downloaded files, which makes qBittorrent
  delete them.

Everything else has no automated coverage yet — verification so far has been
targeted manual/scripted testing per feature (see `KNOWN_ISSUES.md`) plus
the two `check` commands above.

## Security & deployment

`backend/config/settings/production.py` sets `DEBUG=False`, HSTS, secure
cookies, and S3-compatible object storage for static files. Read it before
deploying — several values (`ALLOWED_HOSTS`, `AWS_STORAGE_BUCKET_NAME`,
`CSRF_TRUSTED_ORIGINS`, etc.) are required and have no defaults. See
`KNOWN_ISSUES.md` for what production storage does *not* yet cover (staged
downloads stay on local disk).

### Auth model

- **Invite-only registration.** `POST /api/auth/register` requires an unused
  invite code; there is no open signup path.
- **Rate limiting and lockout.** Per-IP throttles on every unauthenticated
  endpoint, plus a per-account lockout (`LOGIN_FAILURE_LIMIT`) that counts
  failures from the API and the Django admin form alike. Both need a shared
  cache — set `CACHE_URL`, and see the `CACHES` note in `settings/base.py`.
- **Set `NINJA_NUM_PROXIES`** to the number of reverse proxies in front of
  daphne. Leaving it wrong lets a client forge `X-Forwarded-For` and walk past
  every throttle above.
- **Rotating refresh tokens.** `/auth/refresh` returns a new pair and
  blacklists the old token; users can list and revoke their own sessions from
  Settings → Account.
- **Not indexed.** `static/robots.txt` and the `noindex` tag in `src/app.html`
  keep this private instance out of search results.
- **No 2FA yet.** The token path is structured for it (see the docstring in
  `apps/accounts/services/auth.py`), but it isn't built.
