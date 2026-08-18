"""
Credentials vault endpoints. Internet Archive gets a dedicated async login
flow (server-side scrape of archive.org's S3-key page — see
services/internet_archive.py); debrid and metadata providers are simple
stored-secret + test-connection flows (PUT/POST test/DELETE), matching
DebridService/GameMetadataService's setCredentials/testConnection/
clearCredentials shape from the original app.
"""

from celery.result import AsyncResult
from django.utils import timezone
from ninja import Router
from ninja.errors import HttpError
from ninja_jwt.authentication import JWTAuth

from apps.downloads.debrid.registry import registry as debrid_registry
from apps.metadata.providers.registry import registry as metadata_registry

from .models import EncryptedCredential
from .schemas import (
    CredentialFieldOut,
    CredentialIn,
    CredentialStatusOut,
    InternetArchiveKeysIn,
    InternetArchiveLoginIn,
    InternetArchiveStatusOut,
    LoginStatusOut,
    LoginTaskOut,
    TestResultOut,
)
from .services import internet_archive
from .tasks import internet_archive_login

router = Router(tags=["credentials"], auth=JWTAuth())

_REGISTRIES = {"debrid": debrid_registry, "metadata": metadata_registry}


@router.post("/internet-archive/login", response={202: LoginTaskOut})
def ia_login(request, payload: InternetArchiveLoginIn):
    result = internet_archive_login.delay(request.user.id, payload.username, payload.password)
    return 202, LoginTaskOut(task_id=result.id)


@router.get("/internet-archive/login/{task_id}", response=LoginStatusOut)
def ia_login_status(request, task_id: str):
    result = AsyncResult(task_id)
    if not result.ready():
        return LoginStatusOut(state="pending")
    if result.successful():
        return LoginStatusOut(state="success")
    return LoginStatusOut(state="error", message=str(result.result))


@router.put("/internet-archive/keys", response=InternetArchiveStatusOut)
def ia_set_keys(request, payload: InternetArchiveKeysIn):
    """The manual alternative to the username/password flow: the user
    signs in to archive.org in their own browser and pastes the keypair
    from /account/s3.php. Unlike the login flow this needs no headless
    browser, so it verifies the keys inline and answers directly instead
    of going through Celery."""
    try:
        data = internet_archive.login_with_keys(payload.access_key, payload.secret_key)
    except internet_archive.InternetArchiveLoginError as exc:
        # 400, not 500: every failure here is either keys the user can
        # correct or archive.org being unreachable.
        raise HttpError(400, str(exc)) from exc

    # Carry over a cookie session already on file for the same account.
    # apply_headers prefers cookies for archive.org/download/ URLs, and
    # pasting keys is meant to *add* a durable credential, not throw away
    # a working session. Keys for a different account get a clean slate —
    # those cookies belong to someone else.
    existing = EncryptedCredential.objects.filter(user=request.user, provider="internet_archive").first()
    if existing:
        previous = existing.data or {}
        same_account = internet_archive.normalize_username(previous.get("username", "")) == data["username"]
        if previous.get("cookies") and same_account:
            data["cookies"] = previous["cookies"]

    credential, _ = EncryptedCredential.objects.update_or_create(
        user=request.user,
        provider="internet_archive",
        defaults={
            "data": data,
            "status": "ok",
            "failure_count": 0,
            "last_validated_at": timezone.now(),
        },
    )
    return InternetArchiveStatusOut(
        logged_in=True,
        username=data["username"],
        status=credential.status,
        last_validated_at=credential.last_validated_at.isoformat(),
    )


@router.get("/internet-archive/status", response=InternetArchiveStatusOut)
def ia_status(request):
    credential = EncryptedCredential.objects.filter(user=request.user, provider="internet_archive").first()
    if credential is None:
        return InternetArchiveStatusOut(logged_in=False, username=None, status="unverified", last_validated_at=None)
    internet_archive.ensure_fresh(credential)
    credential.refresh_from_db()
    return InternetArchiveStatusOut(
        logged_in=internet_archive.is_logged_in(credential),
        username=(credential.data or {}).get("username"),
        status=credential.status,
        last_validated_at=credential.last_validated_at.isoformat() if credential.last_validated_at else None,
    )


@router.post("/internet-archive/logout", response={204: None})
def ia_logout(request):
    EncryptedCredential.objects.filter(user=request.user, provider="internet_archive").delete()
    return 204, None


