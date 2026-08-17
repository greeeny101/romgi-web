"""
Server-side port of internet_archive_auth_manager.dart. The Dart app never
POSTs credentials itself — it loads archive.org's own login page in a
WebView and lets the browser handle auth, then scrapes S3 keys out of
https://archive.org/account/s3.php using the resulting session cookies
(via JS injected into the WebView, so it gets HttpOnly cookies too).

The login *step* now needs a real browser too: archive.org/account/login
was rewritten as a client-rendered SPA (Lit web components) at some point
after this was first ported — a plain `requests.get()` of that URL returns
an almost-empty HTML shell (no <form>, no <input> at all; confirmed live).
The actual submit goes to a JSON endpoint,
`POST https://archive.org/services/account/login/`, gated by a CSRF JWT
that only gets minted by the page's own JS (no cookie/token appears on a
plain unauthenticated GET) — so this drives the real page with Playwright
(already a project dependency, see apps/ingestion/pipeline for the same
pattern) rather than trying to hand-replicate that token minting.
`s3.php`, by contrast, is still classic server-rendered HTML (confirmed
live) — the `requests`-based `_fetch_s3_keys` scrape below is unaffected
and reuses the cookies the Playwright login obtained.
"""

import re

import requests
from django.utils import timezone
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from apps.credentials.models import EncryptedCredential

LOGIN_URL = "https://archive.org/account/login"
LOGIN_API_URL = "https://archive.org/services/account/login/"
S3_KEYS_URL = "https://archive.org/account/s3.php"
PROBE_URL = "https://s3.us.archive.org/?check_auth=1"

STALE_AFTER = timezone.timedelta(hours=24)
PROBE_TIMEOUT = 5
REQUEST_TIMEOUT = 15
MAX_FAILURES = 3

# IA's s3.php page renders access/secret key <input> values as bare
# 16-character alphanumeric strings (per the Dart port's own comment: IA
# stopped emitting name="access"/name="secret" attributes at some point,
# making this scan the only reliable signal) — first match is access key,
# second is secret key.
_KEY_RE = re.compile(r'value=["\']([A-Za-z0-9]{16})["\']')
_USER_AGENT = "romgi/1.0 (server-side Internet Archive login; contact via project repo)"

# For the browser-driven login only (not the requests.Session calls below,
# which aren't going through a JS-capable bot-detection layer): a real
# desktop Chrome UA, not the honest romgi/1.0 one above, and not
# Playwright's own default — confirmed live that Playwright's default
# headless Chromium sets navigator.webdriver = true and puts
# "HeadlessChrome" in its own User-Agent, both trivial automation
# fingerprints, and login attempts were being silently rejected with the
# *exact same* generic bad_login response a real wrong password gets, with
# no way to tell the two apart from the response alone. _browser_login's
# launch args + init script below neutralize both signals.
_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class InternetArchiveLoginError(Exception):
    """Raised with a user-facing message; never leaves a stored session
    modified on failure — mirrors the Dart invariant that a failed
    attempt must not clobber a possibly-still-valid existing session."""


def _browser_login(username: str, password: str) -> dict[str, str]:
    """Drives the real login SPA in a headless browser and returns the
    resulting cookie jar as a plain dict. Raises InternetArchiveLoginError
    on any failure (network, page-structure drift, or a genuine bad-login
    response) — never leaks which of those it was beyond a generic
    user-facing message, matching the previous cookie-sniffing behavior."""
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True, args=["--disable-blink-features=AutomationControlled"]
            )
            try:
                page = browser.new_page(user_agent=_BROWSER_USER_AGENT)
                page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
                # domcontentloaded, not networkidle: this page keeps
                # background analytics/error-reporting beacons open
                # indefinitely, so "network idle" never actually fires —
                # confirmed live, wait_for_selector below is what actually
                # gates on the login widget being ready.
                page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=REQUEST_TIMEOUT * 1000)
                page.wait_for_selector("#password-input", state="visible", timeout=REQUEST_TIMEOUT * 1000)
                page.fill("#email-input", username)
                page.fill("#password-input", password)

                # On a successful login archive.org redirects immediately,
                # which can race the response body being read at all
                # (confirmed live: reading it — even eagerly, inside the
                # response event handler — sometimes gets nothing, no
                # exception either, just an empty result) — but the status
                # code survives that race even when the body doesn't. Only
                # use status here (200 = request went through, 400 = the
                # confirmed live shape of a bad_login rejection); let the
                # cookie check just below (proven reliable) be the actual
                # authority on whether the login itself succeeded, exactly
                # like the old cookie-sniffing check did pre-SPA-rewrite.
                result: dict = {}

                def _on_response(resp):
                    if resp.url == LOGIN_API_URL and "status" not in result:
                        result["status"] = resp.status

                page.on("response", _on_response)
                page.locator("#password-input").press("Enter")
                for _ in range(REQUEST_TIMEOUT * 10):
                    if "status" in result:
                        break
                    page.wait_for_timeout(100)

                if "status" not in result:
                    raise InternetArchiveLoginError("Could not reach archive.org")
                if result["status"] not in (200, 302):
                    raise InternetArchiveLoginError("Invalid Internet Archive username or password")

                return {c["name"]: c["value"] for c in page.context.cookies()}
            finally:
                browser.close()
    except PlaywrightTimeoutError as exc:
        raise InternetArchiveLoginError("Could not reach archive.org") from exc


