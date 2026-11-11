import asyncio

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from .models import Order, ShopperToken


class TrackConsumer(AsyncJsonWebsocketConsumer):
    """A customer watching one order. The first message must be {"type": "auth", "token": "<customer token>"}: the token
    is sent inside the connection, never in the web address, so it does not end up in server logs."""

    async def connect(self):
        self.order_id = int(self.scope["url_route"]["kwargs"]["order_id"])
        self.group = None
        await self.accept()
        self._guard = asyncio.create_task(self._close_if_not_signed_in())

    async def _close_if_not_signed_in(self):
        await asyncio.sleep(10)
        if self.group is None:
            await self.close(code=4401)

    async def receive_json(self, content, **kwargs):
        kind = content.get("type")
        if kind == "ping":
            await self.send_json({"type": "pong"})
            return
        if kind != "auth" or self.group is not None:
            return
        if not await self._may_watch(str(content.get("token", ""))):
            await self.close(code=4401)
            return
        self.group = f"track_{self.order_id}"
        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.send_json({"type": "ready"})

    @database_sync_to_async
    def _may_watch(self, key):
        token = ShopperToken.objects.select_related("shopper").filter(key=key).first()
        if token is None or not token.shopper.is_active:
            return False
        return Order.objects.filter(pk=self.order_id, shopper=token.shopper).exists()

    async def track_message(self, event):
        await self.send_json(event["data"])

    async def disconnect(self, code):
        guard = getattr(self, "_guard", None)
        if guard:
            guard.cancel()
        if getattr(self, "group", None):
            await self.channel_layer.group_discard(self.group, self.channel_name)