def _provider_or_404(kind: str, provider_id: str):
    registry = _REGISTRIES.get(kind)
    if registry is None:
        raise HttpError(404, "Unknown credential kind.")
    provider = registry.by_id(provider_id)
    if provider is None:
        raise HttpError(404, f"Unknown provider: {provider_id}")
    return provider


_DEBRID_FIELDS = [CredentialFieldOut(key="api_key", label="API Key", obscure=True)]


def _fields(kind: str, provider) -> list[CredentialFieldOut]:
    """One description of a provider's credential shape, served to the
    settings form so it can't drift from what the provider actually
    requires (it did: ScreenScraper's developer credentials were rendered
    as optional while api2 rejects every request without them)."""
    if kind == "debrid":
        return list(_DEBRID_FIELDS)
    return [
        CredentialFieldOut(key=f.key, label=f.label, obscure=f.obscure, optional=f.optional)
        for f in provider.credential_fields
    ]


def _status_out(kind: str, provider, provider_id: str, credential: EncryptedCredential | None) -> CredentialStatusOut:
    data = (credential.data if credential else None) or {}
    fields = _fields(kind, provider)
    stored = {f.key: (data.get(f.key) or "").strip() for f in fields}
    return CredentialStatusOut(
        provider=provider_id,
        configured=credential is not None,
        status=credential.status if credential else "unverified",
        fields=fields,
        stored_keys=[f.key for f in fields if stored[f.key]],
        stored_values={f.key: stored[f.key] for f in fields if stored[f.key] and not f.obscure},
    )


def _is_configured(kind: str, provider, data: dict | None) -> bool:
    if kind == "debrid":
        return provider.is_configured((data or {}).get("api_key"))
    return provider.is_configured(data)


def _validate(kind: str, provider, data: dict | None) -> str | None:
    if kind == "debrid":
        return provider.validate_key((data or {}).get("api_key") or "")
    return provider.validate_credentials(data or {})


@router.put("/{kind}/{provider_id}", response=CredentialStatusOut)
def set_credential(request, kind: str, provider_id: str, payload: CredentialIn):
    """Merges into what's already stored rather than replacing it. The form
    never renders a saved secret back, so an omitted field means "leave it
    alone" — replacing wholesale meant filling in one box (a developer ID,
    say) silently wiped the username and password saved beside it. Use
    DELETE to actually clear a provider."""
    provider = _provider_or_404(kind, provider_id)
    existing = EncryptedCredential.objects.filter(user=request.user, provider=provider_id).first()
    data = dict((existing.data if existing else None) or {})
    for key, value in payload.data.items():
        value = (value or "").strip()
        if value:
            data[key] = value

    credential, _ = EncryptedCredential.objects.update_or_create(
        user=request.user,
        provider=provider_id,
        defaults={"data": data, "status": "unverified", "failure_count": 0},
    )
    return _status_out(kind, provider, provider_id, credential)


@router.get("/{kind}/{provider_id}", response=CredentialStatusOut)
def get_credential_status(request, kind: str, provider_id: str):
    provider = _provider_or_404(kind, provider_id)
    credential = EncryptedCredential.objects.filter(user=request.user, provider=provider_id).first()
    return _status_out(kind, provider, provider_id, credential)


@router.post("/{kind}/{provider_id}/test", response=TestResultOut)
def test_credential(request, kind: str, provider_id: str):
    provider = _provider_or_404(kind, provider_id)
    credential = EncryptedCredential.objects.filter(user=request.user, provider=provider_id).first()
    if credential is None:
        return TestResultOut(ok=False, message="No credentials set")
    if not _is_configured(kind, provider, credential.data):
        # Half-filled is the common case now that saving merges, so name the
        # gap instead of claiming nothing is stored.
        data = credential.data or {}
        missing = [f.label for f in _fields(kind, provider) if not f.optional and not (data.get(f.key) or "").strip()]
        return TestResultOut(ok=False, message=f"Missing required credentials: {', '.join(missing)}")

    error = _validate(kind, provider, credential.data)
    credential.status = "invalid" if error else "ok"
    credential.last_validated_at = timezone.now()
    credential.save(update_fields=["status", "last_validated_at"])
    return TestResultOut(ok=error is None, message=error)


@router.delete("/{kind}/{provider_id}", response={204: None})
def delete_credential(request, kind: str, provider_id: str):
    EncryptedCredential.objects.filter(user=request.user, provider=provider_id).delete()
    return 204, None
