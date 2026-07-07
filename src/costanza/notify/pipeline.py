"""Notification pipeline: router -> render -> limits -> ledger/outbox -> port.

Enqueue happens when an event is first stored (dedupe is the UNIQUE
(event_key, channel) constraint); sending happens in a separate worker
pass so a dead channel adapter can never block or crash ingestion.

Kill-switch semantics: engaged at enqueue time = the row is never created
(suppressed + counted) — flipping the switch off later must not flood the
channel with backlog. Engaged at send time = rows are deferred without
burning attempts, so a brief flip never dead-letters anything.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timedelta

from .. import metrics
from ..config import RoutingConfig
from ..logging import get_logger
from ..outbox import backoff
from ..schemas import CanonicalEvent, MediaRef, RenderedMessage, UserRef, utcnow
from ..store import Store
from .limits import KillSwitch, RateLimiter
from .ports import Notifier
from .render import render_event, rendered_hash
from .router import channels_for

log = get_logger(__name__)

_DEFER = timedelta(seconds=60)

SpecialRenderer = Callable[[str], RenderedMessage]


def enqueue_for_event(
    store: Store,
    routing: RoutingConfig,
    kill_switch: KillSwitch,
    event: CanonicalEvent,
    now: datetime | None = None,
) -> int:
    """Fan an event out to ledger rows per routed channel. Returns rows created."""
    channels = channels_for(event, routing)
    if not channels:
        return 0
    if kill_switch.engaged():
        metrics.NOTIFICATIONS.labels(outcome="suppressed_kill_switch").inc(len(channels))
        log.info(
            "notification suppressed by kill switch",
            event_key=event.source_event_key,
            channels=channels,
        )
        return 0
    created = 0
    message_hash = rendered_hash(render_event(event))
    for channel in channels:
        if store.enqueue_notification(event.source_event_key, channel, message_hash, now):
            metrics.NOTIFICATIONS.labels(outcome="enqueued").inc()
            created += 1
    return created


def event_from_row(store: Store, row) -> CanonicalEvent:
    """Rebuild a renderable CanonicalEvent from a stored event row."""
    media = None
    if row["media_id"]:
        m = store.get_media(row["media_id"])
        if m is not None:
            media = MediaRef(
                media_id=m["id"],
                tmdb_id=m["tmdb_id"],
                tvdb_id=m["tvdb_id"],
                imdb_id=m["imdb_id"],
                title=m["title"],
                year=m["year"],
                kind=m["kind"],
            )
    user = None
    if row["user_id"]:
        u = store.get_user(row["user_id"])
        if u is not None:
            user = UserRef(user_id=u["id"], display=u["display_name"])
    return CanonicalEvent(
        id=row["id"],
        source=store.query("SELECT name FROM sources WHERE id = ?", (row["source_id"],))[0][
            "name"
        ],
        source_event_key=row["source_event_key"],
        origin=row["origin"],
        type=row["type"],
        occurred_at=datetime.fromisoformat(row["occurred_at"]),
        received_at=datetime.fromisoformat(row["received_at"]),
        media=media,
        user=user,
        attrs=json.loads(row["attrs_json"]),
    )


async def send_due_once(
    store: Store,
    notifier: Notifier,
    limiter: RateLimiter,
    kill_switch: KillSwitch,
    *,
    max_attempts: int = 8,
    backoff_base_seconds: float = 5.0,
    special_renderers: dict[str, SpecialRenderer] | None = None,
    limit: int = 20,
    now: datetime | None = None,
) -> int:
    """Drain due ledger rows once; returns messages successfully sent."""
    now = now or utcnow()
    rows = store.claim_notifications_due(limit=limit, now=now)
    if not rows:
        return 0

    if kill_switch.engaged():
        for row in rows:
            store.notification_defer(row["id"], now + _DEFER)
        metrics.NOTIFICATIONS.labels(outcome="suppressed_kill_switch").inc(len(rows))
        return 0

    sent = 0
    for row in rows:
        message = _render_row(store, row, special_renderers or {})
        if message is None:
            store.notification_dead(row["id"], "event_missing")
            metrics.NOTIFICATIONS.labels(outcome="dead").inc()
            continue
        if not limiter.allow(row["channel"], now):
            store.notification_defer(row["id"], now + _DEFER)
            metrics.NOTIFICATIONS.labels(outcome="rate_limited").inc()
            continue
        try:
            await notifier.send(row["channel"], message)
        except Exception as exc:  # noqa: BLE001 — adapter failure must never propagate
            error = f"{type(exc).__name__}: {exc}"
            if row["attempts"] + 1 >= max_attempts:
                store.notification_dead(row["id"], error)
                metrics.NOTIFICATIONS.labels(outcome="dead").inc()
                log.error(
                    "notification dead-lettered",
                    event_key=row["event_key"],
                    channel=row["channel"],
                    error=error,
                )
            else:
                store.notification_retry(
                    row["id"], error, now + backoff(backoff_base_seconds, row["attempts"])
                )
                metrics.NOTIFICATIONS.labels(outcome="retried").inc()
        else:
            store.notification_sent(row["id"], now)
            metrics.NOTIFICATIONS.labels(outcome="sent").inc()
            sent += 1
    return sent


def _render_row(
    store: Store, row, special_renderers: dict[str, SpecialRenderer]
) -> RenderedMessage | None:
    key: str = row["event_key"]
    prefix = key.split(":", 1)[0]
    if prefix in special_renderers:
        return special_renderers[prefix](key)
    event_row = store.get_event_by_key(key)
    if event_row is None:
        return None
    return render_event(event_from_row(store, event_row))
