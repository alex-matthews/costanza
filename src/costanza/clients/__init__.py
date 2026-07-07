"""Read-only API clients (reconcile + identity_sync).

Hard constraint: these clients speak GET only — no write code path to any
external system exists in this codebase (grep-enforced in tests).
"""

from .arr import ArrClient
from .base import ClientError, ReadOnlyClient
from .seerr import SeerrClient
from .tautulli import TautulliClient

__all__ = ["ArrClient", "ClientError", "ReadOnlyClient", "SeerrClient", "TautulliClient"]


def build_clients(routing, kinds=("seerr", "radarr", "sonarr", "tautulli")) -> dict:
    """Instantiate a client per configured source that has url + api key."""
    clients: dict[str, object] = {}
    for source in routing.sources:
        if not source.enabled or source.kind not in kinds:
            continue
        api_key = source.api_key()
        if not source.url or not api_key:
            continue
        if source.kind == "seerr":
            clients[source.name] = SeerrClient(source.url, api_key)
        elif source.kind in ("radarr", "sonarr"):
            clients[source.name] = ArrClient(source.url, api_key)
        elif source.kind == "tautulli":
            clients[source.name] = TautulliClient(source.url, api_key)
    return clients
