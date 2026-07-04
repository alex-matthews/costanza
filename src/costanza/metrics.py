"""Low-cardinality Prometheus metrics (label values are config-bounded).

`costanza_webhook_auth_failures` and `costanza_outbox_backlog` are the two
metrics home-ops alerts on (handoff.md). Counters gain the `_total` suffix
in exposition per the Prometheus client convention.
"""

from __future__ import annotations

from collections.abc import Callable

from prometheus_client import Counter, Gauge

WEBHOOKS_RECEIVED = Counter(
    "costanza_webhooks_received",
    "Webhooks accepted (archived + 202) per source",
    ["source"],
)
WEBHOOK_AUTH_FAILURES = Counter(
    "costanza_webhook_auth_failures",
    "Webhook requests rejected by source auth",
    ["source"],
)
WEBHOOK_REJECTED = Counter(
    "costanza_webhooks_rejected",
    "Webhook requests rejected before archive (unknown source, oversize)",
    ["reason"],
)
OUTBOX_BACKLOG = Gauge(
    "costanza_outbox_backlog",
    "Ingest outbox rows waiting to be processed",
)
OUTBOX_DEAD = Gauge(
    "costanza_outbox_dead",
    "Ingest outbox rows dead-lettered (admin diagnostics)",
)
EVENTS_STORED = Counter(
    "costanza_events_stored",
    "Canonical events persisted, by type and origin",
    ["type", "origin"],
)
EVENTS_DEDUPED = Counter(
    "costanza_events_deduped",
    "Events dropped because their source_event_key already existed",
    ["source"],
)
NOTIFICATIONS = Counter(
    "costanza_notifications",
    "Notification ledger transitions",
    ["outcome"],  # enqueued | sent | retried | dead | suppressed_kill_switch | rate_limited
)
NOTIFY_PENDING = Gauge(
    "costanza_notifications_pending",
    "Notification rows pending or retrying",
)


def bind_backlog_gauges(
    outbox_backlog: Callable[[], int],
    outbox_dead: Callable[[], int],
    notify_pending: Callable[[], int],
) -> None:
    """Compute queue gauges at scrape time from the store."""
    OUTBOX_BACKLOG.set_function(outbox_backlog)
    OUTBOX_DEAD.set_function(outbox_dead)
    NOTIFY_PENDING.set_function(notify_pending)
