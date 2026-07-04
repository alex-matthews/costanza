"""Helpers shared by the per-source normalizers."""

from __future__ import annotations

import re

from ..ids import sha16
from ..schemas import CanonicalEvent

_TITLE_YEAR = re.compile(r"^(?P<title>.+?)\s*\((?P<year>\d{4})\)$")


def to_int(value: object) -> int | None:
    """Best-effort int coercion; webhook payloads stringify ids freely."""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def split_title_year(subject: str | None) -> tuple[str | None, int | None]:
    """'Arrival (2016)' -> ('Arrival', 2016); no trailing year -> (subject, None)."""
    if not subject:
        return None, None
    match = _TITLE_YEAR.match(subject.strip())
    if match:
        return match.group("title"), int(match.group("year"))
    return subject.strip(), None


def unknown_event(
    source: str, payload: dict, discriminator: str | None, **attrs: object
) -> CanonicalEvent:
    """`source.unknown`: recognized source, unrecognized payload. Keep it."""
    label = discriminator or "none"
    return CanonicalEvent(
        source=source,
        source_event_key=f"{source}:unknown:{label}:{sha16(payload)}",
        type="source.unknown",
        attrs={"payload_kind": label, **attrs},
    )
