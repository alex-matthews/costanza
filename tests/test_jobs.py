"""Reconcile diff tests against canned API responses (guarantees matrix),
plus digest, prune, and identity_sync."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from conftest import load_fixture

from costanza.correlate import Correlator
from costanza.jobs import run_digest, run_identity_sync, run_prune, run_reconcile
from costanza.jobs.digest import build_digest_data, digest_renderer
from costanza.normalize import normalize
from costanza.notify.limits import KillSwitch


class FakeSeerr:
    def __init__(self, requests=None, users=None):
        self._requests = requests or []
        self._users = users or []

    def get_requests(self):
        return self._requests

    def get_users(self):
        return self._users


class FakeArr:
    def __init__(self, records):
        self._records = records

    def get_history(self, since=None):
        return self._records


class FakeTautulli:
    def __init__(self, rows=None, users=None):
        self._rows = rows or []
        self._users = users or []

    def get_history(self, after=None):
        return self._rows

    def get_users(self):
        return self._users


@pytest.fixture
def correlator(store, routing):
    store.sync_sources(routing.sources)
    store.sync_users(routing.users)
    return Correlator(store)


def _ingest(correlator, source, name):
    for event in normalize(source, source, load_fixture(source, name)):
        correlator.apply(event)


def _events(store, **kwargs):
    return store.list_events(**kwargs)


# -- seerr: fully reconstructable, no gap marker ---------------------------------


def test_reconcile_seerr_synthesizes_missing_lifecycle(store, routing, correlator, now):
    clients = {"seerr": FakeSeerr(load_fixture("reconcile", "seerr-requests.json")["results"])}
    summary = run_reconcile(store, correlator, routing, clients, now=now)
    # Request 555: created+approved+available; 556: created+declined.
    assert summary["seerr"] == {"recovered": 5, "gap_marked": False}
    for key in (
        "seerr:request.created:555",
        "seerr:request.approved:555",
        "seerr:request.available:555:AVAILABLE",
        "seerr:request.created:556",
        "seerr:request.declined:556",
    ):
        row = store.get_event_by_key(key)
        assert row is not None, key
        assert row["origin"] == "reconcile"
    # Chains advanced: 555 closed available, 556 closed declined.
    assert store.chain_by_request_id("555")["state"] == "available"
    assert store.chain_by_request_id("556")["state"] == "declined"
    # occurred_at comes from the API record, not from now.
    created = store.get_event_by_key("seerr:request.created:555")
    assert created["occurred_at"].startswith("2026-07-03T10:00")
    # Seerr is fully reconstructable: no reconcile.gap marker.
    assert _events(store, type_="reconcile.gap") == []
    # Users resolved through the identity map.
    assert created["user_id"] == "u:alice"


def test_reconcile_seerr_is_idempotent_and_quiet_when_current(store, routing, correlator, now):
    clients = {"seerr": FakeSeerr(load_fixture("reconcile", "seerr-requests.json")["results"])}
    run_reconcile(store, correlator, routing, clients, now=now)
    summary = run_reconcile(store, correlator, routing, clients, now=now + timedelta(hours=1))
    assert summary["seerr"] == {"recovered": 0, "gap_marked": False}


# -- radarr/sonarr: history mostly reconstructable; transient kinds flag-only ----


def test_reconcile_radarr_matrix(store, routing, correlator, now):
    # Webhooks arrived for Arrival's grab+import; Dune's upgrade + delete missed.
    _ingest(correlator, "radarr", "grab.json")
    _ingest(correlator, "radarr", "download-new.json")
    records = load_fixture("reconcile", "radarr-history.json")["records"]
    clients = {"radarr": FakeArr(records)}
    summary = run_reconcile(store, correlator, routing, clients, now=now)
    # Recovered: Dune import-upgrade (MISSED123) + Dune file delete. The
    # Arrival records collapse onto the webhook keys.
    assert summary["radarr"]["recovered"] == 2
    assert len(_events(store, type_="media.grabbed")) == 1
    assert len(_events(store, type_="media.imported")) == 1
    upgraded = store.get_event_by_key("radarr:media.upgraded:693134:MISSED123")
    assert upgraded is not None
    assert upgraded["origin"] == "reconcile"
    assert json.loads(upgraded["attrs_json"])["quality"] == "WEBDL-2160p"
    deleted = _events(store, type_="media.deleted")
    assert len(deleted) == 1
    # Gap marker stored: transient kinds not reconstructable for this window.
    gaps = _events(store, type_="reconcile.gap")
    assert len(gaps) == 1
    attrs = json.loads(gaps[0]["attrs_json"])
    assert attrs["transient_kinds"] == ["health.issue", "failed downloads"]
    assert attrs["recovered"] == 2


def test_reconcile_radarr_delete_guarded_by_near_window(store, routing, correlator, now):
    # The webhook delete already arrived (different key shape than history).
    _ingest(correlator, "radarr", "movie-file-delete.json")
    records = [r for r in load_fixture("reconcile", "radarr-history.json")["records"]
               if r["eventType"] == "movieFileDeleted"]
    clients = {"radarr": FakeArr(records)}
    summary = run_reconcile(store, correlator, routing, clients, now=now)
    assert summary["radarr"]["recovered"] == 0
    assert len(_events(store, type_="media.deleted")) == 1


def test_reconcile_sonarr_matrix(store, routing, correlator, now):
    # Season-pack grab webhook arrived (multi-episode key); history has
    # per-episode records with the same downloadId -> fuzzy dedupe.
    _ingest(correlator, "sonarr", "grab-season-pack.json")
    records = load_fixture("reconcile", "sonarr-history.json")["records"]
    clients = {"sonarr": FakeArr(records)}
    summary = run_reconcile(store, correlator, routing, clients, now=now)
    # Recovered: MISSEDEP grab + the episode file delete. downloadFailed is
    # flag-only and never synthesized.
    assert summary["sonarr"]["recovered"] == 2
    grabbed = _events(store, type_="media.grabbed")
    assert len(grabbed) == 2  # season pack webhook + missed S03E01
    missed = store.get_event_by_key("sonarr:media.grabbed:280619:S03E01:MISSEDEP")
    assert missed is not None
    assert not any(
        "FAILEDDL" in e["source_event_key"] for e in store.list_events(limit=1000)
    )
    assert len(_events(store, type_="reconcile.gap")) == 1


# -- tautulli: watch.completed reconstructable; playback flag-only ----------------


def test_reconcile_tautulli_matrix(store, routing, correlator, now):
    _ingest(correlator, "tautulli", "watched-movie.json")  # webhook twin of row 7001
    rows = load_fixture("reconcile", "tautulli-history.json")["response"]["data"]["data"]
    clients = {"tautulli": FakeTautulli(rows=rows)}
    summary = run_reconcile(store, correlator, routing, clients, now=now)
    # Only the missed episode watch is synthesized; watched_status=0 is not
    # durable truth, and no playback.started/stopped are ever synthesized.
    assert summary["tautulli"]["recovered"] == 1
    watches = _events(store, type_="watch.completed")
    assert len(watches) == 2
    synth = store.get_event_by_key("tautulli:watch.completed:13:61099")
    assert synth["origin"] == "reconcile"
    assert synth["user_id"] == "u:bob"
    assert _events(store, type_="playback.started") == []
    assert _events(store, type_="playback.stopped") == []
    assert len(_events(store, type_="reconcile.gap")) == 1


def test_reconcile_survives_broken_source(store, routing, correlator, now):
    class Exploding:
        def get_requests(self):
            raise RuntimeError("api down")

    rows = load_fixture("reconcile", "tautulli-history.json")["response"]["data"]["data"]
    clients = {"seerr": Exploding(), "tautulli": FakeTautulli(rows=rows)}
    summary = run_reconcile(store, correlator, routing, clients, now=now)
    assert "error" in summary["seerr"]
    assert summary["tautulli"]["recovered"] == 2


# -- digest ---------------------------------------------------------------------


def test_digest_enqueues_once_and_renders(store, routing, correlator):
    kill = KillSwitch(store, env_override=False)
    _ingest(correlator, "radarr", "download-new.json")
    _ingest(correlator, "tautulli", "watched-movie.json")
    # Window end must fall after the wall-clock received_at of the events.
    now = datetime.now(UTC) + timedelta(seconds=1)
    store.set_kill_switch(False, "test", "test", now)

    assert run_digest(store, routing, kill, now) is True
    assert run_digest(store, routing, kill, now) is False  # UNIQUE dedupe
    rows = store.query("SELECT * FROM notifications WHERE event_key LIKE 'digest:%'")
    assert len(rows) == 1
    assert rows[0]["channel"] == "media-digest"

    message = digest_renderer(store)("digest:whatever")
    assert message.kind == "digest"
    body = json.dumps(message.model_dump(mode="json"))
    assert "Arrival (2016)" in body

    data = build_digest_data(store, now - timedelta(days=7), now)
    assert data["new_arrivals"][0]["label"] == "Arrival (2016)"
    assert data["watches"]["per_user"] == [{"display": "Alice", "count": 1}]


def test_digest_respects_kill_switch(store, routing, now):
    kill = KillSwitch(store, env_override=False)  # default state: engaged
    assert run_digest(store, routing, kill, now) is False
    assert store.notification_counts() == {}


def test_digest_period_advances_with_cursor(store, routing, now):
    store.set_kill_switch(False, "test", "test", now)
    kill = KillSwitch(store, env_override=False)
    run_digest(store, routing, kill, now)
    later = now + timedelta(days=7)
    run_digest(store, routing, kill, later)
    cursor = store.get_cursor("digest")
    assert cursor["period_start_at"] == now.isoformat()
    assert cursor["period_end_at"] == later.isoformat()


# -- prune + identity_sync ---------------------------------------------------------


def test_prune_job(store, routing, now):
    store.sync_sources(routing.sources)
    sid = store.source_by_name("radarr")["id"]
    old_raw = store.archive_raw(sid, {}, "{}", now - timedelta(days=31))
    ob = store.enqueue_outbox(old_raw)
    store.outbox_done(ob)
    fresh = store.archive_raw(sid, {}, "{}", now)
    pruned, done, redacted = run_prune(store, 30, now)
    assert (pruned, done, redacted) == (1, 1, 0)
    assert store.get_raw(fresh) is not None


def test_identity_sync_flags_unmapped_users(store, routing, now):
    store.sync_users(routing.users)
    clients = {
        "seerr": FakeSeerr(users=[{"username": "alice"}, {"username": "grandma"}]),
        "tautulli": FakeTautulli(users=[{"user_id": 12}, {"user_id": 99}]),
    }
    kinds = {"seerr": "seerr", "tautulli": "tautulli"}
    observed = run_identity_sync(store, clients, kinds)
    assert observed == 2  # grandma + tautulli 99; mapped users untouched
    unmapped = {(r["provider"], r["external_id"]) for r in store.unmapped_identities()}
    assert unmapped == {("seerr", "grandma"), ("tautulli", "99")}
    # Second run observes nothing new.
    assert run_identity_sync(store, clients, kinds) == 0


def test_identity_sync_survives_broken_client(store, routing):
    class Exploding:
        def get_users(self):
            raise RuntimeError("api down")

    observed = run_identity_sync(
        store,
        {"seerr": Exploding(), "tautulli": FakeTautulli(users=[{"user_id": 7}])},
        {"seerr": "seerr", "tautulli": "tautulli"},
    )
    assert observed == 1


def test_reconcile_tautulli_occurred_at_from_history(store, routing, correlator):
    now = datetime(2026, 7, 4, 12, 0, tzinfo=UTC)
    rows = load_fixture("reconcile", "tautulli-history.json")["response"]["data"]["data"]
    clients = {"tautulli": FakeTautulli(rows=rows)}
    run_reconcile(store, correlator, routing, clients, now=now)
    synth = store.get_event_by_key("tautulli:watch.completed:12:51234")
    # 1782033600 epoch, not `now`.
    assert synth["occurred_at"] != synth["received_at"]
