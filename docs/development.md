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

`backend/.env`'s default `DATABASE_URL`/`REDIS_URL` use Docker service names
(`postgres`, `redis`), which only resolve *inside* the Compose network.
Running the backend directly on the host instead, override them to the
host-mapped ports — `localhost:5434` and `localhost:6380` by default, or
whatever you set `POSTGRES_PORT`/`REDIS_PORT` to in the root `.env`.

Only `REDIS_URL` needs setting: the Celery, Channels and cache URLs derive
from it (`_redis_db` in `config/settings/base.py`).

```bash
export DATABASE_URL="postgres://romgi:romgi@localhost:5434/romgi"
export REDIS_URL="redis://localhost:6380/0"
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

> **Stop the Compose workers first.** Unlike daphne, a Celery worker binds no
> port, so nothing stops a host worker running *alongside* the containerised
> ones — and both subscribe to the same Redis queues. Redis then hands each
> task to whichever worker grabs it first, so the steps of one download get
> split across two machines with different filesystem views. It fails as a
> bare `[Errno 2] No such file or directory` on a staged file that another
> worker wrote somewhere the first one can't see, and the traceback appears in
> neither log you're watching.
>
> ```bash
> docker compose stop celery-worker celery-worker-torrents celery-worker-romsets \
>                     celery-worker-ingestion celery-worker-external celery-beat
> ```
>
> `docker compose start <same list>` puts them back. The same applies to any
> mix of host and container workers — run one set or the other, never both.

Paths are the other half of this. `STAGED_FILES_DIR` and `TORRENT_WORKING_DIR`
default to *relative* paths (`./data/staged`), which resolve against the
process's working directory — `/app` in a container, `backend/` on the host.
Those are different directories, so a host worker will not find what a
container wrote. If the Compose stack stores them somewhere else (see
`*_HOST_PATH` in the root `.env`), override both to that absolute host path
when running on the host.

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
files too). The Python configs load `backend/.env` via `envFile`, so they
connect to whatever Postgres and Redis that file points at — no separate
copy of the connection strings to keep in sync. Only `QBITTORRENT_HOST` is
overridden per-config, because the containers reach the daemon by its Compose
service name and the host can't resolve that.

If `backend/.env` names Compose service names (`postgres`, `redis`) rather
than reachable hosts, those won't resolve from the host — start the bundled
services and override the two URLs to the host-mapped ports, as above.

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

**Stop the debug worker when you're done** — and stop the Compose workers
before you start it (see the warning under *Manual / local development*
above). It consumes the same Redis queues
as the Compose `celery-worker*` services, so leaving it running means the two
compete for every task — and because it runs whatever code was on disk when
it started, it will fail tasks it doesn't recognise (`Received unregistered
task of type ...`) while the Docker workers sit idle. A debug worker left
running overnight looks exactly like a broken feature.

Torrent work needs qBittorrent too, which none of these start by default
(most day-to-day work doesn't need it) — `docker compose up -d qbittorrent`.

The tasks in `.vscode/tasks.json` predate the `COMPOSE_PROFILES` switch and
still run `docker compose up -d postgres redis`. Naming a service explicitly
auto-enables its profile, so those tasks will start bundled Postgres/Redis
containers even when you've profiled them out in favour of external servers —
containers nothing then connects to. Don't run them in that setup.

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
