"""Hardening regression tests: secret hygiene, digest period stability,
crash-safe reprocessing, dead-row raw retention."""

import json
import traceback
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from costanza.clients import ClientError, TautulliClient
from costanza.config import Config
from costanza.correlate import Correlator
from costanza.jobs import run_reconcile
from costanza.jobs.digest import digest_key, digest_renderer, parse_digest_key, run_digest
from costanza.notify.limits import KillSwitch
from costanza.outbox import process_outbox_once
from costanza.schemas import CanonicalEvent, MediaRef
from costanza.worker import build_processor

API_KEY = "super-secret-tautulli-key"


# -- 1. secrets never leak into logs or summaries ---------------------------------


def _failing_tautulli(status_code=401):
    def handler(request: httpx.Request) -> httpx.Response:
        # Sanity: the key really is on the wire (Tautulli requires it).
        assert API_KEY in str(request.url)
        return httpx.Response(status_code, text="unauthorized")

    return TautulliClient(
        "http://tautulli.local", API_KEY, transport=httpx.MockTransport(handler)
    )


def test_failing_tautulli_request_never_exposes_api_key():
    client = _failing_tautulli(401)
    with pytest.raises(ClientError) as excinfo:
        client.get_history()
    assert API_KEY not in str(excinfo.value)
    assert API_KEY not in repr(excinfo.value)
    # Cause severed and context suppressed: a formatted traceback (what
    # structlog/logging would emit) cannot resurface the URL.
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__suppress_context__ is True
    rendered = "".join(traceback.format_exception(excinfo.value))
    assert API_KEY not in rendered
    assert "HTTP 401" in str(excinfo.value)


def test_transport_error_also_sanitized():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"failed to connect to {request.url}")

    client = TautulliClient(
        "http://tautulli.local", API_KEY, transport=httpx.MockTransport(handler)
    )
    with pytest.raises(ClientError) as excinfo:
        client.get_users()
    assert API_KEY not in str(excinfo.value)
    assert excinfo.value.__suppress_context__ is True
    assert API_KEY not in "".join(traceback.format_exception(excinfo.value))


def test_reconcile_summary_never_contains_api_key(store, routing, now):
    store.sync_sources(routing.sources)
    correlator = Correlator(store)
    clients = {"tautulli": _failing_tautulli(500)}
    summary = run_reconcile(store, correlator, routing, clients, now=now)
    assert API_KEY not in json.dumps(summary)
    assert "HTTP 500" in summary["tautulli"]["error"]


# -- 2. digest rendering is period-stable per pending row --------------------------


def test_two_pending_digests_each_render_their_own_period(store, routing):
    store.sync_sources(routing.sources)
    correlator = Correlator(store)
    kill = KillSwitch(store, env_override=False)

    week1 = datetime(2026, 6, 24, 12, 0, tzinfo=UTC)
    week2 = week1 + timedelta(days=7)

    def imported(title, tmdb, at):
        return CanonicalEvent(
            source="radarr",
            source_event_key=f"radarr:media.imported:{tmdb}:x",
            type="media.imported",
            occurred_at=at,
            received_at=at,
            media=MediaRef(tmdb_id=tmdb, title=title, kind="movie"),
        )

    correlator.apply(imported("Week One Movie", 1001, week1 - timedelta(days=1)))
    correlator.apply(imported("Week Two Movie", 1002, week2 - timedelta(days=1)))

    store.set_kill_switch(False, "test", "test", week1)
    assert run_digest(store, routing, kill, week1) is True
    assert run_digest(store, routing, kill, week2) is True

    # Both rows pending (channel down): each must render ITS period.
    rows = store.query("SELECT event_key FROM notifications ORDER BY event_key")
    assert len(rows) == 2
    render = digest_renderer(store)
    bodies = {
        row["event_key"]: json.dumps(render(row["event_key"]).model_dump(mode="json"))
        for row in rows
    }
    week1_key = digest_key(week1 - timedelta(days=7), week1)
    week2_key = digest_key(week1, week2)
    assert set(bodies) == {week1_key, week2_key}
    assert "Week One Movie" in bodies[week1_key]
    assert "Week Two Movie" not in bodies[week1_key]
    assert "Week Two Movie" in bodies[week2_key]
    assert "Week One Movie" not in bodies[week2_key]


def test_digest_key_roundtrip_and_legacy_fallback(store):
    since = datetime(2026, 6, 28, 18, 0, tzinfo=UTC)
    until = since + timedelta(days=7)
    assert parse_digest_key(digest_key(since, until)) == (since, until)
    assert parse_digest_key("digest:2026-07-04") is None  # legacy shape
    # Legacy keys still render (from the cursor) instead of crashing.
    message = digest_renderer(store)("digest:2026-07-04")
    assert message.kind == "digest"


def test_digest_double_fire_guard(store, routing, now):
    kill = KillSwitch(store, env_override=False)
    store.set_kill_switch(False, "test", "test", now)
    assert run_digest(store, routing, kill, now) is True
    # Scheduler hiccup: re-fire seconds later -> skipped, cursor intact.
    assert run_digest(store, routing, kill, now + timedelta(seconds=30)) is False
    assert len(store.query("SELECT * FROM notifications")) == 1
    assert store.get_cursor("digest")["period_end_at"] == now.isoformat()


