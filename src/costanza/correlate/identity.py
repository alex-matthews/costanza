"""Household identity map: normalizer user hints -> mapped members.

The map itself is config (routing.yaml `users:`, OQ-8) synced into the
users/identities tables at startup. Unmapped-but-observed identities are
recorded with user_id NULL so identity_sync and the admin digest can
surface them; the event keeps the raw hint in attrs and user_id stays
NULL — Costanza never guesses who someone is.
"""

from __future__ import annotations

from ..schemas import CanonicalEvent
from ..store import Store


def resolve_user(store: Store, event: CanonicalEvent) -> CanonicalEvent:
    user = event.user
    if user is None or user.provider is None or user.external_id is None:
        return event
    hit = store.resolve_identity(user.provider, user.external_id)
    if hit is not None:
        user.user_id = hit["id"]
        user.display = hit["display_name"]
        return event
    store.observe_identity(user.provider, user.external_id)
    event.attrs.setdefault(
        "unmapped_user",
        {"provider": user.provider, "external_id": user.external_id, "display": user.display},
    )
    user.user_id = None
    return event
