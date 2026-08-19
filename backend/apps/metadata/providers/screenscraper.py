"""Ports lib/services/metadata/screenscraper_provider.dart, with one
correction: api2 authenticates on the *developer* credentials, so dev_id/
dev_password are required here and the end-user account is optional."""

import requests

from .base import (
    CredentialField,
    MediaItem,
    MetadataError,
    MetadataFound,
    MetadataNoMatch,
    MetadataProvider,
    MetadataProviderInfo,
    MetadataResult,
)
from .screenscraper_systems import SCREENSCRAPER_SYSTEM_IDS

BASE_URL = "https://api.screenscraper.fr/api2"
TIMEOUT = (10, 30)


def _auth_params(creds: dict) -> dict:
    """devid/devpassword are what api2 actually authenticates on — a request
    without them is rejected with the same generic "Erreur de login" as a
    request with a bad password, which is why a user-only setup looked like
    wrong credentials rather than a missing developer account. ssid/
    sspassword are the end user's own account: optional, and only there to
    lift the anonymous quota/thread limits, so they're omitted when blank
    rather than sent empty."""
    params = {
        "softname": "romgi",
        "output": "json",
        "devid": (creds.get("dev_id") or "").strip(),
        "devpassword": (creds.get("dev_password") or "").strip(),
    }
    username = (creds.get("username") or "").strip()
    password = (creds.get("password") or "").strip()
    if username:
        params["ssid"] = username
    if password:
        params["sspassword"] = password
    return params


def _missing_dev_creds(creds: dict) -> str | None:
    if (creds.get("dev_id") or "").strip() and (creds.get("dev_password") or "").strip():
        return None
    return (
        "ScreenScraper needs a developer ID and password — the API rejects every "
        "request without them, even with a valid user account. Request developer "
        "access on the ScreenScraper forum, then enter them here."
    )


def _text_error(text: str) -> MetadataError:
    # ScreenScraper returns errors as plain text under a JSON content-type,
    # sometimes with HTTP 200 and sometimes with 401/403.
    lower = text.lower()
    if "erreur de login" in lower:
        return MetadataError("Invalid ScreenScraper credentials", auth_error=True)
    if "votre quota" in lower:
        return MetadataError("ScreenScraper quota exceeded")
    return MetadataError(f"ScreenScraper: {text.strip()[:120]}")


def _synopsis(jeu: dict) -> str | None:
    entries = [e for e in (jeu.get("synopsis") or []) if isinstance(e, dict)]
    if not entries:
        return None
    chosen = next((e for e in entries if e.get("langue") == "en"), entries[0])
    text = (chosen.get("text") or "").strip()
    return text or None


def _screenshots(jeu: dict) -> list[MediaItem]:
    # No thumbnail variant comes back in `medias` — MediaItem falls back to
    # serving the original for display as well as for the link-out.
    items = []
    for media in jeu.get("medias") or []:
        if not isinstance(media, dict) or media.get("type") not in ("ss", "sstitle"):
            continue
        url = media.get("url")
        if url:
            items.append(MediaItem(full=url))
        if len(items) >= 8:
            break
    return items


class ScreenScraperProvider(MetadataProvider):
    info = MetadataProviderInfo(id="screenscraper", name="ScreenScraper")
    credential_fields = [
        CredentialField(key="dev_id", label="Developer ID"),
        CredentialField(key="dev_password", label="Developer Password", obscure=True),
        CredentialField(key="username", label="Username", optional=True),
        CredentialField(key="password", label="Password", obscure=True, optional=True),
    ]

    def validate_credentials(self, creds: dict) -> str | None:
        missing = _missing_dev_creds(creds)
        if missing:
            return missing
        try:
            resp = requests.get(f"{BASE_URL}/ssuserInfos.php", params=_auth_params(creds), timeout=TIMEOUT)
        except requests.RequestException:
            return "Could not reach ScreenScraper"
        if resp.status_code == 200:
            try:
                body = resp.json()
            except ValueError:
                return _text_error(resp.text).message
            if isinstance(body, dict):
                return None
        # Auth failures come back as 401/403 with a plain-text French reason
        # (under a JSON content-type), so prefer that reason over a bare
        # status code — "quota exceeded" and "bad login" both land here.
        if resp.text.strip():
            return _text_error(resp.text).message
        return f"ScreenScraper returned {resp.status_code}"

    def fetch(self, title: str, platform: str, creds: dict) -> MetadataResult:
        system_id = SCREENSCRAPER_SYSTEM_IDS.get(platform)
        if system_id is None:
            return MetadataNoMatch()

        missing = _missing_dev_creds(creds)
        if missing:
            return MetadataError(missing, auth_error=True)

        try:
            resp = requests.get(
                f"{BASE_URL}/jeuRecherche.php",
                params={**_auth_params(creds), "systemeid": system_id, "recherche": title},
                timeout=TIMEOUT,
            )
        except requests.RequestException as exc:
            return MetadataError(str(exc) or "ScreenScraper request failed")

        if resp.status_code in (400, 404):
            return MetadataNoMatch()
        if resp.status_code in (401, 403):
            error = _text_error(resp.text) if resp.text.strip() else MetadataError("Invalid ScreenScraper credentials")
            error.auth_error = True
            return error
        if resp.status_code == 429:
            return MetadataError("ScreenScraper quota exceeded")

        try:
            body = resp.json()
        except ValueError:
            return _text_error(resp.text)
        if not isinstance(body, dict):
            return MetadataError("ScreenScraper: unexpected response")

        jeux = [j for j in ((body.get("response") or {}).get("jeux") or []) if isinstance(j, dict)]
        if not jeux:
            return MetadataNoMatch()

        title_lower = title.lower()
        chosen = None
        for jeu in jeux:
            for nom in jeu.get("noms") or []:
                if isinstance(nom, dict) and (nom.get("text") or "").lower() == title_lower:
                    chosen = jeu
                    break
            if chosen:
                break
        if chosen is None:
            chosen = jeux[0]

        return MetadataFound(description=_synopsis(chosen), screenshots=_screenshots(chosen))
