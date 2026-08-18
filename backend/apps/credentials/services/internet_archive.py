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

import html
import json
import logging
import re
import urllib.parse

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

# Navigation is timed separately from, and far more generously than, the
# `requests` calls: archive.org/account/login is a JS-rendered SPA served
# from a notoriously variable-latency host, and a plain page.goto() of it
# was observed taking >20s live. The old code reused REQUEST_TIMEOUT (15s)
# for navigation, which turned an ordinary slow page load into a login
# failure. The response wait is separate again — once the form is
# submitted, the JSON reply itself comes back quickly.
NAV_TIMEOUT = 45
LOGIN_RESPONSE_TIMEOUT = 30

# archive.org answers a genuinely wrong password with HTTP 400 and
# {"success": false, "value": "bad_login", "error": "..."} (confirmed
# live). Any *other* non-2xx/3xx shape — a rate-limit, a captcha
# challenge, a bot-detection block, a 5xx — is something the user cannot
# fix by retyping their password, so it must not be reported as a bad
# password, and it is worth retrying once. Only bad_login is terminal.
BAD_LOGIN_REASON = "bad_login"
LOGIN_ATTEMPTS = 2

logger = logging.getLogger(__name__)

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
    attempt must not clobber a possibly-still-valid existing session.

    `retryable` says whether re-running the *same* attempt could plausibly
    succeed. A wrong password never can; a timeout, a bot-block or a 5xx
    often does, so those get one more go in a fresh browser before the
    user ever sees them."""

    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


def _describe_failure(status: int, body: str) -> tuple[str, str]:
    """Pulls (reason, human message) out of archive.org's JSON error body.

    Shape confirmed live:
        400 {"success": false,
             "error": "Email address and/or Password incorrect. <a ...>Forgot password?</a>",
             "value": "bad_login"}

    `error` is an HTML fragment, so tags are stripped and entities decoded
    before it's shown to anyone. Returns ("", "") when the body is missing
    or unparseable — which happens sometimes on the success path, where
    archive.org's immediate redirect can beat the body being readable at
    all (see _attempt_browser_login)."""
    try:
        payload = json.loads(body) if body else {}
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        return "", ""
    reason = str(payload.get("value") or "")
    message = html.unescape(re.sub(r"<[^>]+>", "", str(payload.get("error") or ""))).strip()
    return reason, message


def _attempt_browser_login(username: str, password: str) -> dict[str, str]:
    """One pass at driving the real login SPA in a headless browser.
    Returns the resulting cookie jar as a plain dict; raises
    InternetArchiveLoginError (with `retryable` set appropriately) on any
    failure. Callers go through _browser_login, which adds the retry."""
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
                page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=NAV_TIMEOUT * 1000)
                page.wait_for_selector("#password-input", state="visible", timeout=NAV_TIMEOUT * 1000)
                page.fill("#email-input", username)
                page.fill("#password-input", password)

                # On a successful login archive.org redirects immediately,
                # which can race the response body being read at all
                # (confirmed live: reading it — even eagerly, inside the
                # response event handler — sometimes gets nothing, no
                # exception either, just an empty result) — but the status
                # code survives that race even when the body doesn't. So
                # the status is what gates success, and the body is only
                # ever used to *explain* a failure: when it arrives it says
                # exactly why archive.org said no, and when it doesn't the
                # generic message below still stands on the status alone.
                result: dict = {}

                def _on_response(resp):
                    if resp.url == LOGIN_API_URL and "status" not in result:
                        result["status"] = resp.status
                        try:
                            result["body"] = resp.text()
                        except Exception:  # noqa: BLE001 — body lost to the redirect race, see above
                            result["body"] = ""

                page.on("response", _on_response)
                page.locator("#password-input").press("Enter")
                for _ in range(LOGIN_RESPONSE_TIMEOUT * 10):
                    if "status" in result:
                        break
                    page.wait_for_timeout(100)

                if "status" not in result:
                    raise InternetArchiveLoginError("Could not reach archive.org", retryable=True)

                status = result["status"]
                if status not in (200, 302):
                    reason, message = _describe_failure(status, result.get("body", ""))
                    # Logged, not just raised: when archive.org starts
                    # refusing logins for a reason that isn't a wrong
                    # password, this line is the only place that records
                    # *which* reason, and the old code threw it away.
                    logger.warning(
                        "Internet Archive login rejected: HTTP %s reason=%r message=%r",
                        status,
                        reason or "<none>",
                        message or "<none>",
                    )
                    if reason == BAD_LOGIN_REASON:
                        raise InternetArchiveLoginError("Invalid Internet Archive username or password")
                    # Not a bad password — so don't claim it was one.
                    # Prefer archive.org's own wording (it's the only
                    # thing that can explain a captcha/lockout/rate
                    # limit); fall back to the bare status.
                    raise InternetArchiveLoginError(
                        message or f"archive.org rejected the login (HTTP {status}). Please try again shortly.",
                        retryable=True,
                    )

                # The auth cookies land via Set-Cookie on that same
                # response, but the context's cookie jar isn't necessarily
                # updated by the time the response event fires — reading
                # it immediately (as this used to) could miss
                # logged-in-user on a perfectly good login and report it
                # as a wrong password. Give it a moment to settle.
                for _ in range(50):
                    cookies = {c["name"]: c["value"] for c in page.context.cookies()}
                    if "logged-in-user" in cookies:
                        return cookies
                    page.wait_for_timeout(100)
                raise InternetArchiveLoginError("Could not complete the Internet Archive login", retryable=True)
            finally:
                browser.close()
    except PlaywrightTimeoutError as exc:
        raise InternetArchiveLoginError("Could not reach archive.org", retryable=True) from exc


def _browser_login(username: str, password: str) -> dict[str, str]:
    """_attempt_browser_login plus one retry, in a brand-new browser, for
    failures that aren't a wrong password. archive.org's login endpoint is
    intermittently slow and occasionally refuses an automated-looking
    request outright; both were observed live, and both used to surface to
    the user as "invalid username or password" with no retry."""
    last: InternetArchiveLoginError | None = None
    for attempt in range(1, LOGIN_ATTEMPTS + 1):
        try:
            return _attempt_browser_login(username, password)
        except InternetArchiveLoginError as exc:
            if not exc.retryable:
                raise
            last = exc
            logger.warning(
                "Internet Archive login attempt %s/%s failed (%s)%s",
                attempt,
                LOGIN_ATTEMPTS,
                exc,
                "; retrying" if attempt < LOGIN_ATTEMPTS else "",
            )
    raise last  # type: ignore[misc]  # unreachable with LOGIN_ATTEMPTS >= 1


def normalize_username(value: str) -> str:
    """The two ways an account name reaches us disagree on encoding: the
    `logged-in-user` cookie carries it percent-encoded
    (marc%40example.com) while the S3 auth probe returns it plain
    (marc@example.com). Everything stored and compared goes through here
    so the two are actually comparable.

    Decoded repeatedly, not once: the cookie arrives *double*-encoded
    (marc%2540example.com), so a single unquote leaves a stray %40 behind
    and the two forms still don't match."""
    previous = value or ""
    for _ in range(3):
        decoded = urllib.parse.unquote(previous)
        if decoded == previous:
            break
        previous = decoded
    return previous.strip()


