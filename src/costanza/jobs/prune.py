"""Daily prune: raw webhook payloads age out (default 30 days, OQ-7);
canonical events are kept indefinitely (tiny)."""

from __future__ import annotations

from datetime import datetime

from ..logging import get_logger
from ..store import Store

log = get_logger(__name__)


def run_prune(
    store: Store, retention_days: int, now: datetime | None = None
) -> tuple[int, int, int]:
    pruned, outbox_done, redacted = store.prune(retention_days, now)
    log.info("raw archive pruned", raw_rows=pruned, outbox_rows=outbox_done,
             redacted_rows=redacted, retention_days=retention_days)
    return pruned, outbox_done, redacted
