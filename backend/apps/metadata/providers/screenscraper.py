"""Ports lib/services/metadata/screenscraper_provider.dart, with one
correction: api2 authenticates on the *developer* credentials, not the end
user's. Those developer credentials belong to the romgi instance rather than
to each user (settings.SCREENSCRAPER_DEV_ID/_DEV_PASSWORD) — ScreenScraper
issues them per application, so asking every user for a pair they cannot
obtain was never going to work. This is the same arrangement Batocera uses
(its pair is compiled into EmulationStation via -DSCREENSCRAPER_DEV_LOGIN)
and is why Batocera appears to scrape from a username and password alone."""

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests
from django.conf import settings

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

API_HOST = "api.screenscraper.fr"
BASE_URL = f"https://{API_HOST}/api2"
TIMEOUT = (10, 30)

# Everything in a ScreenScraper URL that authenticates rather than addresses.
# The API echoes all of these back inside the media URLs it returns, so they
# have to be strippable — see _strip_auth.
AUTH_PARAMS = ("devid", "devpassword", "ssid", "sspassword", "softname")


def build_auth_params(creds: dict) -> dict:
    """devid/devpassword are what api2 actually authenticates on, and they're
    the instance's, not the user's — a request without them is rejected with
    "Vérifier vos identifiants développeur" no matter how valid the user
    account is. ssid/sspassword are the end user's own account: they only
    lift the anonymous quota/thread limits, so they're omitted when blank
    rather than sent empty."""
    params = {
        "softname": settings.SCREENSCRAPER_SOFTNAME,
        "output": "json",
        "devid": (settings.SCREENSCRAPER_DEV_ID or "").strip(),
        "devpassword": (settings.SCREENSCRAPER_DEV_PASSWORD or "").strip(),
    }
    username = (creds.get("username") or "").strip()
    password = (creds.get("password") or "").strip()
    if username:
        params["ssid"] = username
    if password:
        params["sspassword"] = password
    return params


def _missing_dev_creds() -> str | None:
    """Phrased at the operator, not the user: nothing a user types in Settings
    can fix a missing instance-wide developer pair, so pointing them at the
    ScreenScraper forum (as this once did) just sends them somewhere useless."""
    if (settings.SCREENSCRAPER_DEV_ID or "").strip() and (settings.SCREENSCRAPER_DEV_PASSWORD or "").strip():
        return None
    return (
        "This romgi instance has no ScreenScraper developer credentials configured, "
        "and the API rejects every request without them. ScreenScraper issues these "
        "per application on request; the server administrator sets SCREENSCRAPER_DEV_ID "
        "and SCREENSCRAPER_DEV_PASSWORD."
    )


def _strip_auth(url: str) -> str:
    """ScreenScraper hands back media URLs with the credentials it was called
    with still in the query string. Those URLs go into the *shared* metadata
    cache and then into an <img src>, so the secrets come off before anything
    stores them; apps.metadata.api re-attaches them server-side when it
    proxies the fetch."""
    parsed = urlparse(url)
    kept = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if k.lower() not in AUTH_PARAMS]
    return urlunparse(parsed._replace(query=urlencode(kept)))


def _text_error(text: str) -> MetadataError:
    # ScreenScraper returns errors as plain text under a JSON content-type,
    # sometimes with HTTP 200 and sometimes with 401/403. Both login failures
    # read "Erreur de login"; only the tail distinguishes a missing developer
    # account from a bad user password, and collapsing them into one message
    # is what made a missing devid look like a wrong password.
    lower = text.lower()
    if "identifiants développeur" in lower or "identifiants developpeur" in lower:
        return MetadataError(
            "ScreenScraper rejected this instance's developer credentials — check "
            "SCREENSCRAPER_DEV_ID and SCREENSCRAPER_DEV_PASSWORD on the server.",
            auth_error=True,
        )
    if "erreur de login" in lower:
        return MetadataError("Invalid ScreenScraper username or password", auth_error=True)
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
            items.append(MediaItem(full=_strip_auth(url)))
        if len(items) >= 8:
            break
    return items


class ScreenScraperProvider(MetadataProvider):
    info = MetadataProviderInfo(id="screenscraper", name="ScreenScraper")
    # The user's own account, and nothing else — the developer pair is the
    # instance's. Both required rather than optional: they're all we ask for,
    # and is_configured() (base.py) is what gates this provider into
    # service.get_metadata's fetch list, so an optional-only field list would
    # have the provider claim to be configured with nothing stored at all.
    credential_fields = [
        CredentialField(key="username", label="Username"),
        CredentialField(key="password", label="Password", obscure=True),
    ]

    def validate_credentials(self, creds: dict) -> str | None:
        missing = _missing_dev_creds()
        if missing:
            return missing
        try:
            resp = requests.get(f"{BASE_URL}/ssuserInfos.php", params=build_auth_params(creds), timeout=TIMEOUT)
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

        missing = _missing_dev_creds()
        if missing:
            return MetadataError(missing, auth_error=True)

        try:
            resp = requests.get(
                f"{BASE_URL}/jeuRecherche.php",
                params={**build_auth_params(creds), "systemeid": system_id, "recherche": title},
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
