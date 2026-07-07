"""Reconcile crash repair: a crash between a reconcile event insert and its
notification enqueue must be repaired on the next run — without resurrecting
webhook-origin twins or kill-switch-suppressed history, and without
double-counting recovered events or double-sending."""

from datetime import timedelta

import pytest

from conftest import load_fixture

import costanza.jobs.reconcile as reconcile_mod
from costanza.correlate import Correlator
from costanza.jobs import run_reconcile
from costanza.normalize import normalize
from costanza.notify.limits import KillSwitch


class FakeSeerr:
    def __init__(self, requests):
        self._requests = requests

    def get_requests(self):
        return self._requests


class FakeTautulli:
    def __init__(self, rows):
        self._rows = rows

    def get_history(self, after=None):
        return self._rows


class FakeArr:
    def __init__(self, records):
        self._records = records

    def get_history(self, since=None):
        return self._records


@pytest.fixture
def env(store, routing, now):
    store.sync_sources(routing.sources)
    store.sync_users(routing.users)
    store.set_kill_switch(False, "test", "test", now)
    return {
        "store": store,
        "routing": routing,
        "correlator": Correlator(store),
        "kill": KillSwitch(store, env_override=False),
    }


def _run(env, clients, now):
    return run_reconcile(
        env["store"], env["correlator"], env["routing"], clients,
        kill_switch=env["kill"], now=now,
    )


def _crash_on(monkeypatch, event_key):
    """Patch the reconcile module's enqueue to die for one specific event."""
    real = reconcile_mod.enqueue_for_event
    calls = {"crashes": 0}

    def crashing(store, routing, kill, event, now=None):
        if event.source_event_key == event_key:
            calls["crashes"] += 1
            raise RuntimeError("simulated crash after insert, before enqueue")
        return real(store, routing, kill, event, now)

    monkeypatch.setattr(reconcile_mod, "enqueue_for_event", crashing)
    return calls


def test_seerr_crash_before_enqueue_repaired_on_rerun(env, monkeypatch, now):
    store = env["store"]
    clients = {"seerr": FakeSeerr(load_fixture("reconcile", "seerr-requests.json")["results"])}

    calls = _crash_on(monkeypatch, "seerr:request.approved:555")
    summary = _run(env, clients, now)
    assert calls["crashes"] == 1
    assert "error" in summary["seerr"]  # run failed; cursor NOT advanced
    assert store.get_cursor("reconcile:seerr") is None
    # The approved event landed, but its notification never did.
    assert store.event_key_exists("seerr:request.approved:555")
    assert store.notifications_by_key("seerr:request.approved:555") == []

    # Rerun with the crash gone: exact-key duplicates repair the ledger.
    monkeypatch.setattr(reconcile_mod, "enqueue_for_event", reconcile_mod.enqueue_for_event)
    monkeypatch.undo()
    summary = _run(env, clients, now + timedelta(minutes=10))
    # Events already stored are never re-counted as recovered.
    assert summary["seerr"]["recovered"] == 3  # available:555 + both 556 events
    approved = store.notifications_by_key("seerr:request.approved:555")
    assert [(r["channel"], r["status"]) for r in approved] == [("media-feed", "pending")]
    available = store.notifications_by_key("seerr:request.available:555:AVAILABLE")
    assert [(r["channel"], r["status"]) for r in available] == [("media-feed", "pending")]

    # Third run: fully quiet, nothing duplicated.
    summary = _run(env, clients, now + timedelta(minutes=20))
    assert summary["seerr"]["recovered"] == 0
    assert len(store.notifications_by_key("seerr:request.approved:555")) == 1
    assert len(store.query("SELECT * FROM notifications")) == 2


def test_repair_never_resurrects_webhook_origin_twin(env, now):
    """A webhook-origin event with the exact reconcile key is the ingest
    worker's responsibility; reconcile repair must leave it alone."""
    store = env["store"]
    payload = {
        "notification_type": "MEDIA_APPROVED",
        "subject": "Arrival (2016)",
        "media": {"media_type": "movie", "tmdbId": "329865", "status": "APPROVED"},
        "request": {"request_id": "555", "requestedBy_username": "alice"},
    }
    # Stored during shadow mode: no ledger row was ever created (suppressed).
    for event in normalize("seerr", "seerr", payload):
        event.received_at = now
        env["correlator"].apply(event)
    row = store.get_event_by_key("seerr:request.approved:555")
    assert row["origin"] == "webhook"

    clients = {"seerr": FakeSeerr(load_fixture("reconcile", "seerr-requests.json")["results"])}
    _run(env, clients, now + timedelta(hours=1))
    assert store.notifications_by_key("seerr:request.approved:555") == []


