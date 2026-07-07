import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from conftest import load_fixture

from costanza.api import build_api_router, build_ops_router
from costanza.config import Config
from costanza.correlate import Correlator
from costanza.main import create_metrics_app
from costanza.normalize import normalize
from costanza.notify.limits import KillSwitch

TOKEN = "household-token"


def _client(store, routing, settings, env_override=False):
    settings = settings.model_copy(update={"api_bearer_token": TOKEN})
    config = Config(settings=settings, routing=routing)
    kill = KillSwitch(store, env_override=env_override)
    app = FastAPI()
    app.include_router(build_api_router(config, store, kill))
    app.include_router(build_ops_router(config, store))
    return TestClient(app)


@pytest.fixture
def client(store, routing, settings):
    store.sync_sources(routing.sources)
    store.sync_users(routing.users)
    return _client(store, routing, settings)


@pytest.fixture
def auth():
    return {"Authorization": f"Bearer {TOKEN}"}


def _seed(store, routing):
    correlator = Correlator(store)
    for source, name in (
        ("seerr", "request-auto-approved.json"),
        ("radarr", "download-new.json"),
        ("tautulli", "watched-movie.json"),
    ):
        for event in normalize(source, source, load_fixture(source, name)):
            correlator.apply(event)
    return store.chain_by_request_id("RQ-3001")["media_id"]


def test_api_requires_bearer_token(client):
    assert client.get("/api/v1/events").status_code == 401
    assert client.get(
        "/api/v1/events", headers={"Authorization": "Bearer wrong"}
    ).status_code == 401


def test_unconfigured_token_locks_api(store, routing, settings):
    config = Config(settings=settings, routing=routing)  # api_bearer_token=None
    app = FastAPI()
    app.include_router(build_api_router(config, store, KillSwitch(store, False)))
    client = TestClient(app)
    assert client.get(
        "/api/v1/events", headers={"Authorization": "Bearer "}
    ).status_code == 401


def test_events_endpoint_filters(client, store, routing, auth):
    _seed(store, routing)
    events = client.get("/api/v1/events", headers=auth).json()["events"]
    assert len(events) == 3
    watched = client.get(
        "/api/v1/events", headers=auth, params={"type": "watch.completed"}
    ).json()["events"]
    assert len(watched) == 1
    assert watched[0]["user_id"] == "u:alice"
    by_user = client.get(
        "/api/v1/events", headers=auth, params={"user": "u:alice"}
    ).json()["events"]
    assert len(by_user) == 2  # request + watch
    assert client.get(
        "/api/v1/events", headers=auth, params={"type": "nonsense"}
    ).status_code == 422


def test_timeline_endpoint(client, store, routing, auth):
    media_id = _seed(store, routing)
    body = client.get(f"/api/v1/media/{media_id}/timeline", headers=auth).json()
    assert body["media"]["tmdb_id"] == 329865
    assert [e["type"] for e in body["events"]] == [
        "request.approved",
        "media.imported",
        "watch.completed",
    ]
    assert body["chains"][0]["state"] == "approved"
    assert client.get("/api/v1/media/nope/timeline", headers=auth).status_code == 404


def test_stats_endpoints(client, store, routing, auth):
    _seed(store, routing)
    requests = client.get("/api/v1/stats/requests", headers=auth).json()["per_user"]
    assert requests == [{"user": "Alice", "made": 1, "available": 0, "watched": 1}]
    watch = client.get("/api/v1/stats/watch", headers=auth).json()["per_user"]
    assert watch[0]["user"] == "Alice"
    assert watch[0]["completions"] == 1


def test_digest_preview(client, store, routing, auth):
    _seed(store, routing)
    body = client.get("/api/v1/digest/preview", headers=auth).json()
    assert body["rendered"]["kind"] == "digest"
    labels = [a["label"] for a in body["data"]["new_arrivals"]]
    assert labels == ["Arrival (2016)"]


def test_kill_switch_roundtrip_and_audit(client, store, auth):
    state = client.get("/api/v1/admin/kill-switch", headers=auth).json()
    assert state["engaged"] is True  # safe default on a fresh store
    resp = client.post(
        "/api/v1/admin/kill-switch",
        headers=auth,
        json={"engaged": False, "set_by": "alice"},
    )
    assert resp.status_code == 200
    state = resp.json()
    assert state["engaged"] is False
    assert state["set_by"] == "alice"
    # Audit trail persisted, not just in memory.
    rows = store.query("SELECT * FROM kill_switch_audit ORDER BY id")
    assert [(bool(r["engaged"]), r["set_by"], r["via"]) for r in rows] == [
        (False, "alice", "api")
    ]


def test_env_override_reported_and_wins(store, routing, settings, auth):
    store.sync_sources(routing.sources)
    store.set_kill_switch(False, "alice", "api")
    client = _client(store, routing, settings, env_override=True)
    state = client.get("/api/v1/admin/kill-switch", headers=auth).json()
    assert state["env_override"] is True
    assert state["engaged"] is True  # env wins over the stored toggle


def test_ops_endpoints_unauthenticated(client, store, routing):
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/readyz").json() == {"status": "ready"}
    metrics = TestClient(create_metrics_app()).get("/metrics")
    assert metrics.status_code == 200
    assert "costanza_outbox_backlog" in metrics.text
    assert "costanza_webhook_auth_failures" in metrics.text


def test_diagnostics_surfaces_dead_items(client, store, routing, auth, now):
    sid = store.source_by_name("radarr")["id"]
    raw = store.archive_raw(sid, {}, "not json", now)
    store.enqueue_outbox(raw, dead=True, error="invalid_json: boom")
    store.enqueue_notification("seerr:ghost:1", "media-feed", "h", now)
    row = store.claim_notifications_due(now=now)[0]
    store.notification_dead(row["id"], "event_missing")
    body = client.get("/api/v1/admin/diagnostics", headers=auth).json()
    assert body["dead_outbox"][0]["last_error"].startswith("invalid_json")
    assert body["dead_notifications"][0]["event_key"] == "seerr:ghost:1"
