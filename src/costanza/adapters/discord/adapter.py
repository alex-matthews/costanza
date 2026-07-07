"""Discord notifier adapter — the ONLY module importing discord.py (ADR-0001).

Runs as a supervised in-process async task. Its failure modes (bad token,
gateway outage, library churn) surface as NotifierUnavailable to the
notification worker, which leaves ledger rows pending/failed — ingestion
and jobs never await Discord and never crash because of it.
"""

from __future__ import annotations

import asyncio

import discord

from ...config import RoutingConfig
from ...logging import get_logger
from ...notify.ports import NotifierUnavailable
from ...schemas import RenderedMessage

log = get_logger(__name__)

_RECONNECT_BACKOFF_SECONDS = 30.0


def build_embed(message: RenderedMessage) -> discord.Embed:
    embed = discord.Embed(
        title=message.title[:256],
        description=message.description[:4000] if message.description else None,
        colour=message.color,
    )
    for name, value in message.fields[:25]:
        embed.add_field(name=str(name)[:256], value=str(value)[:1024], inline=False)
    if message.footer:
        embed.set_footer(text=message.footer[:2048])
    return embed


class DiscordNotifier:
    """Notifier-port implementation publishing embeds to mapped channels."""

    def __init__(self, token: str, routing: RoutingConfig):
        self._token = token
        self._channel_ids = {
            name: cfg.discord_channel_id
            for name, cfg in routing.channels.items()
            if cfg.discord_channel_id
        }
        self._client: discord.Client | None = None
        self._task: asyncio.Task | None = None
        self._stopping = False

    # -- lifecycle (supervised task) ------------------------------------------

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.get_running_loop().create_task(
                self._supervise(), name="discord-adapter"
            )

    async def _supervise(self) -> None:
        while not self._stopping:
            self._client = discord.Client(intents=discord.Intents.none())
            try:
                log.info("discord adapter connecting")
                await self._client.start(self._token)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — bot crash must never propagate
                log.error("discord client crashed", error=f"{type(exc).__name__}: {exc}")
            finally:
                if not self._client.is_closed():
                    await self._client.close()
                self._client = None
            if not self._stopping:
                await asyncio.sleep(_RECONNECT_BACKOFF_SECONDS)

    async def stop(self) -> None:
        self._stopping = True
        client, task = self._client, self._task
        if client is not None and not client.is_closed():
            await client.close()
        if task is not None:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._task = None

    # -- notifier port ----------------------------------------------------------

    async def send(self, channel: str, message: RenderedMessage) -> None:
        channel_id = self._channel_ids.get(channel)
        if channel_id is None:
            raise NotifierUnavailable(f"no discord_channel_id configured for {channel!r}")
        client = self._client
        if client is None or client.is_closed() or not client.is_ready():
            raise NotifierUnavailable("discord client is not connected")
        target = client.get_channel(channel_id)
        if target is None:
            target = await client.fetch_channel(channel_id)
        await target.send(embed=build_embed(message))
