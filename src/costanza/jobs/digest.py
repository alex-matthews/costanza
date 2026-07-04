"""Weekly digest: aggregate the period since the last digest and enqueue
one ledger row. The period bounds are encoded in the ledger key
(`digest:{start}|{end}`), so a row is rendered at send time against ITS
OWN window — if the channel is down across two digest runs, each pending
row still renders its own week instead of both showing the newest one.
UNIQUE(event_key, channel) keeps double-fires harmless."""

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
MIN_PERIOD = timedelta(hours=1)  # guard against scheduler double-fires


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


def digest_key(since: datetime, until: datetime) -> str:
    # '|' keeps the isoformat colons out of the prefix-routing split.
    return f"digest:{since.isoformat()}|{until.isoformat()}"


def parse_digest_key(key: str) -> tuple[datetime, datetime] | None:
    body = key.removeprefix("digest:")
    if "|" not in body:
        return None
    start_raw, _, end_raw = body.partition("|")
    try:
        return datetime.fromisoformat(start_raw), datetime.fromisoformat(end_raw)
    except ValueError:
        return None


def digest_renderer(store: Store):
    """Special renderer for `digest:` ledger keys (used by the send worker)."""
    from ..notify.render import render_digest

    def render(key: str) -> RenderedMessage:
        period = parse_digest_key(key)
        if period is None:
            # Legacy/unparseable key: fall back to the cursor window.
            cursor = store.get_cursor(CURSOR_JOB) or {}
            until = (
                datetime.fromisoformat(cursor["period_end_at"])
                if cursor.get("period_end_at")
                else utcnow()
            )
            start = cursor.get("period_start_at")
            since = datetime.fromisoformat(start) if start else until - DEFAULT_PERIOD
        else:
            since, until = period
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
    if until - since < MIN_PERIOD:
        log.info("digest skipped: period too short", since=since.isoformat())
        return False
    cursor = {"period_start_at": since.isoformat(), "period_end_at": until.isoformat()}
    if kill_switch.engaged():
        # Advance the window silently: disengaging the switch later must not
        # dump weeks of backlog into the channel.
        store.set_cursor(CURSOR_JOB, cursor, now)
        log.info("digest suppressed by kill switch", period_end=until.isoformat())
        return False
    created = store.enqueue_notification(digest_key(since, until), channel, "digest", now)
    if created:
        # Only a real enqueue advances the cursor; a deduped double-fire
        # leaves the previous period intact.
        store.set_cursor(CURSOR_JOB, cursor, now)
        log.info("digest enqueued", period_start=since.isoformat(), period_end=until.isoformat())
    return created
