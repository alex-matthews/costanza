-- Costanza v1 initial schema (handoff.md data model, verbatim tables).
-- Timestamps are ISO-8601 UTC strings.

CREATE TABLE sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    name TEXT NOT NULL UNIQUE,
    secret_ref TEXT,
    enabled INTEGER NOT NULL DEFAULT 1
);

-- Raw webhook archive, pruned at raw_retention_days (default 30d, OQ-7).
CREATE TABLE raw_events (
    id TEXT PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    received_at TEXT NOT NULL,
    headers_subset TEXT NOT NULL,
    body_json TEXT NOT NULL
);
CREATE INDEX idx_raw_events_received ON raw_events(received_at);

CREATE TABLE media (
    id TEXT PRIMARY KEY,
    tmdb_id INTEGER,
    tvdb_id INTEGER,
    imdb_id TEXT,
    kind TEXT NOT NULL,
    title TEXT,
    year INTEGER,
    added_at TEXT NOT NULL
);
CREATE INDEX idx_media_tmdb ON media(tmdb_id);
CREATE INDEX idx_media_tvdb ON media(tvdb_id);
CREATE INDEX idx_media_imdb ON media(imdb_id);

CREATE TABLE users (
    id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1
);

-- user_id NULL = observed-but-unmapped external identity (identity_sync flags these).
CREATE TABLE identities (
    user_id TEXT REFERENCES users(id),
    provider TEXT NOT NULL CHECK (provider IN ('seerr', 'plex', 'tautulli', 'discord')),
    external_id TEXT NOT NULL,
    UNIQUE (provider, external_id)
);

CREATE TABLE events (
    id TEXT PRIMARY KEY,
    source_event_key TEXT NOT NULL UNIQUE,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    origin TEXT NOT NULL CHECK (origin IN ('webhook', 'reconcile', 'manual')),
    type TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    received_at TEXT NOT NULL,
    media_id TEXT REFERENCES media(id),
    user_id TEXT REFERENCES users(id),
    attrs_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX idx_events_media ON events(media_id, occurred_at);
CREATE INDEX idx_events_type ON events(type, occurred_at);
CREATE INDEX idx_events_occurred ON events(occurred_at);

-- Timeline spine: one chain per Seerr request lifecycle.
CREATE TABLE request_chains (
    id TEXT PRIMARY KEY,
    media_id TEXT REFERENCES media(id),
    seerr_request_id TEXT,
    requested_by TEXT,
    state TEXT NOT NULL,
    opened_at TEXT NOT NULL,
    closed_at TEXT
);
CREATE UNIQUE INDEX idx_chains_seerr_request ON request_chains(seerr_request_id)
    WHERE seerr_request_id IS NOT NULL;
CREATE INDEX idx_chains_media ON request_chains(media_id);

-- Doubles as ledger (dedupe/audit) AND outbound outbox (handoff.md).
CREATE TABLE notifications (
    id TEXT PRIMARY KEY,
    event_key TEXT NOT NULL,
    channel TEXT NOT NULL,
    rendered_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'sent', 'failed', 'dead')),
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT,
    last_error TEXT,
    sent_at TEXT,
    UNIQUE (event_key, channel)
);
CREATE INDEX idx_notifications_status ON notifications(status, next_attempt_at);

-- Empty in v1; reactions land here in v1.x. No writer exists in this codebase.
CREATE TABLE signals (
    id TEXT PRIMARY KEY,
    user_id TEXT REFERENCES users(id),
    media_id TEXT REFERENCES media(id),
    kind TEXT NOT NULL,
    value TEXT,
    at TEXT NOT NULL
);

CREATE TABLE job_cursors (
    job TEXT PRIMARY KEY,
    cursor_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Ingest work queue: raw webhook -> normalize/correlate off the request path.
CREATE TABLE outbox (
    id TEXT PRIMARY KEY,
    raw_event_id TEXT NOT NULL REFERENCES raw_events(id),
    state TEXT NOT NULL DEFAULT 'pending'
        CHECK (state IN ('pending', 'done', 'dead')),
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT,
    last_error TEXT
);
CREATE INDEX idx_outbox_state ON outbox(state, next_attempt_at);

-- Kill-switch persistence + audit (handoff: "persisted, audited").
-- Not in the handoff table list, which gives the toggle no home; recorded
-- as a deviation in docs/build-notes.md.
CREATE TABLE kill_switch_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    engaged INTEGER NOT NULL,
    set_by TEXT NOT NULL,
    via TEXT NOT NULL,
    set_at TEXT NOT NULL
);
