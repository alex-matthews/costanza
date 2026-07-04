"""SQLite-backed ingest work queue: raw webhook rows -> off-path processing.

The webhook handler only archives + enqueues; this worker owns parsing,
normalization, correlation and notification fan-out via an injected
`process` callable, so a bad payload can never drop a webhook — it retries
with backoff and dead-letters into admin diagnostics.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import datetime, timedelta

from .logging import get_logger
from .schemas import utcnow
from .store import Store

log = get_logger(__name__)

Processor = Callable[[sqlite3.Row], None]


def backoff(base_seconds: float, attempts: int, cap_seconds: float = 3600.0) -> timedelta:
    return timedelta(seconds=min(base_seconds * (2**attempts), cap_seconds))


def process_outbox_once(
    store: Store,
    process: Processor,
    *,
    max_attempts: int = 5,
    backoff_base_seconds: float = 2.0,
    limit: int = 20,
    now: datetime | None = None,
) -> int:
    """Drain due outbox rows once; returns the number of rows handled."""
    now = now or utcnow()
    rows = store.claim_outbox_due(limit=limit, now=now)
    for row in rows:
        raw = store.get_raw(row["raw_event_id"])
        if raw is None:  # pruned from under us; nothing to do
            store.outbox_dead(row["id"], "raw_event_missing")
            continue
        try:
            process(raw)
        except Exception as exc:  # noqa: BLE001 — worker must survive any payload
            error = f"{type(exc).__name__}: {exc}"
            if row["attempts"] + 1 >= max_attempts:
                store.outbox_dead(row["id"], error)
                log.error(
                    "outbox item dead-lettered",
                    outbox_id=row["id"],
                    raw_event_id=row["raw_event_id"],
                    error=error,
                )
            else:
                store.outbox_retry(
                    row["id"], error, now + backoff(backoff_base_seconds, row["attempts"])
                )
                log.warning(
                    "outbox item retry scheduled",
                    outbox_id=row["id"],
                    attempts=row["attempts"] + 1,
                    error=error,
                )
        else:
            store.outbox_done(row["id"])
    return len(rows)
