"""Config-registered webhook sources (v1: seerr, radarr, sonarr, tautulli).

Registration is pure config: a routing.yaml entry plus a
WEBHOOK_SECRET__{NAME} env var. Adding a second Arr instance later
(e.g. radarr-se, OQ-1) requires no code change.
"""

from __future__ import annotations

import hmac

from ..config import RoutingConfig, SourceConfig


class SourceRegistry:
    def __init__(self, routing: RoutingConfig):
        self._sources = {s.name: s for s in routing.sources}

    def get(self, name: str) -> SourceConfig | None:
        source = self._sources.get(name)
        if source is None or not source.enabled:
            return None
        return source

    def names(self) -> list[str]:
        return sorted(self._sources)

    @staticmethod
    def authenticate(source: SourceConfig, presented: str | None) -> bool:
        """Constant-time shared-secret check.

        A source with no configured secret rejects everything (fail-safe:
        an unset ExternalSecret must not open an unauthenticated ingest path).
        """
        secret = source.secret()
        if not secret or not presented:
            return False
        return hmac.compare_digest(secret, presented)
