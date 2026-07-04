"""Ledger/limits property tests: dedupe, storms, dead channels, kill switch."""

from datetime import timedelta

import pytest

from costanza.correlate import Correlator
from costanza.normalize import normalize
from costanza.notify import (
    KillSwitch,
    NotifierUnavailable,
    RateLimiter,
    enqueue_for_event,
    send_due_once,
)
from costanza.notify.render import render_digest
from costanza.notify.router import channels_for
from costanza.schemas import CanonicalEvent, MediaRef, RenderedMessage, UserRef


class FakeNotifier:
    def __init__(self):
        self.sent: list[tuple[str, RenderedMessage]] = []
        self.down = False

    async def send(self, channel: str, message: RenderedMessage) -> None:
        if self.down:
            raise NotifierUnavailable("discord is down")
        self.sent.append((channel, message))


@pytest.fixture
def env(store, routing, now):
    store.sync_sources(routing.sources)
    store.sync_users(routing.users)
    return {
        "store": store,
        "routing": routing,
        "kill": KillSwitch(store, env_override=False),
        "notifier": FakeNotifier(),
        "limiter": RateLimiter(routing.rate_limits.per_channel_per_minute),
        "correlator": Correlator(store),
    }


def _event(n: int = 1, type_: str = "request.available") -> CanonicalEvent:
    return CanonicalEvent(
        source="seerr",
        source_event_key=f"seerr:{type_}:{n}",
        type=type_,
        media=MediaRef(title=f"Movie {n}", year=2026, kind="movie"),
        user=UserRef(user_id="u:alice", display="Alice"),
        attrs={},
    )


def _enqueue(env, event, now):
    """Persist-then-enqueue, mirroring the real worker pipeline."""
    env["correlator"].apply(event)
    return enqueue_for_event(env["store"], env["routing"], env["kill"], event, now)


def test_router_allowlist(routing):
    assert channels_for(_event(type_="request.available"), routing) == ["media-feed"]
    assert channels_for(_event(type_="health.issue"), routing) == ["media-admin"]
    # Not on the allowlist: stored but silent.
    assert channels_for(_event(type_="playback.started"), routing) == []
    assert channels_for(_event(type_="source.unknown"), routing) == []


def test_router_source_filter(routing):
    routing.rules[0].sources = ["radarr"]
    assert channels_for(_event(type_="request.available"), routing) == []


async def test_same_event_twice_one_send(env, now):
    env["store"].set_kill_switch(False, "test", "test", now)
    event = _event(1)
    assert _enqueue(env, event, now) == 1
    assert _enqueue(env, event, now) == 0  # UNIQUE(event_key, channel)
    sent = await send_due_once(
        env["store"], env["notifier"], env["limiter"], env["kill"], now=now
    )
    assert sent == 1
    # Re-delivery after send: still no second row, nothing to drain.
    assert _enqueue(env, event, now) == 0
    sent = await send_due_once(
        env["store"], env["notifier"], env["limiter"], env["kill"], now=now
    )
    assert sent == 0
    assert len(env["notifier"].sent) == 1


async def test_storm_is_rate_limited_then_drains(env, now):
    env["store"].set_kill_switch(False, "test", "test", now)
    for n in range(25):
        _enqueue(env, _event(n), now)
    sent = await send_due_once(
        env["store"], env["notifier"], env["limiter"], env["kill"], limit=100, now=now
    )
    assert sent == 10  # per_channel_per_minute
    counts = env["store"].notification_counts()
    assert counts["sent"] == 10
    assert counts["pending"] == 15  # deferred, not dropped, no attempts burned
    pending = env["store"].claim_notifications_due(limit=100, now=now + timedelta(seconds=61))
    assert all(r["attempts"] == 0 for r in pending)
    # Next minute: another 10 drain.
    sent = await send_due_once(
        env["store"], env["notifier"], env["limiter"], env["kill"],
        limit=100, now=now + timedelta(seconds=61),
    )
    assert sent == 10