# -- 3. crash between event insert and notification enqueue is repaired ------------


@pytest.fixture
def pipeline(store, routing, settings, monkeypatch):
    for name in ("SEERR", "RADARR", "SONARR", "TAUTULLI"):
        monkeypatch.setenv(f"WEBHOOK_SECRET__{name}", "s")
    store.sync_sources(routing.sources)
    store.sync_users(routing.users)
    config = Config(settings=settings, routing=routing)
    correlator = Correlator(store)
    kill = KillSwitch(store, env_override=False)
    processor = build_processor(store, correlator, config, kill)
    return {"store": store, "correlator": correlator, "processor": processor, "kill": kill}


def _enqueue_webhook(store, payload, now, source="seerr"):
    sid = store.source_by_name(source)["id"]
    raw = store.archive_raw(sid, {}, json.dumps(payload), now)
    store.enqueue_outbox(raw, now=now)


_APPROVED = {
    "notification_type": "MEDIA_APPROVED",
    "subject": "Arrival (2016)",
    "media": {"media_type": "movie", "tmdbId": "329865", "status": "APPROVED"},
    "request": {"request_id": "RQ-77", "requestedBy_username": "alice"},
}


def test_crash_before_enqueue_is_repaired_on_retry(pipeline, monkeypatch, now):
    store = pipeline["store"]
    store.set_kill_switch(False, "test", "test", now)
    _enqueue_webhook(store, _APPROVED, now)

    # First pass: the event lands, then the process dies before the
    # notification enqueue.
    calls = {"n": 0}
    import costanza.worker as worker_mod

    real_enqueue = worker_mod.enqueue_for_event

    def crashing_enqueue(*args, **kwargs):
        calls["n"] += 1
        raise RuntimeError("simulated crash after event insert")

    monkeypatch.setattr(worker_mod, "enqueue_for_event", crashing_enqueue)
    process_outbox_once(store, pipeline["processor"], now=now)
    assert calls["n"] == 1
    assert store.event_key_exists("seerr:request.approved:RQ-77")  # stored...
    assert store.query("SELECT * FROM notifications") == []  # ...but silent
    assert store.outbox_backlog() == 1  # retry still owed

    # Retry: the deduped event must still repair the ledger row.
    monkeypatch.setattr(worker_mod, "enqueue_for_event", real_enqueue)
    process_outbox_once(store, pipeline["processor"], now=now + timedelta(minutes=5))
    assert store.outbox_backlog() == 0
    rows = store.notifications_by_key("seerr:request.approved:RQ-77")
    assert [(r["channel"], r["status"]) for r in rows] == [("media-feed", "pending")]
    # Only one event row despite double processing.
    assert len(store.list_events(type_="request.approved")) == 1


def test_crash_before_chain_update_is_repaired_on_retry(pipeline, monkeypatch, now):
    store = pipeline["store"]
    store.set_kill_switch(False, "test", "test", now)
    _enqueue_webhook(store, _APPROVED, now)

    from costanza.correlate.engine import Correlator as Engine

    real_advance = Engine._advance_chain
    calls = {"n": 0}

    def crashing_advance(self, event):
        calls["n"] += 1
        raise RuntimeError("simulated crash after event insert, before chain")

    monkeypatch.setattr(Engine, "_advance_chain", crashing_advance)
    process_outbox_once(store, pipeline["processor"], now=now)
    assert store.event_key_exists("seerr:request.approved:RQ-77")
    assert store.chain_by_request_id("RQ-77") is None  # chain update lost

    monkeypatch.setattr(Engine, "_advance_chain", real_advance)
    process_outbox_once(store, pipeline["processor"], now=now + timedelta(minutes=5))
    chain = store.chain_by_request_id("RQ-77")  # repaired on the deduped retry
    assert chain is not None
    assert chain["state"] == "approved"
    assert store.notifications_by_key("seerr:request.approved:RQ-77") != []


def test_repair_never_double_sends(pipeline, now):
    """An already-sent notification is not resurrected by reprocessing."""
    store = pipeline["store"]
    store.set_kill_switch(False, "test", "test", now)
    _enqueue_webhook(store, _APPROVED, now)
    process_outbox_once(store, pipeline["processor"], now=now)
    row = store.notifications_by_key("seerr:request.approved:RQ-77")[0]
    store.notification_sent(row["id"], now)

    # Duplicate delivery (tee/retry) fully reprocesses; ledger unchanged.
    _enqueue_webhook(store, _APPROVED, now)
    process_outbox_once(store, pipeline["processor"], now=now)
    rows = store.notifications_by_key("seerr:request.approved:RQ-77")
    assert [(r["status"], r["attempts"]) for r in rows] == [("sent", 1)]


