# Installation

[← back to README](../README.md)

The README's quick start covers the happy path. This is everything else: the
configuration values that need care, getting the first account created, the
qBittorrent handshake, and loading a catalog.

## Environment

There are two env files, with two different jobs:

| File | Read by | Holds |
|---|---|---|
| `backend/.env` | the containers (via Compose's `env_file`) | application config — secrets, database URLs, in-container paths |
| `.env` (repo root) | Docker Compose itself | where each volume lives **on the host** |

A variable put in the wrong one silently does nothing. Both have a committed
`.example` template:

```bash
cp .env.example .env
cp backend/.env.example backend/.env
```

`.env` needs `ROM_LIBRARY_HOST_PATH` set before the stack will start — see
[Where files are stored](#where-files-are-stored) below.

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

## What `docker compose up` starts

`postgres`, `redis`, `django` (runs migrations + registers the Celery Beat
schedule on boot, then serves the API + WebSocket on 8001), five
`celery-worker*` services split by queue, `celery-beat`, `qbittorrent`, and
`sveltekit`.

| Service | URL |
|---|---|
| Frontend | http://localhost:5174 |
| Backend API | http://localhost:8001/api |
| Backend admin | http://localhost:8001/admin |
| qBittorrent WebUI | http://localhost:8080 |

## Where files are stored

Every volume's host location is set from the root `.env`:

| Variable | Holds | Unset |
|---|---|---|
| `ROM_LIBRARY_HOST_PATH` | Downloaded ROM sets | **Stack refuses to start** |
| `STAGED_FILES_HOST_PATH` | Single-game downloads awaiting claim | `staged_files` named volume |
| `TORRENT_DATA_HOST_PATH` | Torrent working directory | `torrent_data` named volume |
| `QBITTORRENT_CONFIG_HOST_PATH` | qBittorrent's config and WebUI password | `qbittorrent_config` named volume |
| `POSTGRES_DATA_HOST_PATH` | The database | `postgres_data` named volume |

Leave the bottom four unset and they stay Docker-managed named volumes, which
is a reasonable default — it just means the files live inside the Docker VM,
where on macOS Finder can't reach them and `docker compose cp` is the only way
to get anything out. Set one to a path and it becomes a bind mount to that
host folder instead.

Compose decides which of the two you meant by the *shape* of the value: a bare
name is a named volume, anything with a slash in it is a bind mount. So a
value must be an absolute path or start with `./`. `staged` on its own is read
as a volume reference and Compose refuses to start — *"refers to undefined
volume staged"* — rather than doing what you meant.

Changing one of these later does **not** migrate what's already there. The new
location starts empty; the old contents stay in the named volume, still listed
under `docker volume ls`.

### The library folder

`ROM_LIBRARY_HOST_PATH` is the one with no default — Compose aborts before
starting anything if it's unset or empty. That's deliberate: a library is the
one location that can't be guessed, and quietly filling a home directory with
tens of gigabytes is worse than refusing to boot. Point it at whatever you
actually want to browse — a NAS share, an external disk, the folder your
cabinet reads.

Unlike the other four it must be an **absolute** path to a folder that
**already exists**, and if it's a network share, one that's actually mounted.
It uses a different mount mechanism precisely so that it fails loudly instead
of creating what's missing: if the share isn't mounted, you want the error,
not 20GB written into an empty local folder that the real share then hides the
moment it does mount.

## Using existing servers

Postgres, Redis and qBittorrent each ship as a container, but if you already
run one, the bundled copy can be skipped entirely. `COMPOSE_PROFILES` in the
root `.env` lists which of the three to start:

```
COMPOSE_PROFILES=local-postgres,local-redis,local-qbittorrent
```

Remove a name and that container is never created. Then point the matching
variable in `backend/.env` at the real server:

| Removed from `COMPOSE_PROFILES` | Set in `backend/.env` |
|---|---|
| `local-postgres` | `DATABASE_URL` |
| `local-redis` | `REDIS_URL` |
| `local-qbittorrent` | `QBITTORRENT_HOST` |

Redis needs only that one variable — the Celery, Channels and cache URLs are
derived from it (databases 1, 2 and 3 of the same server). Set
`CELERY_BROKER_URL` and friends explicitly only if you need a different
database layout, or if `REDIS_URL` isn't a `redis://` URL.

Note this means editing **two** files: `COMPOSE_PROFILES` is Compose's own
configuration and lives in the root `.env`, while the connection URLs are
application configuration and live in `backend/.env`.

Three things that catch people out:

- **`localhost` inside a container is the container.** A server running on this
  machine is `host.docker.internal` (Docker Desktop) or the host's LAN address.
  `redis://localhost:6379/0` will not reach it.
- **Removing a profile doesn't stop an already-running container** — it's left
  behind as an orphan. Use `docker compose up -d --remove-orphans`.
- **There's no health gate on an external server.** When the bundled service
  runs, dependents wait for its healthcheck; an external one can't be waited
  on, so containers start immediately and retry. They all have a restart policy
  for this reason, but expect a few failed attempts in the logs if the server
  is slower to come up than the stack.

`POSTGRES_PORT` and `REDIS_PORT` in the root `.env` control which host ports
the *bundled* Postgres and Redis publish on (5434 and 6380 by default) — useful
if something else on the machine already owns those. They have no effect on a
server you've profiled out; that one's port comes from its URL.

### External qBittorrent

This one needs more than a hostname. The download pipeline hands qBittorrent a
save path, then **reads the finished files back off disk itself** — so an
external daemon has to write somewhere this stack can also read. That means:

1. Point `TORRENT_DATA_HOST_PATH` and `ROM_LIBRARY_HOST_PATH` (root `.env`) at
   storage both machines can see — an NFS/SMB share, say.
2. Set `QBITTORRENT_SAVE_PATH` and `QBITTORRENT_LIBRARY_PATH` (`backend/.env`)
   to the paths *that daemon* sees for those same directories. They are its
   view of the storage, not this stack's — see the comments next to them in
   `backend/.env.example`.

Get this wrong and torrents complete happily in qBittorrent and then fail when
the pipeline goes looking for the files.

## First account

Registration is invite-only — there is no open signup, so the first account
has to come from the shell. Create the admin, then invite everyone else:

```bash
docker compose exec django python manage.py createsuperuser

# Prints a signup link to send to the new user. --email binds the invite to
# that address so a leaked link is useless to anyone else.
docker compose exec django python manage.py createinvite --email someone@example.com
```

Invites can also be issued from the Django admin (Accounts → Invites), which
shows the signup link for each unused one.

## Forgotten passwords

If `EMAIL_HOST` is configured, users self-serve from the "Forgot your
password?" link. If it isn't — email is optional here — the reset endpoint
deliberately does nothing, and you issue links by hand:

```bash
docker compose exec django python manage.py resetlink someone@example.com
```

That link grants access to the account, so send it over something private.

## First qBittorrent login

Only applies to the bundled container — skip this if you removed
`local-qbittorrent` and pointed `QBITTORRENT_HOST` at your own daemon.

qBittorrent generates a random temporary password on first boot — check
`docker compose logs qbittorrent` for it, log in as `admin`, then set the
password to match `QBITTORRENT_PASSWORD` in your `.env` (Preferences → Web UI)
so the backend can authenticate.

That setting persists in the `qbittorrent_config` volume, so you only do it
once. Delete that volume (or run an older compose file that lacks it) and
qBittorrent comes back with a fresh random password that no longer matches
`.env` — every API call then fails to authenticate, and qBittorrent bans the
caller's IP for retrying, which surfaces as downloads failing with *"Your IP
address has been banned"*. Recreate the container to clear the ban, then set
the password again.

## Loading a catalog

The database starts empty. Run ingestion for a source once the stack is up:

```bash
docker compose exec django python manage.py ingest_catalog --sources mariocube
```

(Swap `mariocube` for `minerva`/`nopaystation`/`internet_archive`, or omit
`--sources` to run all of them — see [`KNOWN_ISSUES.md`](../KNOWN_ISSUES.md)
for which of these have actually been run against live data.)

ROM Sets need none of this — they read archive.org live. See
[ROM sets](romsets.md).
