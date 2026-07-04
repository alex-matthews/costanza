import json
from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from costanza.ingest import SourceRegistry, build_ingest_router
from costanza.outbox import backoff, process_outbox_once

SECRET = "s3cret"


@pytest.fixture(autouse=True)
def _secrets(monkeypatch):
    for name in ("SEERR", "RADARR", "SONARR", "TAUTULLI"):
        monkeypatch.setenv(f"WEBHOOK_SECRET__{name}", SECRET)


@pytest.fixture
def client(store, routing):
    store.sync_sources(routing.sources)
    app = FastAPI()
    app.include_router(build_ingest_router(SourceRegistry(routing), store, 1024))
    return TestClient(app)


def _post(client, source="radarr", body=None, token=SECRET, **kwargs):
    headers = kwargs.pop("headers", {})
    if token is not None:
        headers["X-Webhook-Token"] = token
    return client.post(
        f"/webhooks/{source}",
        content=json.dumps(body) if isinstance(body, dict) else body,
        headers={"Content-Type": "application/json", **headers},
        **kwargs,
    )


def test_accept_archive_202(client, store):
    resp = _post(client, body={"eventType": "Test"})
    assert resp.status_code == 202
    rows = store.query("SELECT * FROM raw_events")
    assert len(rows) == 1
    assert json.loads(rows[0]["body_json"]) == {"eventType": "Test"}
    assert "content-type" in json.loads(rows[0]["headers_subset"])
    assert store.outbox_backlog() == 1


def test_bearer_auth_also_accepted(client, store):
    resp = _post(
        client, body={}, token=None, headers={"Authorization": f"Bearer {SECRET}"}
    )
    assert resp.status_code == 202


def test_auth_failure_401_and_no_archive(client, store):
    assert _post(client, body={}, token="wrong").status_code == 401
    assert _post(client, body={}, token=None).status_code == 401
    assert store.query("SELECT * FROM raw_events") == []
    assert store.outbox_backlog() == 0


def test_source_without_secret_rejects_everything(client, store, monkeypatch):
    monkeypatch.delenv("WEBHOOK_SECRET__RADARR")
    assert _post(client, body={}).status_code == 401


def test_unknown_source_404(client, store):
    assert _post(client, source="radarr-se", body={}).status_code == 404
    assert _post(client, source="nonsense", body={}).status_code == 404


def test_disabled_source_404(store, routing, monkeypatch):
    routing.sources[1].enabled = False
    store.sync_sources(routing.sources)
    app = FastAPI()
    app.include_router(build_ingest_router(SourceRegistry(routing), store, 1024))
    client = TestClient(app)
    assert _post(client, source="radarr", body={}).status_code == 404


def test_oversize_413(client, store):
    big = json.dumps({"pad": "x" * 2048})
    assert _post(client, body=big).status_code == 413
    assert store.query("SELECT * FROM raw_events") == []


def test_invalid_json_archived_dead_202(client, store):
    resp = _post(client, body="{not json")
    assert resp.status_code == 202  # never a source-facing error
    assert len(store.query("SELECT * FROM raw_events")) == 1
    assert store.outbox_backlog() == 0
    assert store.outbox_dead_count() == 1
    dead = store.query("SELECT * FROM outbox WHERE state = 'dead'")[0]
    assert dead["last_error"].startswith("invalid_json")


def test_duplicate_delivery_archives_both(client, store):
    # A Chaski tee / source retry double-delivers: both raws archived; the
    # canonical-event dedupe happens off-path via source_event_key.
    _post(client, body={"eventType": "Test"})
    _post(client, body={"eventType": "Test"})
    assert len(store.query("SELECT * FROM raw_events")) == 2
    assert store.outbox_backlog() == 2


def test_outbox_worker_success_and_retry_and_dead(store, routing, now):
    store.sync_sources(routing.sources)
    sid = store.source_by_name("radarr")["id"]
    raw_id = store.archive_raw(sid, {}, '{"ok": true}', now)
    store.enqueue_outbox(raw_id, now=now)

    seen = []
    handled = process_outbox_once(store, lambda raw: seen.append(raw["id"]), now=now)
    assert handled == 1
    assert seen == [raw_id]
    assert store.outbox_backlog() == 0

    # Failing processor: retries with backoff, then dead-letters.
    bad_raw = store.archive_raw(sid, {}, "{}", now)
    store.enqueue_outbox(bad_raw, now=now)

    def boom(raw):
        raise RuntimeError("normalizer exploded")

    t = now
    for attempt in range(5):
        process_outbox_once(store, boom, max_attempts=5, now=t)
        t += backoff(2.0, attempt) + timedelta(seconds=1)
    assert store.outbox_backlog() == 0
    assert store.outbox_dead_count() == 1
    dead = store.query("SELECT * FROM outbox WHERE state = 'dead'")[0]
    assert "normalizer exploded" in dead["last_error"]
    # A poisoned payload never blocks the queue for later arrivals.
    ok_raw = store.archive_raw(sid, {}, "{}", t)
    store.enqueue_outbox(ok_raw, now=t)
    assert process_outbox_once(store, lambda raw: None, now=t) == 1
    assert store.outbox_backlog() == 0
