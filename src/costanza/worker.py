"""Off-path processing: outbox rows -> normalize -> correlate -> notify fan-out.

This is the glue the webhook handler deliberately does not do. One
processor instance is shared by the outbox worker loop; notification
sending runs in its own loop so channel trouble never slows ingestion.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime

from .config import Config
from .correlate import Correlator
from .logging import get_logger
from .normalize import normalize
from .notify import KillSwitch, RateLimiter, enqueue_for_event, send_due_once
from .notify.pipeline import SpecialRenderer
from .notify.ports import Notifier, NotifierUnavailable
from .outbox import process_outbox_once
from .schemas import RenderedMessage
from .store import Store

log = get_logger(__name__)


class NullNotifier:
    """Placeholder when no channel adapter is configured (e.g. no token):
    ledger rows accumulate as pending/failed and drain when one exists."""

    async def send(self, channel: str, message: RenderedMessage) -> None:
        raise NotifierUnavailable("no notifier adapter configured")


def build_processor(store: Store, correlator: Correlator, config: Config, kill: KillSwitch):
    watch = config.routing.watch_completion

    def process(raw: sqlite3.Row) -> None:
        payload = json.loads(raw["body_json"])
        source_row = store.source_by_id(raw["source_id"])
        if source_row is None:
            raise ValueError(f"raw event {raw['id']} references unknown source")
        received_at = datetime.fromisoformat(raw["received_at"])
        events = normalize(source_row["name"], source_row["kind"], payload, watch)
        for event in events:
            event.received_at = received_at
            if correlator.apply(event):
                enqueue_for_event(store, config.routing, kill, event)

    return process


async def outbox_loop(store: Store, processor, config: Config) -> None:
    settings = config.settings
    while True:
        try:
            handled = await asyncio.to_thread(
                process_outbox_once,
                store,
                processor,
                max_attempts=settings.outbox_max_attempts,
                backoff_base_seconds=settings.outbox_backoff_base_seconds,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — the loop must survive anything
            log.error("outbox loop error", error=f"{type(exc).__name__}: {exc}")
            handled = 0
        await asyncio.sleep(0.05 if handled else settings.outbox_poll_interval_seconds)


async def notify_loop(
    store: Store,
    notifier: Notifier,
    limiter: RateLimiter,
    kill: KillSwitch,
    config: Config,
    special_renderers: dict[str, SpecialRenderer],
) -> None:
    settings = config.settings
    while True:
        try:
            sent = await send_due_once(
                store,
                notifier,
                limiter,
                kill,
                max_attempts=settings.notify_max_attempts,
                backoff_base_seconds=settings.notify_backoff_base_seconds,
                special_renderers=special_renderers,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.error("notify loop error", error=f"{type(exc).__name__}: {exc}")
            sent = 0
        await asyncio.sleep(0.05 if sent else settings.notify_poll_interval_seconds)
