"""
Two unrelated things share this router because they're both small enough
not to warrant their own app:

1. Serves small artefacts the ingestion pipeline writes to local disk at
   scrape time — currently just NoPayStation's per-entry RAP/ZRIF key
   files (apps/ingestion/pipeline/sources/nopaystation/scraper.py). Those
   used to be linked as raw.githubusercontent.com URLs against the
   *original* app's fork, matching its "commit the built catalog back to
   GitHub" model — this project replaced that model with
   CatalogBuild-tagged DB writes, so nothing publishes these files there
   and every generated link 404ed. This proxies them from wherever the
   scraper actually wrote them instead, the same "always proxy, never
   expose the raw path" pattern apps.downloads.api uses for staged
   downloads.
2. A manual per-source "Run" trigger for the Sources page.
"""

import os

from django.conf import settings as django_settings
from django.http import FileResponse, Http404
from ninja import Router, Schema
from ninja.errors import HttpError
from ninja_jwt.authentication import JWTAuth

from apps.catalog.models import CatalogBuild, Source

from .tasks import run_single_source

router = Router(tags=["ingestion"])

_ALLOWED_KINDS = {
    "ps3": {"raps"},
    "psv": {"zrifs"},
}


def _safe_path(base_dir: str, *parts: str) -> str | None:
    """Resolves parts under base_dir, rejecting anything that would escape
    it (e.g. a `..` component) — same guard shape as
    apps.downloads.extraction._safe_target."""
    base_abs = os.path.abspath(base_dir)
    target_abs = os.path.abspath(os.path.join(base_dir, *parts))
    if target_abs == base_abs or target_abs.startswith(base_abs + os.sep):
        return target_abs
    return None


@router.get("/keys/{platform}/{kind}/{filename}")
def get_ingestion_key(request, platform: str, kind: str, filename: str):
    if kind not in _ALLOWED_KINDS.get(platform, set()):
        raise Http404("Unknown key type.")

    path = _safe_path(django_settings.NOPAYSTATION_KEYS_DIR, platform, kind, filename)
    if path is None or not os.path.isfile(path):
        raise Http404("Key file not found.")

    return FileResponse(open(path, "rb"), as_attachment=True, filename=os.path.basename(path))


class RunSourceOut(Schema):
    task_id: str


@router.post("/sources/{source_id}/run", response={202: RunSourceOut}, auth=JWTAuth())
def run_source(request, source_id: str):
    if not Source.objects.filter(id=source_id).exists():
        raise Http404("Unknown source.")
    if CatalogBuild.objects.filter(status="running").exists():
        raise HttpError(409, "An ingestion build is already running — try again once it finishes.")

    result = run_single_source.delay(source_id)
    return 202, RunSourceOut(task_id=result.id)
