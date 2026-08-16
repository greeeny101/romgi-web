"""
Channels' built-in AuthMiddlewareStack assumes session auth. The rest of the
API is JWT-only (django-ninja-jwt), so WebSocket connections authenticate the
same way instead: a `?token=<access_token>` query param, validated with the
same token backend Ninja's HttpBearer uses — no session/cookie middleware
needed.

Full progress-consumer wiring lands in Phase 3; this exists now so
config/asgi.py has something real to import.
"""

from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.contrib.auth.models import AnonymousUser


@database_sync_to_async
def _user_from_token(token: str):
    from django.contrib.auth import get_user_model
    from ninja_jwt.exceptions import TokenError
    from ninja_jwt.tokens import AccessToken

    try:
        access = AccessToken(token)
    except TokenError:
        return AnonymousUser()

    User = get_user_model()
    try:
        return User.objects.get(pk=access["user_id"])
    except User.DoesNotExist:
        return AnonymousUser()


class JWTAuthMiddleware(BaseMiddleware):
    async def __call__(self, scope, receive, send):
        query_string = scope.get("query_string", b"").decode()
        token = parse_qs(query_string).get("token", [None])[0]
        scope["user"] = await _user_from_token(token) if token else AnonymousUser()
        return await super().__call__(scope, receive, send)


def JWTAuthMiddlewareStack(inner):
    return JWTAuthMiddleware(inner)