def test_duplicate_created_does_not_regress_chain(pipeline, now):
    store = pipeline["store"]
    store.set_kill_switch(False, "test", "test", now)
    created = {**_APPROVED, "notification_type": "MEDIA_PENDING",
               "media": {**_APPROVED["media"], "status": "PENDING"}}
    _enqueue_webhook(store, created, now)
    _enqueue_webhook(store, _APPROVED, now)
    process_outbox_once(store, pipeline["processor"], now=now)
    assert store.chain_by_request_id("RQ-77")["state"] == "approved"
    # Late re-delivery of request.created must not walk the chain backwards.
    _enqueue_webhook(store, created, now)
    process_outbox_once(store, pipeline["processor"], now=now)
    assert store.chain_by_request_id("RQ-77")["state"] == "approved"


# -- 4. dead outbox rows do not preserve raw bodies past retention ------------------


def test_dead_raw_bodies_redacted_after_retention(store, routing, now):
    store.sync_sources(routing.sources)
    sid = store.source_by_name("tautulli")["id"]
    sensitive = '{"plex_username": "alice", "title": "Very Private Movie"}'
    old_raw = store.archive_raw(
        sid, {"user-agent": "Tautulli/2.x"}, sensitive, now - timedelta(days=31)
    )
    store.enqueue_outbox(old_raw, dead=True, error="invalid_json: nope")
    fresh_raw = store.archive_raw(sid, {}, sensitive, now)
    store.enqueue_outbox(fresh_raw, dead=True, error="invalid_json: nope")

    pruned, done, redacted = store.prune(30, now)
    assert (pruned, done, redacted) == (0, 0, 1)

    old = store.get_raw(old_raw)
    assert old is not None  # diagnostics row survives...
    assert "Very Private Movie" not in old["body_json"]  # ...the payload does not
    assert old["headers_subset"] == "{}"
    assert json.loads(old["body_json"])["redacted"]
    # Recent dead rows keep their body for debugging until they age out.
    assert "Very Private Movie" in store.get_raw(fresh_raw)["body_json"]
    # Dead-letter metadata (error, count) is preserved for diagnostics.
    assert store.outbox_dead_count() == 2
    # Idempotent: a second prune redacts nothing new.
    assert store.prune(30, now) == (0, 0, 0)


def test_stuck_pending_raw_also_redacted(store, routing, now):
    store.sync_sources(routing.sources)
    sid = store.source_by_name("radarr")["id"]
    raw = store.archive_raw(sid, {}, '{"secret": "body"}', now - timedelta(days=40))
    store.enqueue_outbox(raw)  # never processed (pathological)
    _, _, redacted = store.prune(30, now)
    assert redacted == 1
    assert "secret" not in store.get_raw(raw)["body_json"]


# -- H10: every read client shares the sanitized error path; webhook secrets
# -- never reach logs -----------------------------------------------------------


def _leaky_transport(secret_marker):
    def handler(request: httpx.Request) -> httpx.Response:
        # The secret is on the wire (header or URL) — that's expected;
        # it must never surface in raised exceptions or logs.
        assert secret_marker in str(request.url) or secret_marker in str(
            dict(request.headers)
        )
        return httpx.Response(500, text="boom")

    return httpx.MockTransport(handler)


def test_seerr_client_failures_are_sanitized():
    from costanza.clients import SeerrClient

    key = "seerr-api-key-abc123"
    client = SeerrClient("http://seerr.local", key, transport=_leaky_transport(key))
    with pytest.raises(ClientError) as excinfo:
        client.get_requests()
    assert key not in str(excinfo.value)
    assert key not in "".join(traceback.format_exception(excinfo.value))
    assert "HTTP 500" in str(excinfo.value)


def test_arr_client_failures_are_sanitized():
    from costanza.clients import ArrClient

    key = "radarr-api-key-def456"
    client = ArrClient("http://radarr.local", key, transport=_leaky_transport(key))
    with pytest.raises(ClientError) as excinfo:
        client.get_history()
    assert key not in str(excinfo.value)
    assert key not in "".join(traceback.format_exception(excinfo.value))


def test_webhook_secret_never_logged(store, routing, monkeypatch):
    """Neither a wrong presented token nor the configured secret may appear
    in ingest logs — auth failures log only the source name."""
    import structlog
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from costanza.ingest import SourceRegistry, build_ingest_router

    real_secret = "real-webhook-secret-xyz"
    wrong_secret = "attacker-guess-123"
    monkeypatch.setenv("WEBHOOK_SECRET__RADARR", real_secret)
    store.sync_sources(routing.sources)
    app = FastAPI()
    app.include_router(build_ingest_router(SourceRegistry(routing), store, 1024))
    client = TestClient(app)

    with structlog.testing.capture_logs() as logs:
        resp = client.post(
            "/webhooks/radarr", json={}, headers={"X-Webhook-Token": wrong_secret}
        )
        assert resp.status_code == 401
        client.post(
            "/webhooks/radarr",
            content="{not json",
            headers={"X-Webhook-Token": real_secret, "Content-Type": "application/json"},
        )
    rendered = json.dumps(logs, default=str)
    assert wrong_secret not in rendered
    assert real_secret not in rendered
    assert any(entry.get("source") == "radarr" for entry in logs)