async def test_discord_down_accumulates_then_drains(env, now):
    env["store"].set_kill_switch(False, "test", "test", now)
    env["notifier"].down = True
    for n in range(5):
        _enqueue(env, _event(n), now)
    sent = await send_due_once(
        env["store"], env["notifier"], env["limiter"], env["kill"], now=now
    )
    assert sent == 0
    counts = env["store"].notification_counts()
    assert counts.get("failed") == 5
    # Recovery: rows drain once their backoff elapses.
    env["notifier"].down = False
    later = now + timedelta(minutes=5)
    sent = await send_due_once(
        env["store"], env["notifier"], env["limiter"], env["kill"], now=later
    )
    assert sent == 5
    assert env["store"].notification_counts() == {"sent": 5}


async def test_dead_after_max_attempts(env, now):
    env["store"].set_kill_switch(False, "test", "test", now)
    env["notifier"].down = True
    _enqueue(env, _event(1), now)
    t = now
    for _ in range(3):
        await send_due_once(
            env["store"], env["notifier"], env["limiter"], env["kill"],
            max_attempts=3, now=t,
        )
        t += timedelta(minutes=10)
    counts = env["store"].notification_counts()
    assert counts == {"dead": 1}
    row = env["store"].dead_notifications()[0]
    assert "discord is down" in row["last_error"]


async def test_kill_switch_at_enqueue_suppresses(env, now):
    env["store"].set_kill_switch(True, "admin", "api", now)
    assert _enqueue(env, _event(1), now) == 0
    assert env["store"].notification_counts() == {}


async def test_kill_switch_at_send_defers_without_attempts(env, now):
    env["store"].set_kill_switch(False, "test", "test", now)
    _enqueue(env, _event(1), now)
    env["store"].set_kill_switch(True, "admin", "api", now)
    sent = await send_due_once(
        env["store"], env["notifier"], env["limiter"], env["kill"], now=now
    )
    assert sent == 0
    counts = env["store"].notification_counts()
    assert counts == {"pending": 1}
    # Switch back off: message goes out; no attempts were burned meanwhile.
    env["store"].set_kill_switch(False, "admin", "api", now)
    sent = await send_due_once(
        env["store"], env["notifier"], env["limiter"], env["kill"],
        now=now + timedelta(seconds=61),
    )
    assert sent == 1
    assert env["notifier"].sent[0][0] == "media-feed"


async def test_env_override_wins_over_stored_toggle(env, now):
    env["store"].set_kill_switch(False, "admin", "api", now)
    kill = KillSwitch(env["store"], env_override=True)
    assert kill.engaged() is True
    assert enqueue_for_event(env["store"], env["routing"], kill, _event(1), now) == 0


async def test_end_to_end_event_row_rendering(env, now):
    """Events stored via the correlator render from DB rows at send time."""
    env["store"].set_kill_switch(False, "test", "test", now)
    payload_events = normalize("seerr", "seerr", {
        "notification_type": "MEDIA_AVAILABLE",
        "subject": "Arrival (2016)",
        "media": {"media_type": "movie", "tmdbId": "329865", "status": "AVAILABLE"},
        "request": {"request_id": "RQ-1", "requestedBy_username": "alice"},
    })
    for event in payload_events:
        assert env["correlator"].apply(event) is True
        _enqueue(env, event, now)
    sent = await send_due_once(
        env["store"], env["notifier"], env["limiter"], env["kill"], now=now
    )
    assert sent == 1
    channel, message = env["notifier"].sent[0]
    assert channel == "media-feed"
    assert message.title == "Now available: Arrival (2016)"
    assert message.description == "Requested by Alice"  # mapped display name


async def test_special_renderer_for_digest_keys(env, now):
    env["store"].set_kill_switch(False, "test", "test", now)
    env["store"].enqueue_notification("digest:2026-W27", "media-digest", "h", now)
    rendered = render_digest({"period_start": "2026-06-28", "period_end": "2026-07-05"})
    sent = await send_due_once(
        env["store"], env["notifier"], env["limiter"], env["kill"],
        special_renderers={"digest": lambda key: rendered}, now=now,
    )
    assert sent == 1
    assert env["notifier"].sent[0][0] == "media-digest"
    assert env["notifier"].sent[0][1].kind == "digest"


async def test_missing_event_row_dead_letters(env, now):
    env["store"].set_kill_switch(False, "test", "test", now)
    env["store"].enqueue_notification("seerr:ghost:1", "media-feed", "h", now)
    sent = await send_due_once(
        env["store"], env["notifier"], env["limiter"], env["kill"], now=now
    )
    assert sent == 0
    assert env["store"].notification_counts() == {"dead": 1}
