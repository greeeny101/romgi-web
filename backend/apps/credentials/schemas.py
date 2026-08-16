from ninja import Schema


class InternetArchiveLoginIn(Schema):
    username: str
    password: str


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


class CredentialIn(Schema):
    data: dict[str, str]


class CredentialStatusOut(Schema):
    provider: str
    configured: bool
    status: str


class TestResultOut(Schema):
    ok: bool
    message: str | None = None
