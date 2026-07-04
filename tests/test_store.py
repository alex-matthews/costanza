from datetime import timedelta

from costanza.config import SourceConfig
from costanza.schemas import CanonicalEvent, MediaRef, UserRef
from costanza.store import Store


def _source_id(store, routing) -> int:
    store.sync_sources(routing.sources)
    return store.source_by_name("radarr")["id"]


def test_migrations_apply_once_and_are_idempotent(tmp_path):
    store = Store(tmp_path / "m.db")
    assert store.migrations_applied() == ["0001_initial"]
    # Re-opening must not re-apply.
    store.close()
    store = Store(tmp_path / "m.db")
    assert store.migrations_applied() == ["0001_initial"]
    assert store.ping()


def test_sync_sources_upserts(store, routing):
    store.sync_sources(routing.sources)
    row = store.source_by_name("radarr")
    assert row["kind"] == "radarr"
    assert row["secret_ref"] == "WEBHOOK_SECRET__RADARR"
    assert row["enabled"] == 1
    # Config change: disable, re-sync.
    updated = [
        s if s.name != "radarr" else SourceConfig(name="radarr", kind="radarr", enabled=False)
        for s in routing.sources
    ]
    store.sync_sources(updated)
    assert store.source_by_name("radarr")["enabled"] == 0


def test_event_insert_is_idempotent_on_source_event_key(store, routing, now):
    sid = _source_id(store, routing)
    event = CanonicalEvent(
        source="radarr",
        source_event_key="radarr:media.imported:157336:abc",
        type="media.imported",
        occurred_at=now,
        received_at=now,
    )
    assert store.insert_event(event, sid) is True
    dup = event.model_copy(update={"id": "different-id"})
    assert store.insert_event(dup, sid) is False
    assert store.event_key_exists("radarr:media.imported:157336:abc")


def test_media_identity_dedupes_across_id_spaces(store):
    a = store.find_or_create_media(MediaRef(tmdb_id=157336, kind="movie", title="Arrival"))
    # Same tmdb id -> same row; imdb id gets backfilled.
    b = store.find_or_create_media(
        MediaRef(tmdb_id=157336, imdb_id="tt2543164", kind="movie", year=2016)
    )
    assert a == b
    row = store.get_media(a)
    assert row["imdb_id"] == "tt2543164"
    assert row["year"] == 2016
    # Now findable by imdb alone.
    c = store.find_or_create_media(MediaRef(imdb_id="tt2543164", kind="movie"))
    assert c == a
    # A series with the same tmdb id is a different row (kind-scoped).
    d = store.find_or_create_media(MediaRef(tmdb_id=157336, kind="episode", title="Show"))
    assert d != a
    assert store.get_media(d)["kind"] == "series"


def test_identity_map_resolution_and_unmapped_observation(store, routing):
    store.sync_users(routing.users)
    hit = store.resolve_identity("seerr", "alice")
    assert hit["display_name"] == "Alice"
    assert store.resolve_identity("plex", "stranger") is None
    assert store.observe_identity("plex", "stranger") is True
    assert store.observe_identity("plex", "stranger") is False  # already observed
    unmapped = store.unmapped_identities()
    assert [(r["provider"], r["external_id"]) for r in unmapped] == [("plex", "stranger")]
    # Mapping the user later claims the observed identity row.
    users = routing.users
    users[1].identities["plex"] = "stranger"
    store.sync_users(users)
    assert store.resolve_identity("plex", "stranger")["display_name"] == "Bob"
    assert store.unmapped_identities() == []


def test_notification_unique_event_key_channel(store, now):
    assert store.enqueue_notification("k1", "media-feed", "h", now) is True
    assert store.enqueue_notification("k1", "media-feed", "h", now) is False
    assert store.enqueue_notification("k1", "media-admin", "h", now) is True
    due = store.claim_notifications_due(now=now)
    assert len(due) == 2


def test_notification_lifecycle(store, now):
    store.enqueue_notification("k1", "media-feed", "h", now)
    row = store.claim_notifications_due(now=now)[0]
    store.notification_retry(row["id"], "boom", now + timedelta(seconds=30))
    assert store.claim_notifications_due(now=now) == []
    retryable = store.claim_notifications_due(now=now + timedelta(seconds=31))
    assert retryable[0]["status"] == "failed"
    assert retryable[0]["attempts"] == 1
    store.notification_sent(row["id"], now)
    assert store.notification_counts() == {"sent": 1}


