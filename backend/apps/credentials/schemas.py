from ninja import Schema


class InternetArchiveLoginIn(Schema):
    username: str
    password: str


class InternetArchiveKeysIn(Schema):
    access_key: str
    secret_key: str


class LoginTaskOut(Schema):
    task_id: str


class LoginStatusOut(Schema):
    state: str  # pending|success|error
    message: str | None = None


class InternetArchiveStatusOut(Schema):
    logged_in: bool
    username: str | None
    status: str
    last_validated_at: str | None


class CredentialFieldOut(Schema):
    key: str
    label: str
    obscure: bool = False
    optional: bool = False


class CredentialIn(Schema):
    data: dict[str, str]


class CredentialStatusOut(Schema):
    provider: str
    configured: bool
    status: str
    # What the vault actually holds, so the settings form can prove a save
    # landed instead of silently blanking every box. Obscure fields are
    # reported by name only (stored_keys); non-secret ones (a username, a
    # developer ID) come back in stored_values so they can be shown.
    fields: list[CredentialFieldOut] = []
    stored_keys: list[str] = []
    stored_values: dict[str, str] = {}


class TestResultOut(Schema):
    ok: bool
    message: str | None = None
