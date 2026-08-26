# Installation

[← back to README](../README.md)

The README's quick start covers the happy path. This is everything else: the
configuration values that need care, getting the first account created, the
qBittorrent handshake, and loading a catalog.

## Environment

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

## The library folder

Downloaded ROM sets land in the `rom_library` volume, which is bind-mounted
to a real host folder so you can actually reach the files — set
`ROM_LIBRARY_HOST_PATH` in a `.env` next to `docker-compose.yml` to point it
wherever you want (an absolute path that already exists). Leave it unset and
it uses the default baked into `docker-compose.yml`.

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
