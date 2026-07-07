"""Notifier port (ADR-0001): everything channel-shaped goes through here.

Core modules import this protocol, never a channel library. The Discord
adapter implements it; tests use fakes; a future ntfy/Apprise adapter is a
leaf change.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..schemas import RenderedMessage


class NotifierUnavailable(Exception):
    """The channel is temporarily down; the ledger row stays pending/failed."""


@runtime_checkable
class Notifier(Protocol):
    async def send(self, channel: str, message: RenderedMessage) -> None:
        """Deliver a rendered message to a named channel. Raises on failure."""
        ...
