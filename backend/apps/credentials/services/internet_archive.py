"""
Server-side port of internet_archive_auth_manager.dart. The Dart app never
POSTs credentials itself — it loads archive.org's own login page in a
WebView and lets the browser handle auth, then scrapes S3 keys out of
https://archive.org/account/s3.php using the resulting session cookies
(via JS injected into the WebView, so it gets HttpOnly cookies too). A
server has no WebView, so `login()` below does the equivalent with a
`requests.Session`: POST the login form directly, then run the identical
s3.php scrape/generate-keys flow the WebView's injected JS used.

NOTE: the exact login form field names (`username`/`password`/...) were
not independently re-verified against archive.org's live markup in this
session — archive.org was unreachable from the dev sandbox this was built
in (connection refused on every attempt), unlike screenscraper.fr/
steamgriddb.com which were reachable and whose integrations *are*
live-verified. These field names match the long-standing, widely-used
`internetarchive` Python package's login flow, but this specific code path
has not been exercised against a real login. The failure mode if a field
name has drifted is graceful (no `logged-in-user` cookie comes back, which
`login()` reports as "invalid username or password" rather than crashing)
but this is flagged here so it gets a real test with live credentials
before being relied on.
"""

import re

import requests
from django.utils import timezone

from apps.credentials.models import EncryptedCredential

LOGIN_URL = "https://archive.org/account/login"
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


class InternetArchiveLoginError(Exception):
    """Raised with a user-facing message; never leaves a stored session
    modified on failure — mirrors the Dart invariant that a failed
    attempt must not clobber a possibly-still-valid existing session."""


def login(username: str, password: str) -> dict:
    """Returns {username, access_key, secret_key, cookies} on success.
    Doesn't touch the DB — the caller (the login Celery task) decides
    whether/how to persist it."""
    session = requests.Session()
    session.headers["User-Agent"] = _USER_AGENT

    try:
        session.post(
            LOGIN_URL,
            data={"username": username, "password": password, "remember": "true", "submit-to-login": "1"},
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
        )
    except requests.RequestException as exc:
        raise InternetArchiveLoginError("Could not reach archive.org") from exc

    cookies = session.cookies.get_dict()
    if "logged-in-user" not in cookies:
        raise InternetArchiveLoginError("Invalid Internet Archive username or password")

    keys = _fetch_s3_keys(session)
    if keys is None:
        raise InternetArchiveLoginError("Could not retrieve Internet Archive credentials. Please try again.")

    access_key, secret_key = keys
    cookie_header = "; ".join(f"{k}={v}" for k, v in session.cookies.get_dict().items())

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
