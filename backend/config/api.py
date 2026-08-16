"""
Root Django Ninja API. Mounted at /api/ in config/urls.py, alongside (not
instead of) the Channels WebSocket route in config/asgi.py — see the plan's
"Django Ninja owns the entire REST API; Channels adds only a progress
WebSocket" decision.
"""

from ninja import NinjaAPI

from apps.accounts.api import router as accounts_router
from apps.accounts.api import settings_router
from apps.catalog.api import router as catalog_router
from apps.credentials.api import router as credentials_router
from apps.downloads.api import router as downloads_router
from apps.library.api import router as library_router
from apps.metadata.api import router as metadata_router

api = NinjaAPI(title="romgi API", version="1.0.0")

api.add_router("/catalog", catalog_router)
api.add_router("/auth", accounts_router)
api.add_router("/settings", settings_router)
api.add_router("/library", library_router)
api.add_router("/downloads", downloads_router)
api.add_router("/credentials", credentials_router)
api.add_router("/metadata", metadata_router)
