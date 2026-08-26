"""
HTTP session that keeps Internet Archive credentials alive across
archive.org's redirects.

Extracted from apps.downloads.tasks so the ROM-set browser can reuse it
rather than reimplement it. Duplicating this is a trap: a plain
`requests.get` against a `/download/` URL looks like it works, silently
loses its credentials on the redirect to the node host, and comes back 401
for restricted items only — so the bug hides until someone tries a
login-gated item. That is exactly how it resurfaced in apps.romsets.
"""

from urllib.parse import urlparse

import requests


def same_registrable_domain(a: str, b: str) -> bool:
    """True when two URLs sit on the same registrable domain, approximated
    as the last two labels of the hostname. Good enough for the hosts this
    pipeline actually talks to (archive.org and its node servers); it would
    be too permissive for a multi-label public suffix like .co.uk, so keep
    it out of any security decision beyond "may this credential follow this
    redirect"."""
    host_a = (urlparse(a).hostname or "").lower()
    host_b = (urlparse(b).hostname or "").lower()
    if not host_a or not host_b:
        return False
    return host_a == host_b or ".".join(host_a.split(".")[-2:]) == ".".join(host_b.split(".")[-2:])


class CredentialPreservingSession(requests.Session):
    """requests deliberately drops credentials when a redirect changes
    host: `rebuild_auth` deletes the Authorization header, and
    `resolve_redirects` pops the Cookie header outright. That is the right
    default for a redirect to a stranger, but archive.org/download/ URLs
    *always* redirect to a per-item node host (dn711101.ca.archive.org,
    ia800901.us.archive.org, ...), so both credentials were being discarded
    exactly when they were needed — confirmed live, every auth variant
    arrived at the node anonymous and got 401/403, which surfaced to the
    user as "Internet Archive login required" no matter how they'd logged
    in.

    Re-attaching Authorization across a same-domain redirect fixes the S3
    keys; cookies are handled by putting them in the session jar (see
    session_for) instead of pinning a Cookie header, which lets requests
    scope and re-send them per host the way a browser would."""

    def rebuild_auth(self, prepared_request, response):
        kept = prepared_request.headers.get("Authorization")
        super().rebuild_auth(prepared_request, response)
        if (
            kept
            and "Authorization" not in prepared_request.headers
            and same_registrable_domain(response.request.url, prepared_request.url)
        ):
            prepared_request.headers["Authorization"] = kept


def session_for(url: str, headers: dict) -> requests.Session:
    """Builds the download session, moving any `Cookie` header the adapter
    set into the cookie jar so it survives redirects. Mutates `headers`:
    the Cookie entry is consumed, because leaving it in place would have
    requests fighting its own jar."""
    session = CredentialPreservingSession()
    cookie_header = headers.pop("Cookie", None)
    if not cookie_header:
        return session
    host = (urlparse(url).hostname or "").lower()
    domain = "." + ".".join(host.split(".")[-2:]) if host else ""
    for part in cookie_header.split(";"):
        name, _, value = part.strip().partition("=")
        if name:
            session.cookies.set(name, value, domain=domain)
    return session
