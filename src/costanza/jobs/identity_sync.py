"""Daily identity_sync: pull Seerr/Tautulli user lists and record any
external identity the routing.yaml map doesn't cover (user_id NULL rows).
Flag-only — Costanza never invents household members; the admin digest
surfaces the unmapped list for a config fix (OQ-8)."""

from __future__ import annotations

from ..logging import get_logger
from ..store import Store

log = get_logger(__name__)


def run_identity_sync(store: Store, clients: dict[str, object], kinds: dict[str, str]) -> int:
    """Observe unmapped identities. Returns how many new ones were recorded."""
    observed = 0
    for name, client in clients.items():
        kind = kinds.get(name)
        try:
            if kind == "seerr":
                for user in client.get_users():
                    username = user.get("username") or user.get("plexUsername")
                    if username and store.resolve_identity("seerr", str(username)) is None:
                        observed += int(store.observe_identity("seerr", str(username)))
            elif kind == "tautulli":
                for user in client.get_users():
                    user_id = user.get("user_id")
                    if user_id is not None and (
                        store.resolve_identity("tautulli", str(user_id)) is None
                    ):
                        observed += int(store.observe_identity("tautulli", str(user_id)))
        except Exception as exc:  # noqa: BLE001 — one broken source must not stop the rest
            log.error("identity_sync failed", source=name, error=str(exc))
    if observed:
        log.info("identity_sync observed unmapped identities", count=observed)
    return observed
