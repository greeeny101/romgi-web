from apps.credentials.models import EncryptedCredential
from apps.credentials.services import internet_archive as ia

from .base import HostAdapter


class InternetArchiveAdapter(HostAdapter):
    """Ports Dart's InternetArchiveAdapter onto the credentials vault."""

    auth_error = "Internet Archive login required"

    def can_start_download(self, task, user) -> bool:
        if not task.link_requires_auth:
            return True
        credential = self._credential(user)
        return credential is not None and ia.is_logged_in(credential)

    def prepare_headers(self, headers, task) -> None:
        credential = self._credential(task.user)
        if credential is None:
            return
        ia.ensure_fresh(credential)
        credential.refresh_from_db()
        ia.apply_headers(credential, headers)

    def on_auth_failure(self, task, user) -> None:
        credential = self._credential(user)
        if credential is not None:
            ia.record_auth_failure(credential)

    @staticmethod
    def _credential(user) -> EncryptedCredential | None:
        return EncryptedCredential.objects.filter(user=user, provider="internet_archive").first()
