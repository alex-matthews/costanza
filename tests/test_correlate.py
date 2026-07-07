"""Correlation scenario tests: fixture sequences -> expected chain/timeline state."""

import json

import pytest

from conftest import load_fixture

from costanza.correlate import Correlator
from costanza.normalize import normalize


@pytest.fixture
def correlator(store, routing):
    store.sync_sources(routing.sources)
    store.sync_users(routing.users)
    return Correlator(store)


def apply_fixture(correlator, source, *parts, mutate=None):
    payload = load_fixture(source, *parts)
    if mutate:
        payload = json.loads(json.dumps(payload))
        mutate(payload)
    results = []
    for event in normalize(source, source, payload):
        results.append((correlator.apply(event), event))
    return results


def test_movie_request_lifecycle_closes_chain(correlator, store):
    apply_fixture(correlator, "seerr", "request-created.json")
    chain = store.chain_by_request_id("RQ-1001")
    assert chain["state"] == "requested"
    assert chain["closed_at"] is None
    assert chain["requested_by"] == "u:alice"

    apply_fixture(correlator, "seerr", "request-approved.json")
    chain = store.chain_by_request_id("RQ-1001")
    assert chain["state"] == "approved"
    assert chain["closed_at"] is None

    apply_fixture(correlator, "seerr", "request-available.json")
    chain = store.chain_by_request_id("RQ-1001")
    assert chain["state"] == "available"
    assert chain["closed_at"] is not None

    # Timeline: all three events attached to the same media row.
    events = store.events_for_media(chain["media_id"])
    assert [e["type"] for e in events] == [
        "request.created",
        "request.approved",
        "request.available",
    ]


def test_partial_available_keeps_chain_open(correlator, store):
    apply_fixture(correlator, "seerr", "request-created.json")
    apply_fixture(correlator, "seerr", "request-partially-available.json")
    chain = store.chain_by_request_id("RQ-1001")
    assert chain["state"] == "partially_available"
    assert chain["closed_at"] is None
    apply_fixture(correlator, "seerr", "request-available.json")
    chain = store.chain_by_request_id("RQ-1001")
    assert chain["state"] == "available"
    assert chain["closed_at"] is not None


def test_declined_closes_chain(correlator, store):
    apply_fixture(correlator, "seerr", "request-created.json")
    apply_fixture(correlator, "seerr", "request-declined.json")
    chain = store.chain_by_request_id("RQ-1001")
    assert chain["state"] == "declined"
    assert chain["closed_at"] is not None


def test_events_after_close_do_not_reopen(correlator, store):
    apply_fixture(correlator, "seerr", "request-created.json")
    apply_fixture(correlator, "seerr", "request-declined.json")
    # A later (weird) approval for the same request must not reopen it.
    apply_fixture(correlator, "seerr", "request-approved.json")
    chain = store.chain_by_request_id("RQ-1001")
    assert chain["state"] == "declined"


def test_out_of_order_first_event_opens_chain_at_that_stage(correlator, store):
    apply_fixture(correlator, "seerr", "request-available.json")
    chain = store.chain_by_request_id("RQ-1001")
    assert chain["state"] == "available"
    assert chain["closed_at"] is not None


def test_media_identity_unifies_across_sources(correlator, store):
    # Arrival via Seerr (tmdb 329865), Radarr import, Tautulli watch.
    apply_fixture(correlator, "seerr", "request-auto-approved.json")
    apply_fixture(correlator, "radarr", "grab.json")
    apply_fixture(correlator, "radarr", "download-new.json")
    apply_fixture(correlator, "tautulli", "watched-movie.json")

    chain = store.chain_by_request_id("RQ-3001")
    media_id = chain["media_id"]
    events = store.events_for_media(media_id)
    assert [e["type"] for e in events] == [
        "request.approved",
        "media.grabbed",
        "media.imported",
        "watch.completed",
    ]
    media = store.get_media(media_id)
    assert media["tmdb_id"] == 329865
    assert media["imdb_id"] == "tt2543164"  # backfilled from Radarr
    # Tautulli user id 12 maps to Alice via the identity map.
    watch = [e for e in events if e["type"] == "watch.completed"][0]
    assert watch["user_id"] == "u:alice"


def test_series_identity_unifies_seerr_and_sonarr(correlator, store):
    apply_fixture(correlator, "seerr", "tv-request-created.json")
    apply_fixture(correlator, "sonarr", "download-new.json")
    chain = store.chain_by_request_id("RQ-2001")
    events = store.events_for_media(chain["media_id"])
    assert [e["type"] for e in events] == ["request.created", "media.imported"]
    assert store.get_media(chain["media_id"])["kind"] == "series"


def test_duplicate_event_not_reinserted(correlator, store):
    [(first, _)] = apply_fixture(correlator, "radarr", "download-new.json")
    [(second, _)] = apply_fixture(correlator, "radarr", "download-new.json")
    assert first is True
    assert second is False
    assert len(store.list_events(type_="media.imported")) == 1


def test_unmapped_user_recorded_not_guessed(correlator, store):
    def mutate(payload):
        payload["request"]["requestedBy_username"] = "stranger"
        payload["request"]["request_id"] = "RQ-9009"

    [(_, event)] = apply_fixture(correlator, "seerr", "request-created.json", mutate=mutate)
    row = store.get_event_by_key(event.source_event_key)
    assert row["user_id"] is None
    attrs = json.loads(row["attrs_json"])
    assert attrs["unmapped_user"] == {
        "provider": "seerr",
        "external_id": "stranger",
        "display": "stranger",
    }
    assert [(r["provider"], r["external_id"]) for r in store.unmapped_identities()] == [
        ("seerr", "stranger")
    ]


def test_health_issue_has_no_media_or_chain(correlator, store):
    apply_fixture(correlator, "radarr", "health-issue.json")
    row = store.list_events(type_="health.issue")[0]
    assert row["media_id"] is None
    assert store.open_chains() == []


def test_unregistered_source_rejected(correlator):
    from costanza.schemas import CanonicalEvent

    event = CanonicalEvent(source="radarr-se", source_event_key="x:y", type="source.unknown")
    with pytest.raises(ValueError):
        correlator.apply(event)
