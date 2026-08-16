"""
Fernet-encrypted JSON field.

Replaces flutter_secure_storage's per-device OS-level encryption: credentials
(Internet Archive session, debrid/metadata API keys) now live server-side,
per-user, encrypted at rest with a key from settings.ENCRYPTION_KEY (.env).
"""

import json

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


def _fernet() -> Fernet:
    return Fernet(settings.ENCRYPTION_KEY.encode() if isinstance(settings.ENCRYPTION_KEY, str) else settings.ENCRYPTION_KEY)


class EncryptedJSONField(models.TextField):
    """Stores an arbitrary JSON-serializable dict as Fernet ciphertext."""

    description = "Fernet-encrypted JSON"

    def from_db_value(self, value, expression, connection):
        if value is None or value == "":
            return None
        try:
            plaintext = _fernet().decrypt(value.encode())
        except InvalidToken as exc:
            raise ValidationError("Could not decrypt stored credential data.") from exc
        return json.loads(plaintext.decode())

    def to_python(self, value):
        if value is None or isinstance(value, dict):
            return value
        if isinstance(value, (bytes, bytearray)):
            value = value.decode()
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return value

    def get_prep_value(self, value):
        if value is None:
            return None
        plaintext = json.dumps(value).encode()
        return _fernet().encrypt(plaintext).decode()
