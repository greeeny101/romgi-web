"""
ASGI config for config project.

Routes plain HTTP requests to Django (which serves the Django Ninja API
under /api/, mounted in config/urls.py) and WebSocket connections to
Channels consumers (currently just the live download/torrent progress
feed in apps.realtime). Both run in the same ASGI process.
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")

# Must be called before importing anything that touches models/apps —
# this populates Django's app registry.
django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402

from apps.realtime.auth import JWTAuthMiddlewareStack  # noqa: E402
from apps.realtime.routing import websocket_urlpatterns  # noqa: E402

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": JWTAuthMiddlewareStack(URLRouter(websocket_urlpatterns)),
    }
)
