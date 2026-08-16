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
    CredentialIn,
    CredentialStatusOut,
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
    _provider_or_404(kind, provider_id)
    credential, _ = EncryptedCredential.objects.update_or_create(
        user=request.user,
        provider=provider_id,
        defaults={"data": payload.data, "status": "unverified", "failure_count": 0},
    )
    return CredentialStatusOut(provider=provider_id, configured=True, status=credential.status)


@router.get("/{kind}/{provider_id}", response=CredentialStatusOut)
def get_credential_status(request, kind: str, provider_id: str):
    _provider_or_404(kind, provider_id)
    credential = EncryptedCredential.objects.filter(user=request.user, provider=provider_id).first()
    if credential is None:
        return CredentialStatusOut(provider=provider_id, configured=False, status="unverified")
    return CredentialStatusOut(provider=provider_id, configured=True, status=credential.status)


@router.post("/{kind}/{provider_id}/test", response=TestResultOut)
def test_credential(request, kind: str, provider_id: str):
    provider = _provider_or_404(kind, provider_id)
    credential = EncryptedCredential.objects.filter(user=request.user, provider=provider_id).first()
    if credential is None or not _is_configured(kind, provider, credential.data):
        return TestResultOut(ok=False, message="No credentials set")

    error = _validate(kind, provider, credential.data)
    credential.status = "invalid" if error else "ok"
    credential.last_validated_at = timezone.now()
    credential.save(update_fields=["status", "last_validated_at"])
    return TestResultOut(ok=error is None, message=error)


@router.delete("/{kind}/{provider_id}", response={204: None})
def delete_credential(request, kind: str, provider_id: str):
    EncryptedCredential.objects.filter(user=request.user, provider=provider_id).delete()
    return 204, None
