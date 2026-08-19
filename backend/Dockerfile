FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev git \
    && rm -rf /var/lib/apt/lists/*

# Pinned rather than :latest — see requirements comment on qbittorrent-api
# in pyproject.toml for why floating tags have bitten this project before.
COPY --from=ghcr.io/astral-sh/uv:0.10.9 /uv /uvx /usr/local/bin/

COPY pyproject.toml uv.lock ./
# No flags = base + dev tooling (pytest, ruff, django-debug-toolbar) — matches
# docker-compose.yml's dev services, which all use this image as-is.
# Production builds override:
#   --build-arg UV_SYNC_ARGS="--no-default-groups --extra production"
ARG UV_SYNC_ARGS=""
RUN uv sync --frozen ${UV_SYNC_ARGS}

# The mariocube ingestion source needs a real browser (TLS-fingerprinting
# bypass) — see apps/ingestion/pipeline/utils/scrape_utils.py. `uv sync`
# only installs the playwright Python package; the browser binary itself
# is a separate download.
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/playwright
RUN /opt/venv/bin/playwright install --with-deps chromium

# chdman, from mame-tools (~15MB). A multi-track CD rip extracts to a .cue plus
# N .bin tracks, but a download serves exactly one file, so the set is collapsed
# into a single .chd — see apps/downloads/chd.py.
#
# Its own layer, deliberately, rather than folded into the build-essential
# apt-get above: that one sits before `uv sync` and the chromium download, so
# touching it would rebuild both of those (several minutes) for the sake of one
# small package.
RUN apt-get update \
    && apt-get install -y --no-install-recommends mame-tools \
    && rm -rf /var/lib/apt/lists/*

# The venv deliberately lives outside /app (UV_PROJECT_ENVIRONMENT above) —
# docker-compose.yml's dev services bind-mount ./backend over /app at
# runtime, which would otherwise shadow (and, worse, silently replace with
# a macOS/host-incompatible one) whatever venv sat inside it.
ENV PATH="/opt/venv/bin:${PATH}"

COPY . .

EXPOSE 8000

CMD ["daphne", "-b", "0.0.0.0", "-p", "8000", "config.asgi:application"]
