"""Canonical event contract (handoff.md) — pydantic v2 models used everywhere.

`reconcile.gap` extends the handoff enum per the build prompt: the hourly
reconcile stores gap *markers* for transient event kinds it cannot
reconstruct (see the guarantees matrix in architecture.md).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .ids import new_id

EventType = Literal[
    "request.created",
    "request.approved",
    "request.declined",
    "request.available",
    "media.grabbed",
    "media.imported",
    "media.upgraded",
    "media.deleted",
    "playback.started",
    "playback.stopped",
    "watch.completed",
    "health.issue",
    "source.unknown",
    "reconcile.gap",
]

EVENT_TYPES: tuple[str, ...] = EventType.__args__  # type: ignore[attr-defined]

Origin = Literal["webhook", "reconcile", "manual"]
MediaKind = Literal["movie", "series", "season", "episode"]
IdentityProvider = Literal["seerr", "plex", "tautulli", "discord"]


class MediaRef(BaseModel):
    """Media identity as seen by a normalizer; correlate resolves media_id."""

    model_config = ConfigDict(extra="forbid")

    media_id: str | None = None
    tmdb_id: int | None = None
    tvdb_id: int | None = None
    imdb_id: str | None = None
    title: str | None = None
    year: int | None = None
    kind: MediaKind | None = None
    detail: dict = Field(default_factory=dict)  # e.g. {"season": 2, "episode": 5}


class UserRef(BaseModel):
    """User hint from a normalizer; correlate maps it to a household member.

    provider/external_id are the raw identity observed in the payload;
    user_id/display are filled only when the identity map resolves them.
    """

    model_config = ConfigDict(extra="forbid")

    user_id: str | None = None
    display: str | None = None
    provider: IdentityProvider | None = None
    external_id: str | None = None


class CanonicalEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_id)
    source: str  # configured instance name, e.g. "radarr"
    source_event_key: str  # deterministic idempotency key
    origin: Origin = "webhook"
    type: EventType
    occurred_at: datetime | None = None  # None -> persisted as received_at
    received_at: datetime | None = None
    media: MediaRef | None = None
    user: UserRef | None = None
    attrs: dict = Field(default_factory=dict)


class RenderedMessage(BaseModel):
    """Channel-agnostic message produced by the pure renderers."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["embed", "digest"] = "embed"
    title: str
    description: str = ""
    fields: list[tuple[str, str]] = Field(default_factory=list)
    color: int | None = None
    footer: str | None = None


def utcnow() -> datetime:
    return datetime.now(UTC)
