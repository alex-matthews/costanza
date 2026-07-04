"""Correlation: media identity, user identity, request chains, persistence.

`Correlator.apply` is the single write path for canonical events: resolve
media -> resolve user -> insert (idempotent on source_event_key) -> update
the request-chain timeline spine. Returns True only when the event was new,
which is what gates notification fan-out (dedupe = exactly-once notify).
"""

from __future__ import annotations

from datetime import datetime

from .. import metrics
from ..logging import get_logger
from ..schemas import CanonicalEvent, utcnow
from ..store import Store
from .identity import resolve_user

log = get_logger(__name__)

# request.* event type -> chain state
_CHAIN_STATES = {
    "request.created": "requested",
    "request.approved": "approved",
    "request.declined": "declined",
    "request.available": "available",
}
_CLOSING_STATES = ("declined", "available")


class Correlator:
    def __init__(self, store: Store):
        self._store = store

    def apply(self, event: CanonicalEvent) -> bool:
        """Correlate and persist one canonical event. True if newly inserted."""
        store = self._store
        source_row = store.source_by_name(event.source)
        if source_row is None:
            raise ValueError(f"event from unregistered source {event.source!r}")

        if event.media is not None and event.media.media_id is None:
            if any((event.media.tmdb_id, event.media.tvdb_id, event.media.imdb_id, event.media.title)):
                event.media.media_id = store.find_or_create_media(event.media)

        event = resolve_user(store, event)

        if event.received_at is None:
            event.received_at = utcnow()
        inserted = store.insert_event(event, source_row["id"])
        if not inserted:
            metrics.EVENTS_DEDUPED.labels(source=event.source).inc()
            return False
        metrics.EVENTS_STORED.labels(type=event.type, origin=event.origin).inc()

        if event.type in _CHAIN_STATES:
            self._advance_chain(event)
        return True

    # -- request chains -------------------------------------------------------

    def _advance_chain(self, event: CanonicalEvent) -> None:
        store = self._store
        state = _CHAIN_STATES[event.type]
        if event.type == "request.available" and event.attrs.get("partial"):
            state = "partially_available"
        occurred: datetime = event.occurred_at or event.received_at or utcnow()
        request_id = event.attrs.get("request_id")
        media_id = event.media.media_id if event.media else None
        user_id = event.user.user_id if event.user else None

        chain = store.chain_by_request_id(request_id) if request_id else None
        if chain is None and media_id:
            chain = store.open_chain_for_media(media_id)

        closes = state in _CLOSING_STATES
        if chain is None:
            # Out-of-order or reconcile-synthesized: open the chain at
            # whatever lifecycle stage we first observed.
            store.create_chain(
                media_id=media_id,
                seerr_request_id=request_id,
                requested_by=user_id,
                state=state,
                opened_at=occurred,
                closed_at=occurred if closes else None,
            )
            return

        if chain["closed_at"] is not None:
            log.info(
                "event for closed chain ignored",
                chain_id=chain["id"],
                event_key=event.source_event_key,
            )
            return
        store.update_chain(
            chain["id"],
            state=state,
            closed_at=occurred if closes else None,
            media_id=media_id if chain["media_id"] is None else None,
            requested_by=user_id if chain["requested_by"] is None else None,
        )
