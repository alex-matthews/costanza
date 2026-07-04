"""Weekly digest: aggregate the period since the last digest and enqueue
one ledger row (key `digest:{period_end}` — UNIQUE(event_key, channel)
makes double-fires harmless). The message body is rendered at send time
by the digest special renderer so it reflects the stored cursor."""

from __future__ import annotations

from datetime import datetime, timedelta

from .. import stats
from ..config import RoutingConfig
from ..logging import get_logger
from ..notify.limits import KillSwitch
from ..schemas import RenderedMessage, utcnow
from ..store import Store

log = get_logger(__name__)

CURSOR_JOB = "digest"
DEFAULT_PERIOD = timedelta(days=7)


def build_digest_data(store: Store, since: datetime, until: datetime) -> dict:
    return {
        "period_start": since.date().isoformat(),
        "period_end": until.date().isoformat(),
        "new_arrivals": stats.new_arrivals(store, since, until),
        "requests": stats.requests_summary(store, since, until),
        "watches": stats.watch_summary(store, since, until),
        "ops": stats.ops_summary(store, since, until),
    }


def _period(store: Store, now: datetime) -> tuple[datetime, datetime]:
    cursor = store.get_cursor(CURSOR_JOB) or {}
    last_end = cursor.get("period_end_at")
    since = datetime.fromisoformat(last_end) if last_end else now - DEFAULT_PERIOD
    return since, now


def digest_renderer(store: Store):
    """Special renderer for `digest:` ledger keys (used by the send worker)."""
    from ..notify.render import render_digest

    def render(_key: str) -> RenderedMessage:
        cursor = store.get_cursor(CURSOR_JOB) or {}
        until = datetime.fromisoformat(cursor["period_end_at"]) if cursor else utcnow()
        start = cursor.get("period_start_at")
        since = datetime.fromisoformat(start) if start else until - DEFAULT_PERIOD
        return render_digest(build_digest_data(store, since, until))

    return render


def run_digest(
    store: Store,
    routing: RoutingConfig,
    kill_switch: KillSwitch,
    now: datetime | None = None,
) -> bool:
    """Enqueue this period's digest. Returns True when a row was created."""
    now = now or utcnow()
    channel = routing.digest.channel
    if not channel:
        log.info("digest skipped: no digest channel configured")
        return False
    since, until = _period(store, now)
    cursor = {"period_start_at": since.isoformat(), "period_end_at": until.isoformat()}
    if kill_switch.engaged():
        # Advance the window silently: disengaging the switch later must not
        # dump weeks of backlog into the channel.
        store.set_cursor(CURSOR_JOB, cursor, now)
        log.info("digest suppressed by kill switch", period_end=until.isoformat())
        return False
    created = store.enqueue_notification(
        f"digest:{until.date().isoformat()}", channel, "digest", now
    )
    if created:
        # Only a real enqueue advances the cursor; a deduped double-fire
        # leaves the previous period intact for the send-time renderer.
        store.set_cursor(CURSOR_JOB, cursor, now)
        log.info("digest enqueued", period_start=since.isoformat(), period_end=until.isoformat())
    return created
