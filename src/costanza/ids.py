"""Identifier and hashing helpers."""

from __future__ import annotations

import hashlib
import json
import uuid


def new_id() -> str:
    """Time-ordered UUIDv7 (stdlib in Python 3.14)."""
    return str(uuid.uuid7())


def sha16(data: object) -> str:
    """Short deterministic hash of arbitrary JSON-able data.

    Used as the fallback discriminator inside source_event_keys when the
    payload carries no native id: it depends only on payload content, so a
    relayed/tee'd duplicate or a source retry produces the same key.
    """
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]
