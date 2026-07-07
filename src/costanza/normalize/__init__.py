"""Per-source payload -> CanonicalEvent normalizers (pure, fixture-tested).

Dispatch is by source *kind*, keyed off the configured source *name* so a
second instance of the same kind (e.g. radarr-se, OQ-1) gets distinct
source_event_keys with zero code change. Unrecognized payloads become
`source.unknown` events — kept, never dropped.
"""

from __future__ import annotations

from collections.abc import Callable

from ..config import WatchCompletionConfig
from ..schemas import CanonicalEvent
from .radarr import normalize_radarr
from .seerr import normalize_seerr
from .sonarr import normalize_sonarr
from .tautulli import normalize_tautulli

Normalizer = Callable[[str, dict, WatchCompletionConfig], list[CanonicalEvent]]

NORMALIZERS: dict[str, Normalizer] = {
    "seerr": normalize_seerr,
    "radarr": normalize_radarr,
    "sonarr": normalize_sonarr,
    "tautulli": normalize_tautulli,
}


def normalize(
    source_name: str,
    kind: str,
    payload: dict,
    watch: WatchCompletionConfig | None = None,
) -> list[CanonicalEvent]:
    normalizer = NORMALIZERS.get(kind)
    if normalizer is None:
        raise ValueError(f"no normalizer for source kind {kind!r}")
    return normalizer(source_name, payload, watch or WatchCompletionConfig())


__all__ = ["NORMALIZERS", "normalize"]