def test_outbox_claim_and_prune(store, routing, now):
    sid = _source_id(store, routing)
    raw_id = store.archive_raw(sid, {"content-type": "application/json"}, "{}", now)
    store.enqueue_outbox(raw_id)
    assert store.outbox_backlog() == 1
    row = store.claim_outbox_due()[0]
    assert row["raw_event_id"] == raw_id
    store.outbox_done(row["id"])
    assert store.outbox_backlog() == 0
    # Dead outbox rows (e.g. invalid JSON) count separately for diagnostics.
    dead_raw = store.archive_raw(sid, {}, "not json", now)
    store.enqueue_outbox(dead_raw, dead=True, error="invalid_json")
    assert store.outbox_backlog() == 0
    assert store.outbox_dead_count() == 1
    # Retry/backoff: retried rows stay pending until next_attempt_at.
    raw2 = store.archive_raw(sid, {}, "{}", now)
    ob2 = store.enqueue_outbox(raw2)
    store.outbox_retry(ob2, "boom", now + timedelta(seconds=60))
    assert store.claim_outbox_due(now=now) == []
    due = store.claim_outbox_due(now=now + timedelta(seconds=61))
    assert due[0]["attempts"] == 1


def test_kill_switch_defaults_engaged_and_audits(store, now):
    state = store.kill_switch_state()
    assert state["engaged"] is True
    assert state["set_by"] == "default"
    state = store.set_kill_switch(False, "alice", "api", now)
    assert state["engaged"] is False
    assert state["set_by"] == "alice"
    state = store.set_kill_switch(True, "env", "env", now)
    assert state["engaged"] is True


def test_chains(store, now):
    media_id = store.find_or_create_media(MediaRef(tmdb_id=1, kind="movie", title="X"))
    chain_id = store.create_chain(
        media_id=media_id,
        seerr_request_id="RQ-1",
        requested_by="u:alice",
        state="requested",
        opened_at=now,
    )
    assert store.chain_by_request_id("RQ-1")["state"] == "requested"
    store.update_chain(chain_id, state="available", closed_at=now + timedelta(days=1))
    row = store.chains_for_media(media_id)[0]
    assert row["state"] == "available"
    assert row["closed_at"] is not None
    assert store.open_chains() == []


def test_cursors(store, now):
    assert store.get_cursor("digest") is None
    store.set_cursor("digest", {"since": "2026-01-01"}, now)
    assert store.get_cursor("digest") == {"since": "2026-01-01"}
    store.set_cursor("digest", {"since": "2026-02-01"}, now)
    assert store.get_cursor("digest") == {"since": "2026-02-01"}


def test_event_user_attrs_roundtrip(store, routing, now):
    sid = _source_id(store, routing)
    store.sync_users(routing.users)
    media_id = store.find_or_create_media(MediaRef(tmdb_id=2, kind="movie", title="Y"))
    event = CanonicalEvent(
        source="radarr",
        source_event_key="k-attrs",
        type="media.imported",
        occurred_at=now,
        received_at=now,
        media=MediaRef(media_id=media_id, tmdb_id=2, kind="movie"),
        user=UserRef(user_id="u:alice", display="Alice"),
        attrs={"quality": "WEBDL-1080p"},
    )
    store.insert_event(event, sid)
    row = store.get_event_by_key("k-attrs")
    assert row["media_id"] == media_id
    assert row["user_id"] == "u:alice"
    assert row["attrs_json"] == '{"quality": "WEBDL-1080p"}'


def test_store_query_is_read_only(store):
    import pytest

    with pytest.raises(ValueError):
        store.query("DELETE FROM events")


def test_prune_removes_old_raw_and_done_outbox(store, routing, now):
    sid = _source_id(store, routing)
    old = now - timedelta(days=31)
    raw_id = store.archive_raw(sid, {}, "{}", old)
    ob = store.enqueue_outbox(raw_id)
    store.outbox_done(ob)
    fresh = store.archive_raw(sid, {}, "{}", now)
    pruned, done = store.prune(30, now)
    assert pruned == 1
    assert done == 1
    assert store.get_raw(raw_id) is None
    assert store.get_raw(fresh) is not None


def test_config_roundtrip(tmp_path, routing):
    import yaml

    from costanza.config import load_routing

    path = tmp_path / "routing.yaml"
    path.write_text(yaml.safe_dump(routing.model_dump(mode="json")))
    loaded = load_routing(path)
    assert [s.name for s in loaded.sources] == ["seerr", "radarr", "sonarr", "tautulli"]
    assert loaded.source("radarr").secret_env == "WEBHOOK_SECRET__RADARR"
    assert loaded.source("nope") is None


def test_config_rejects_unknown_channel(tmp_path):
    import pytest
    import yaml

    from costanza.config import load_routing

    path = tmp_path / "bad.yaml"
    path.write_text(
        yaml.safe_dump(
            {"rules": [{"types": ["request.available"], "channel": "ghost"}], "channels": {}}
        )
    )
    with pytest.raises(ValueError):
        load_routing(path)


def test_config_missing_file_fails_fast(tmp_path):
    import pytest

    from costanza.config import load_routing

    with pytest.raises(FileNotFoundError):
        load_routing(tmp_path / "missing.yaml")
