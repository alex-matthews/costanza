"""Rate limits + kill switch: the Tier-1 write-safety gates (ADR-0006).

Notification storms are a write-safety failure, not a cosmetic one: the
limiter defers (never drops) over-budget sends, and the kill switch — env
override OR persisted toggle — silences all outbound while leaving the
event store fully live.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta

from ..schemas import utcnow
from ..store import Store


class KillSwitch:
    def __init__(self, store: Store, env_override: bool):
        self._store = store
        self._env_override = env_override

    def engaged(self) -> bool:
        if self._env_override:
            return True
        return bool(self._store.kill_switch_state()["engaged"])

    def state(self) -> dict:
        stored = self._store.kill_switch_state()
        return {**stored, "env_override": self._env_override,
                "engaged": self._env_override or stored["engaged"]}

    def set(self, engaged: bool, set_by: str, via: str = "api") -> dict:
        self._store.set_kill_switch(engaged, set_by, via)
        return self.state()


class RateLimiter:
    """Sliding-window per-channel limiter (in-process; single replica)."""

    def __init__(self, per_channel_per_minute: int):
        self._limit = max(1, per_channel_per_minute)
        self._window = timedelta(minutes=1)
        self._sent: dict[str, deque[datetime]] = {}

    def allow(self, channel: str, now: datetime | None = None) -> bool:
        now = now or utcnow()
        sent = self._sent.setdefault(channel, deque())
        while sent and now - sent[0] > self._window:
            sent.popleft()
        if len(sent) >= self._limit:
            return False
        sent.append(now)
        return True
