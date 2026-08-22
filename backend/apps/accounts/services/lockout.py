"""
Per-account login lockout.

The per-IP throttles on the auth endpoints (ninja.throttling) cap how fast one
host can guess, but they do nothing about the realistic attack on a small
multi-user instance: a botnet trying one password against one account from many
addresses. This module counts failures per *account* instead, across every
entry point.

State lives in the shared Redis cache (settings.CACHES), not in the database:
these counters are hot, short-lived and worthless after their window expires.
That does mean a cache flush clears every lockout — acceptable for a
rate-limiting control, and the reason this is not the only defence.

NOTE: requires a cross-process cache. On Django's default LocMemCache each
daphne/celery process would keep a private counter and the limit would
effectively multiply by the process count. See the CACHES comment in
config/settings/base.py.
"""

import hashlib
import logging

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger("romgi.auth")

_PREFIX = "auth:lockout:"


def _key(email: str) -> str:
    # Hashed so the cache never holds a plaintext list of this instance's
    # registered addresses, and to keep the key safe for any address shape.
    digest = hashlib.sha256((email or "").strip().casefold().encode()).hexdigest()
    return f"{_PREFIX}{digest}"


def is_locked(email: str) -> bool:
    return cache.get(_key(email), 0) >= settings.LOGIN_FAILURE_LIMIT


def record_failure(email: str) -> int:
    """Count one failed attempt. Returns the new total."""
    key = _key(email)
    # add() only sets when absent, so the window starts at the first failure
    # and is not extended by later ones — a fixed window, not a sliding one.
    cache.add(key, 0, settings.LOGIN_FAILURE_WINDOW_SECONDS)
    try:
        count = cache.incr(key)
    except ValueError:
        # Entry expired between add() and incr().
        cache.set(key, 1, settings.LOGIN_FAILURE_WINDOW_SECONDS)
        count = 1

    if count == settings.LOGIN_FAILURE_LIMIT:
        # Hold the lock for its own duration rather than the window's, so the
        # cooldown is predictable regardless of when in the window it tripped.
        cache.touch(key, settings.LOGIN_LOCKOUT_SECONDS)
        logger.warning("Account locked after %s failed logins: %s", count, email)
    return count


def clear(email: str) -> None:
    cache.delete(_key(email))
