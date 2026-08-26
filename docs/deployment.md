# Security & deployment

[← back to README](../README.md)

`backend/config/settings/production.py` sets `DEBUG=False`, HSTS, secure
cookies, and S3-compatible object storage for static files. Read it before
deploying — several values (`ALLOWED_HOSTS`, `AWS_STORAGE_BUCKET_NAME`,
`CSRF_TRUSTED_ORIGINS`, etc.) are required and have no defaults. See
[`KNOWN_ISSUES.md`](../KNOWN_ISSUES.md) for what production storage does *not*
yet cover (staged downloads stay on local disk).

## Auth model

- **Invite-only registration.** `POST /api/auth/register` requires an unused
  invite code; there is no open signup path.
- **Rate limiting and lockout.** Per-IP throttles on every unauthenticated
  endpoint, plus a per-account lockout (`LOGIN_FAILURE_LIMIT`) that counts
  failures from the API and the Django admin form alike. Both need a shared
  cache — set `CACHE_URL`, and see the `CACHES` note in `settings/base.py`.
- **Set `NINJA_NUM_PROXIES`** to the number of reverse proxies in front of
  daphne. Leaving it wrong lets a client forge `X-Forwarded-For` and walk past
  every throttle above.
- **Rotating refresh tokens.** `/auth/refresh` returns a new pair and
  blacklists the old token; users can list and revoke their own sessions from
  Settings → Account.
- **Not indexed.** `static/robots.txt` and the `noindex` tag in `src/app.html`
  keep this private instance out of search results.
- **No 2FA yet.** The token path is structured for it (see the docstring in
  `apps/accounts/services/auth.py`), but it isn't built.
