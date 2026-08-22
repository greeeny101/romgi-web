"""
Pytest configuration.

The project has no test suite by convention (see README) — auth is the
exception, because "the lockout still works" is not something anyone can
usefully verify by clicking around, and a regression here is a security
regression rather than a broken screen.
"""

import pytest
from django.core.cache import cache


@pytest.fixture(autouse=True)
def _isolate_cache(settings):
    """
    Keep throttle and lockout state out of the shared Redis cache and out of
    each other's way. Redis db 3 belongs to the running instance; a test run
    must neither read its counters nor leave any behind.
    """
    settings.CACHES = {
        "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}
    }
    cache.clear()
    yield
    cache.clear()


@pytest.fixture(autouse=True)
def _predictable_auth_settings(settings):
    settings.LOGIN_FAILURE_LIMIT = 3
    settings.LOGIN_FAILURE_WINDOW_SECONDS = 900
    settings.LOGIN_LOCKOUT_SECONDS = 900
    settings.FRONTEND_BASE_URL = "http://testserver"
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"


@pytest.fixture
def api_client():
    """
    Ninja's test client bound to the real API, so tests exercise routing,
    schema validation, auth and throttling exactly as a browser would.
    """
    from ninja.testing import TestClient

    from apps.accounts.api import router

    return TestClient(router)
