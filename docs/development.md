# Development

[← back to README](../README.md)

## Code layout

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

## Debugging in VS Code

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
targeted manual/scripted testing per feature (see
[`KNOWN_ISSUES.md`](../KNOWN_ISSUES.md)) plus the two `check` commands above.