def login(username: str, password: str) -> dict:
    """Returns {username, access_key, secret_key, cookies} on success.
    Doesn't touch the DB — the caller (the login Celery task) decides
    whether/how to persist it."""
    cookies = _browser_login(username, password)
    # Belt-and-braces: _attempt_browser_login already waits for this
    # cookie and won't return without it.
    if "logged-in-user" not in cookies:
        raise InternetArchiveLoginError("Could not complete the Internet Archive login")

    session = requests.Session()
    session.headers["User-Agent"] = _USER_AGENT
    session.cookies.update(cookies)

    keys = _fetch_s3_keys(session)
    if keys is None:
        raise InternetArchiveLoginError("Could not retrieve Internet Archive credentials. Please try again.")

    access_key, secret_key = keys
    cookie_header = "; ".join(f"{k}={v}" for k, v in cookies.items())

    return {
        "username": normalize_username(cookies.get("logged-in-user") or username),
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
        logger.warning("Internet Archive S3 key fetch failed", exc_info=True)
        return None
    if len(keys) < 2:
        # Logged for the same reason the login rejection above is: this is
        # a *different* failure from a bad password (the session is fine,
        # s3.php just didn't yield a keypair) and used to be invisible.
        logger.warning("Internet Archive s3.php returned no usable keypair (found %s key-shaped values)", len(keys))
        return None
    return keys[0], keys[1]


def check_keys(access_key: str, secret_key: str) -> tuple[bool, dict]:
    """Probes a keypair against IA's S3 auth endpoint. Returns
    (reachable, payload) — `reachable` False means the network call
    itself failed and nothing can be concluded about the keys.

    The endpoint answers *200 for everything*, valid keys or not
    (confirmed live), so the HTTP status carries no authorization signal
    at all and only the JSON body does:

        authorized:   {"username": "...", "screenname": "...",
                       "itemname": "@...", "accesskey": "...",
                       "authorized": true}
        unauthorized: {"error": "The AWS Access Key Id you provided does
                       not exist in our records.", "accesskey": "...",
                       "authorized": false}

    It must be a GET, not a HEAD, for the same reason — a HEAD returns
    200 with no body whether or not the keys are any good."""
    try:
        resp = requests.get(
            PROBE_URL,
            headers={"Authorization": f"LOW {access_key}:{secret_key}", "User-Agent": _USER_AGENT},
            timeout=PROBE_TIMEOUT,
        )
        payload = resp.json()
    except (requests.RequestException, ValueError):
        return False, {}
    if not isinstance(payload, dict):
        return False, {}
    return True, payload


def validate(credential: EncryptedCredential) -> str:
    """Probes the S3 auth endpoint with the stored keys — ports
    IAAuthManager.validate(). Persists the resolved status (+ resets
    failure_count on success) and returns it."""
    data = credential.data or {}
    access_key = data.get("access_key")
    secret_key = data.get("secret_key")

    if not access_key or not secret_key:
        status = "invalid"
    else:
        reachable, payload = check_keys(access_key, secret_key)
        if not reachable:
            # Couldn't reach archive.org (or got something unparseable):
            # "stale" leaves the session usable and retries later, rather
            # than logging the user out over a blip.
            status = "stale"
        elif payload.get("authorized"):
            status = "ok"
        else:
            logger.info("Internet Archive keys rejected: %s", payload.get("error") or "<no reason given>")
            status = "invalid"

    credential.last_validated_at = timezone.now()
    credential.status = status
    if status == "ok":
        credential.failure_count = 0
    credential.save(update_fields=["last_validated_at", "status", "failure_count"])
    return status


def login_with_keys(access_key: str, secret_key: str) -> dict:
    """The keypair equivalent of login(): the user does the archive.org
    sign-in themselves and pastes the keys from
    https://archive.org/account/s3.php, so there's no browser to drive
    and no password to hold. Returns the same credential payload shape,
    minus `cookies` — apply_headers falls through to the S3 LOW header
    when there are none. Raises InternetArchiveLoginError if the keys
    don't check out."""
    access_key = access_key.strip()
    secret_key = secret_key.strip()
    if not access_key or not secret_key:
        raise InternetArchiveLoginError("Both the access key and the secret key are required")

    reachable, payload = check_keys(access_key, secret_key)
    if not reachable:
        raise InternetArchiveLoginError("Could not reach archive.org to verify the keys. Please try again.")
    if not payload.get("authorized"):
        raise InternetArchiveLoginError(
            payload.get("error") or "archive.org did not accept that access key and secret key"
        )

    return {
        "username": normalize_username(payload.get("username") or "") or access_key,
        "screenname": payload.get("screenname") or "",
        "access_key": access_key,
        "secret_key": secret_key,
    }


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
    """Applies *both* credentials when both are on file, rather than
    treating the S3 keys as a fallback only reached when there is no
    cookie.

    They fail independently — the session cookie can lapse while the
    keypair stays valid indefinitely — so sending only the cookie meant a
    stale session produced a 401 and a "login required" prompt even though
    a perfectly good keypair was sitting right there. Confirmed live
    against a login-gated item that cookie-only, key-only, and both
    together each return 206, so there is no downside to sending both."""
    data = credential.data or {}
    cookies = data.get("cookies")
    if cookies:
        headers["Cookie"] = cookies
        headers["Referer"] = "https://archive.org/"
    access_key = data.get("access_key")
    secret_key = data.get("secret_key")
    if access_key and secret_key:
        headers["Authorization"] = f"LOW {access_key}:{secret_key}"