def test_repair_never_double_sends(env, now):
    store = env["store"]
    clients = {"seerr": FakeSeerr(load_fixture("reconcile", "seerr-requests.json")["results"])}
    _run(env, clients, now)
    row = store.notifications_by_key("seerr:request.approved:555")[0]
    store.notification_sent(row["id"], now)
    # Reruns repair-attempt every window event; UNIQUE keeps the sent row.
    _run(env, clients, now + timedelta(minutes=30))
    rows = store.notifications_by_key("seerr:request.approved:555")
    assert [(r["status"], r["attempts"]) for r in rows] == [("sent", 1)]


def test_suppressed_history_not_flooded_after_kill_switch_off(env, now):
    """Events synthesized under an engaged kill switch belong to completed
    runs; disengaging the switch must not backfill their notifications."""
    store = env["store"]
    store.set_kill_switch(True, "admin", "api", now)
    clients = {"seerr": FakeSeerr(load_fixture("reconcile", "seerr-requests.json")["results"])}
    summary = _run(env, clients, now)
    assert summary["seerr"]["recovered"] == 5
    assert store.query("SELECT * FROM notifications") == []  # suppressed

    store.set_kill_switch(False, "admin", "api", now)
    summary = _run(env, clients, now + timedelta(days=2))
    assert summary["seerr"]["recovered"] == 0
    # Strict window bound: prior-run events are not repaired into the ledger.
    assert store.query("SELECT * FROM notifications") == []


def test_tautulli_gap_marker_crash_repaired(env, monkeypatch, now):
    store = env["store"]
    rows = load_fixture("reconcile", "tautulli-history.json")["response"]["data"]["data"]
    clients = {"tautulli": FakeTautulli(rows)}
    window_start = now - timedelta(hours=24)
    marker_key = f"tautulli:reconcile.gap:{window_start.isoformat()}"

    calls = _crash_on(monkeypatch, marker_key)
    summary = _run(env, clients, now)
    assert calls["crashes"] == 1
    assert "error" in summary["tautulli"]
    assert store.event_key_exists(marker_key)  # marker stored...
    assert store.notifications_by_key(marker_key) == []  # ...but silent

    monkeypatch.undo()
    summary = _run(env, clients, now + timedelta(minutes=10))
    # Watches were recovered pre-crash; rerun recovers nothing new and
    # creates no second marker — it repairs the existing one.
    assert summary["tautulli"] == {"recovered": 0, "gap_marked": False}
    markers = store.list_events(type_="reconcile.gap")
    assert len(markers) == 1
    rows = store.notifications_by_key(marker_key)
    assert [(r["channel"], r["status"]) for r in rows] == [("media-admin", "pending")]


def test_arr_fuzzy_dedupe_preserved_and_exact_key_repaired(env, monkeypatch, now):
    """Webhook/history twin keys (fuzzy) stay untouched; reconcile's own
    exact-key rows get repaired."""
    store = env["store"]
    # Season-pack grab arrived by webhook (multi-episode key, no ledger row
    # because media.grabbed is not allowlisted -- and it is webhook-origin).
    for event in normalize("sonarr", "sonarr", load_fixture("sonarr", "grab-season-pack.json")):
        event.received_at = now
        env["correlator"].apply(event)

    records = load_fixture("reconcile", "sonarr-history.json")["records"]
    calls = _crash_on(monkeypatch, "sonarr:media.grabbed:280619:S03E01:MISSEDEP")
    summary = _run(env, {"sonarr": FakeArr(records)}, now)
    assert calls["crashes"] == 1
    assert "error" in summary["sonarr"]
    assert store.event_key_exists("sonarr:media.grabbed:280619:S03E01:MISSEDEP")

    monkeypatch.undo()
    summary = _run(env, {"sonarr": FakeArr(records)}, now + timedelta(minutes=10))
    # The delete record is the only new recovery; the crashed grab repairs
    # silently (media.grabbed is not allowlisted -> no ledger row) and the
    # season-pack twins never synthesize duplicates.
    grabbed = store.list_events(type_="media.grabbed", limit=100)
    assert len(grabbed) == 2  # webhook season pack + repaired MISSEDEP
    assert summary["sonarr"]["recovered"] == 1  # episode-file delete only
