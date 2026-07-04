"""Renderer snapshot tests (pure functions -> stable output)."""

from conftest import load_fixture

from costanza.normalize import normalize
from costanza.notify.render import render_digest, render_event, rendered_hash
from costanza.schemas import CanonicalEvent, MediaRef, UserRef


def _event(source, *parts):
    payload = load_fixture(source, *parts)
    return normalize(source, source, payload)[0]


def test_request_created_snapshot():
    message = render_event(_event("seerr", "request-created.json"))
    assert message.model_dump(mode="json") == {
        "kind": "embed",
        "title": "New request: The Quiet Place",
        "description": "Requested by alice",
        "fields": [],
        "color": 0x3498DB,
        "footer": "source: seerr",
    }


def test_tv_request_with_seasons_snapshot():
    message = render_event(_event("seerr", "tv-request-created.json"))
    assert message.model_dump(mode="json") == {
        "kind": "embed",
        "title": "New request: The Expanse (2015)",
        "description": "Requested by bob",
        "fields": [["Seasons", "1, 2"]],
        "color": 0x3498DB,
        "footer": "source: seerr",
    }


def test_partial_available_snapshot():
    message = render_event(_event("seerr", "request-partially-available.json"))
    assert message.title == "Partially available: The Quiet Place"


def test_import_snapshot():
    message = render_event(_event("radarr", "download-new.json"))
    assert message.model_dump(mode="json") == {
        "kind": "embed",
        "title": "Added to library: Arrival (2016)",
        "description": "",
        "fields": [["Quality", "WEBDL-2160p"]],
        "color": 0x1ABC9C,
        "footer": "source: radarr",
    }


def test_episode_label_includes_sxxeyy():
    message = render_event(_event("sonarr", "download-new.json"))
    assert message.title == "Added to library: The Expanse (2015) S01E01"


def test_health_issue_snapshot():
    message = render_event(_event("radarr", "health-issue.json"))
    assert message.title == "Health warning: radarr"
    assert message.description == "Indexers unavailable due to failures: nzbgeek"


def test_request_failed_maps_to_health_title():
    message = render_event(_event("seerr", "media-failed.json"))
    assert message.title == "Request failed: Arrival (2016)"


def test_reconcile_origin_flagged():
    event = CanonicalEvent(
        source="seerr",
        source_event_key="seerr:request.available:1",
        origin="reconcile",
        type="request.available",
        media=MediaRef(title="Arrival", year=2016, kind="movie"),
        user=UserRef(display="Alice"),
        attrs={},
    )
    message = render_event(event)
    assert ("Origin", "reconcile (synthesized after the fact)") in message.fields


def test_reconcile_gap_snapshot():
    event = CanonicalEvent(
        source="radarr",
        source_event_key="reconcile:gap:radarr:2026-07-01",
        origin="reconcile",
        type="reconcile.gap",
        attrs={"recovered": 3, "transient_kinds": ["health.issue"]},
    )
    message = render_event(event)
    assert message.title == "Reconcile gap: radarr"
    assert ("Recovered events", "3") in message.fields
    assert ("Not reconstructable", "health.issue") in message.fields


def test_watch_completed_description():
    message = render_event(_event("tautulli", "watched-movie.json"))
    assert message.title == "Watched: Arrival (2016)"
    assert message.description == "Watched by alice"


def test_rendered_hash_is_stable_and_content_sensitive():
    a = render_event(_event("radarr", "download-new.json"))
    b = render_event(_event("radarr", "download-new.json"))
    c = render_event(_event("radarr", "download-upgrade.json"))
    assert rendered_hash(a) == rendered_hash(b)
    assert rendered_hash(a) != rendered_hash(c)


def test_digest_snapshot():
    data = {
        "period_start": "2026-06-28",
        "period_end": "2026-07-05",
        "new_arrivals": [{"label": "Arrival (2016)"}, {"label": "The Expanse (2015) S01E01"}],
        "requests": {"opened": 3, "available": 2, "declined": 1, "stale": ["Dune (2021)"]},
        "watches": {
            "top": [{"label": "Arrival (2016)", "count": 2}],
            "per_user": [{"display": "Alice", "count": 3}],
        },
        "ops": {
            "gaps": 1,
            "dead_notifications": 0,
            "dead_outbox": 2,
            "unknown_events": 4,
            "unmapped_identities": ["plex:stranger"],
        },
    }
    message = render_digest(data)
    assert message.kind == "digest"
    assert message.title == "Weekly media digest — 2026-06-28 to 2026-07-05"
    names = [name for name, _ in message.fields]
    assert names == ["New arrivals", "Requests", "Still waiting", "Most watched",
                     "Watch counts", "Ops"]
    ops = dict(message.fields)["Ops"]
    assert "reconcile gaps: 1" in ops
    assert "dead ingest items: 2" in ops
    assert "unmapped identities: plex:stranger" in ops
    assert "dead notifications" not in ops  # zero counts are omitted


def test_digest_quiet_week():
    message = render_digest({"period_start": "a", "period_end": "b"})
    assert message.fields == []
    assert "quiet week" in message.description
