"""Ports lib/services/metadata/screenscraper_provider.dart 1:1."""

import requests

from .base import CredentialField, MetadataError, MetadataFound, MetadataNoMatch, MetadataProvider, MetadataProviderInfo, MetadataResult
from .screenscraper_systems import SCREENSCRAPER_SYSTEM_IDS

BASE_URL = "https://api.screenscraper.fr/api2"
TIMEOUT = (10, 30)


def _auth_params(creds: dict) -> dict:
    params = {
        "softname": "romgi",
        "output": "json",
        "ssid": (creds.get("username") or "").strip(),
        "sspassword": (creds.get("password") or "").strip(),
    }
    dev_id = (creds.get("dev_id") or "").strip()
    dev_password = (creds.get("dev_password") or "").strip()
    if dev_id:
        params["devid"] = dev_id
    if dev_password:
        params["devpassword"] = dev_password
    return params


def _text_error(text: str) -> MetadataError:
    # ScreenScraper returns errors as HTTP 200 plain text, not JSON.
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


def _screenshots(jeu: dict) -> list[str]:
    urls = []
    for media in jeu.get("medias") or []:
        if not isinstance(media, dict) or media.get("type") not in ("ss", "sstitle"):
            continue
        url = media.get("url")
        if url:
            urls.append(url)
        if len(urls) >= 8:
            break
    return urls


class ScreenScraperProvider(MetadataProvider):
    info = MetadataProviderInfo(id="screenscraper", name="ScreenScraper")
    credential_fields = [
        CredentialField(key="username", label="Username"),
        CredentialField(key="password", label="Password", obscure=True),
        CredentialField(key="dev_id", label="Developer ID", optional=True),
        CredentialField(key="dev_password", label="Developer Password", obscure=True, optional=True),
    ]

    def validate_credentials(self, creds: dict) -> str | None:
        try:
            resp = requests.get(f"{BASE_URL}/ssuserInfos.php", params=_auth_params(creds), timeout=TIMEOUT)
        except requests.RequestException:
            return "Could not reach ScreenScraper"
        if resp.status_code in (401, 403):
            return "Invalid ScreenScraper credentials"
        if resp.status_code == 200:
            try:
                body = resp.json()
            except ValueError:
                return _text_error(resp.text).message
            if isinstance(body, dict):
                return None
        return f"ScreenScraper returned {resp.status_code}"

    def fetch(self, title: str, platform: str, creds: dict) -> MetadataResult:
        system_id = SCREENSCRAPER_SYSTEM_IDS.get(platform)
        if system_id is None:
            return MetadataNoMatch()

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
            return MetadataError("Invalid ScreenScraper credentials", auth_error=True)
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

        return MetadataFound(description=_synopsis(chosen), screenshot_urls=_screenshots(chosen))
