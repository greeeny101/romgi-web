"""Ports lib/services/metadata/steamgriddb_provider.dart 1:1. `platform` is
accepted (for interface parity with ScreenScraper) but unused — SGDB
searches by title only, not scoped by platform."""

from urllib.parse import quote

import requests

from .base import CredentialField, MetadataError, MetadataFound, MetadataNoMatch, MetadataProvider, MetadataProviderInfo, MetadataResult

BASE_URL = "https://www.steamgriddb.com/api/v2"
TIMEOUT = (10, 30)
MAX_ARTWORK = 6


def _headers(creds: dict) -> dict:
    return {"Authorization": f"Bearer {(creds.get('api_key') or '').strip()}"}


class SteamGridDbProvider(MetadataProvider):
    info = MetadataProviderInfo(id="steamgriddb", name="SteamGridDB")
    credential_fields = [CredentialField(key="api_key", label="API Key", obscure=True)]

    def validate_credentials(self, creds: dict) -> str | None:
        try:
            resp = requests.get(f"{BASE_URL}/search/autocomplete/mario", headers=_headers(creds), timeout=TIMEOUT)
        except requests.RequestException:
            return "Could not reach SteamGridDB"
        if resp.status_code in (401, 403):
            return "Invalid SteamGridDB API key"
        if resp.status_code == 200:
            try:
                body = resp.json()
            except ValueError:
                body = None
            if isinstance(body, dict) and body.get("success") is True:
                return None
        return f"SteamGridDB returned {resp.status_code}"

    def fetch(self, title: str, platform: str, creds: dict) -> MetadataResult:
        headers = _headers(creds)
        try:
            resp = requests.get(f"{BASE_URL}/search/autocomplete/{quote(title, safe='')}", headers=headers, timeout=TIMEOUT)
        except requests.RequestException as exc:
            return MetadataError(str(exc) or "SteamGridDB request failed")

        if resp.status_code in (401, 403):
            return MetadataError("Invalid SteamGridDB API key", auth_error=True)
        try:
            body = resp.json()
        except ValueError:
            return MetadataError("SteamGridDB: unexpected response")
        if not isinstance(body, dict):
            return MetadataError("SteamGridDB: unexpected response")
        if body.get("success") is False:
            errors = [e for e in (body.get("errors") or []) if isinstance(e, str)]
            return MetadataError(f"SteamGridDB: {', '.join(errors) or 'request failed'}")

        results = [g for g in (body.get("data") or []) if isinstance(g, dict)]
        if not results:
            return MetadataNoMatch()

        title_lower = title.lower()
        chosen = next((g for g in results if (g.get("name") or "").lower() == title_lower), results[0])
        game_id = chosen.get("id")
        if not isinstance(game_id, int):
            return MetadataNoMatch()

        # Heroes first, then grids, response order preserved — no
        # dimension/score-based selection in the source app.
        urls = self._media_urls(f"/heroes/game/{game_id}", headers) + self._media_urls(f"/grids/game/{game_id}", headers)
        return MetadataFound(artwork_urls=urls[:MAX_ARTWORK])

    def _media_urls(self, path: str, headers: dict) -> list[str]:
        try:
            resp = requests.get(f"{BASE_URL}{path}", headers=headers, timeout=TIMEOUT)
            body = resp.json()
        except (requests.RequestException, ValueError):
            return []
        if not isinstance(body, dict) or body.get("success") is not True:
            return []
        return [m["url"] for m in (body.get("data") or []) if isinstance(m, dict) and m.get("url")]
