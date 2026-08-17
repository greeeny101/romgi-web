"""Progress WebSocket consumer — one connection per browser tab, grouped
per-user so every tab watching /downloads gets the same feed."""

from channels.generic.websocket import AsyncJsonWebsocketConsumer


class DownloadProgressConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        user = self.scope.get("user")
        if user is None or not user.is_authenticated:
            await self.close(code=4001)
            return
        self.group_name = f"user_{user.id}_downloads"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    # Dispatch target for group_send({"type": "download.event", ...}) —
    # Channels maps dots to underscores when routing to consumer methods.
    async def download_event(self, event):
        await self.send_json({"type": event["event"], "data": event["data"]})


class IngestionProgressConsumer(AsyncJsonWebsocketConsumer):
    """Progress WebSocket for the Sources page — a single global group,
    since Source/SourceHealth rows aren't user-owned (unlike downloads)."""

    GROUP_NAME = "ingestion_progress"

    async def connect(self):
        user = self.scope.get("user")
        if user is None or not user.is_authenticated:
            await self.close(code=4001)
            return
        await self.channel_layer.group_add(self.GROUP_NAME, self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        await self.channel_layer.group_discard(self.GROUP_NAME, self.channel_name)

    # Dispatch target for group_send({"type": "ingestion.event", ...}).
    async def ingestion_event(self, event):
        await self.send_json({"type": event["event"], "data": event["data"]})