def login(username: str, password: str) -> dict:
    """Returns {username, access_key, secret_key, cookies} on success.
    Doesn't touch the DB — the caller (the login Celery task) decides
    whether/how to persist it."""
    cookies = _browser_login(username, password)
    if "logged-in-user" not in cookies:
        raise InternetArchiveLoginError("Invalid Internet Archive username or password")

    session = requests.Session()
    session.headers["User-Agent"] = _USER_AGENT
    session.cookies.update(cookies)

    keys = _fetch_s3_keys(session)
    if keys is None:
        raise InternetArchiveLoginError("Could not retrieve Internet Archive credentials. Please try again.")

    access_key, secret_key = keys
    cookie_header = "; ".join(f"{k}={v}" for k, v in cookies.items())

    return {
        "username": cookies.get("logged-in-user", username),
        "access_key": access_key,
        "secret_key": secret_key,
        "cookies": cookie_header,
    }


def _fetch_s3_keys(session: requests.Session) -> tuple[str, str] | None:
    try:
        resp = session.get(S3_KEYS_URL, timeout=REQUEST_TIMEOUT)
        keys = _KEY_RE.findall(resp.text)
        if len(keys) < 2:
            # No existing keypair shown — ask archive.org to generate one,
            # the same fallback the WebView's injected JS used.
            resp = session.post(
                S3_KEYS_URL, data={"generateNewKeys": "Generate New Keys", "confirm": "on"}, timeout=REQUEST_TIMEOUT
            )
            keys = _KEY_RE.findall(resp.text)
    except requests.RequestException:
        return None
    if len(keys) < 2:
        return None
    return keys[0], keys[1]


def validate(credential: EncryptedCredential) -> str:
    """HEAD-probes the S3 auth endpoint with the stored keys — ports
    IAAuthManager.validate(). Persists the resolved status (+ resets
    failure_count on success) and returns it."""
    data = credential.data or {}
    access_key = data.get("access_key")
    secret_key = data.get("secret_key")

    if not access_key or not secret_key:
        status = "invalid"
    else:
        try:
            resp = requests.head(
                PROBE_URL, headers={"Authorization": f"LOW {access_key}:{secret_key}"}, timeout=PROBE_TIMEOUT
            )
            if 200 <= resp.status_code < 300:
                status = "ok"
            elif resp.status_code in (401, 403):
                status = "invalid"
            else:
                status = "stale"
        except requests.RequestException:
            status = "stale"

    credential.last_validated_at = timezone.now()
    credential.status = status
    if status == "ok":
        credential.failure_count = 0
    credential.save(update_fields=["last_validated_at", "status", "failure_count"])
    return status


def ensure_fresh(credential: EncryptedCredential) -> None:
    if credential.last_validated_at is None or timezone.now() - credential.last_validated_at >= STALE_AFTER:
        validate(credential)


def record_auth_failure(credential: EncryptedCredential) -> None:
    """One "strike" per observed 401/403 on a real download request (not
    called from validate() itself) — mirrors IAAuthManager's 3-strike
    circuit breaker. The only way to clear strikes is a successful
    validate() (see above) or a brand-new login."""
    credential.failure_count += 1
    if credential.failure_count >= MAX_FAILURES:
        credential.status = "invalid"
    credential.save(update_fields=["failure_count", "status"])


def is_logged_in(credential: EncryptedCredential) -> bool:
    return credential.failure_count < MAX_FAILURES and credential.status != "invalid"


def apply_headers(credential: EncryptedCredential, headers: dict) -> None:
    """Cookie-based auth is preferred (required for archive.org/download/...
    URLs); the S3 LOW-auth header is the fallback for anything under
    s3.us.archive.org or IA's S3-compatible API."""
    data = credential.data or {}
    cookies = data.get("cookies")
    if cookies:
        headers["Cookie"] = cookies
        headers["Referer"] = "https://archive.org/"
        return
    access_key = data.get("access_key")
    secret_key = data.get("secret_key")
    if access_key and secret_key:
        headers["Authorization"] = f"LOW {access_key}:{secret_key}"
