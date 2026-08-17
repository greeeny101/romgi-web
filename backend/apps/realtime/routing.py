from django.urls import re_path

from . import consumers

websocket_urlpatterns = [
    re_path(r"^ws/downloads/$", consumers.DownloadProgressConsumer.as_asgi()),
    re_path(r"^ws/ingestion/$", consumers.IngestionProgressConsumer.as_asgi()),
]
