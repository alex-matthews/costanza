"""SQLite (WAL) system of record — ADR-0002.

One shared connection serialized with an RLock (FastAPI runs sync handlers
on a thread pool; sqlite3 connections are not thread-safe). Versioned
migrations live in `migrations/*.sql` and are applied in filename order,
recorded in `schema_migrations`.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ..config import HouseholdUser, SourceConfig
from ..ids import new_id
from ..schemas import CanonicalEvent, MediaRef

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat()


def _now() -> datetime:
    return datetime.now(UTC)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


class Store:
    def __init__(self, path: Path | str):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._migrate()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -- migrations ---------------------------------------------------------

    def _migrate(self) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY)"
            )
            applied = {
                row["version"]
                for row in self._conn.execute("SELECT version FROM schema_migrations")
            }
            for sql_file in sorted(MIGRATIONS_DIR.glob("*.sql")):
                version = sql_file.stem
                if version in applied:
                    continue
                self._conn.executescript(sql_file.read_text())
                self._conn.execute(
                    "INSERT INTO schema_migrations (version) VALUES (?)", (version,)
                )

    def migrations_applied(self) -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            ).fetchall()
        return [r["version"] for r in rows]

    def ping(self) -> bool:
        with self._lock:
            self._conn.execute("SELECT 1")
        return True

    # -- generic query (stats module) ---------------------------------------

    def query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        if not sql.lstrip().upper().startswith("SELECT"):
            raise ValueError("Store.query is read-only")
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    # -- sources -------------------------------------------------------------

    def sync_sources(self, sources: list[SourceConfig]) -> None:
        with self._lock, self._conn:
            for src in sources:
                self._conn.execute(
                    """
                    INSERT INTO sources (kind, name, secret_ref, enabled)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(name) DO UPDATE
                    SET kind = excluded.kind,
                        secret_ref = excluded.secret_ref,
                        enabled = excluded.enabled
                    """,
                    (src.kind, src.name, src.secret_env, int(src.enabled)),
                )

    def source_by_name(self, name: str) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(
                "SELECT * FROM sources WHERE name = ?", (name,)
            ).fetchone()

    # -- raw events + ingest outbox -------------------------------------------

    def archive_raw(
        self,
        source_id: int,
        headers_subset: dict,
        body: str,
        received_at: datetime | None = None,
    ) -> str:
        raw_id = new_id()
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO raw_events (id, source_id, received_at, headers_subset, body_json)"
                " VALUES (?, ?, ?, ?, ?)",
                (raw_id, source_id, _iso(received_at or _now()), json.dumps(headers_subset), body),
            )
        return raw_id

    def get_raw(self, raw_id: str) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(
                "SELECT * FROM raw_events WHERE id = ?", (raw_id,)
            ).fetchone()

    def enqueue_outbox(
        self, raw_event_id: str, *, dead: bool = False, error: str | None = None
    ) -> str:
        outbox_id = new_id()
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO outbox (id, raw_event_id, state, next_attempt_at, last_error)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    outbox_id,
                    raw_event_id,
                    "dead" if dead else "pending",
                    None if dead else _iso(_now()),
                    error,
                ),
            )
        return outbox_id

    def claim_outbox_due(self, limit: int = 20, now: datetime | None = None) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(
                "SELECT * FROM outbox WHERE state = 'pending' AND next_attempt_at <= ?"
                " ORDER BY next_attempt_at LIMIT ?",
                (_iso(now or _now()), limit),
            ).fetchall()

    def outbox_done(self, outbox_id: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE outbox SET state = 'done', last_error = NULL WHERE id = ?", (outbox_id,)
            )

    def outbox_retry(self, outbox_id: str, error: str, next_attempt_at: datetime) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE outbox SET attempts = attempts + 1, last_error = ?, next_attempt_at = ?"
                " WHERE id = ?",
                (error, _iso(next_attempt_at), outbox_id),
            )

    def outbox_dead(self, outbox_id: str, error: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE outbox SET state = 'dead', attempts = attempts + 1, last_error = ?"
                " WHERE id = ?",
                (error, outbox_id),
            )

    def outbox_backlog(self) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM outbox WHERE state = 'pending'"
            ).fetchone()
        return row["n"]

    def outbox_dead_count(self) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM outbox WHERE state = 'dead'"
            ).fetchone()
        return row["n"]

    def prune(self, retention_days: int, now: datetime | None = None) -> tuple[int, int]:
        """Delete raw events older than retention and their processed outbox rows."""
        cutoff = _iso((now or _now()) - timedelta(days=retention_days))
        with self._lock, self._conn:
            done = self._conn.execute(
                "DELETE FROM outbox WHERE state = 'done' AND raw_event_id IN"
                " (SELECT id FROM raw_events WHERE received_at < ?)",
                (cutoff,),
            ).rowcount
            pruned = self._conn.execute(
                "DELETE FROM raw_events WHERE received_at < ? AND id NOT IN"
                " (SELECT raw_event_id FROM outbox)",
                (cutoff,),
            ).rowcount
        return pruned, done

    # -- media identity --------------------------------------------------------

    def find_or_create_media(self, ref: MediaRef, now: datetime | None = None) -> str:
        """Resolve a MediaRef to a media row id (tmdb > tvdb > imdb), backfilling ids."""
        kind = "series" if ref.kind in ("series", "season", "episode") else "movie"
        with self._lock, self._conn:
            row = None
            for column, value in (
                ("tmdb_id", ref.tmdb_id),
                ("tvdb_id", ref.tvdb_id),
                ("imdb_id", ref.imdb_id),
            ):
                if value is None:
                    continue
                row = self._conn.execute(
                    f"SELECT * FROM media WHERE {column} = ? AND kind = ?", (value, kind)
                ).fetchone()
                if row:
                    break
            if row is None and not any((ref.tmdb_id, ref.tvdb_id, ref.imdb_id)):
                row = self._conn.execute(
                    "SELECT * FROM media WHERE kind = ? AND title = ? AND year IS ?",
                    (kind, ref.title, ref.year),
                ).fetchone()
            if row is None:
                media_id = new_id()
                self._conn.execute(
                    "INSERT INTO media (id, tmdb_id, tvdb_id, imdb_id, kind, title, year, added_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        media_id,
                        ref.tmdb_id,
                        ref.tvdb_id,
                        ref.imdb_id,
                        kind,
                        ref.title,
                        ref.year,
                        _iso(now or _now()),
                    ),
                )
                return media_id
            updates: dict[str, object] = {}
            for column, value in (
                ("tmdb_id", ref.tmdb_id),
                ("tvdb_id", ref.tvdb_id),
                ("imdb_id", ref.imdb_id),
                ("title", ref.title),
                ("year", ref.year),
            ):
                if value is not None and row[column] is None:
                    updates[column] = value
            if updates:
                sets = ", ".join(f"{c} = ?" for c in updates)
                self._conn.execute(
                    f"UPDATE media SET {sets} WHERE id = ?", (*updates.values(), row["id"])
                )
            return row["id"]

    def get_media(self, media_id: str) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(
                "SELECT * FROM media WHERE id = ?", (media_id,)
            ).fetchone()

    # -- users + identities ------------------------------------------------------

    def sync_users(self, users: list[HouseholdUser]) -> None:
        """Upsert household members and their identity map from routing.yaml."""
        with self._lock, self._conn:
            for user in users:
                user_id = f"u:{_slug(user.display)}"
                self._conn.execute(
                    "INSERT INTO users (id, display_name, is_admin, active)"
                    " VALUES (?, ?, ?, ?)"
                    " ON CONFLICT(id) DO UPDATE SET display_name = excluded.display_name,"
                    " is_admin = excluded.is_admin, active = excluded.active",
                    (user_id, user.display, int(user.admin), int(user.active)),
                )
                for provider, external_id in user.identities.items():
                    self._conn.execute(
                        "INSERT INTO identities (user_id, provider, external_id)"
                        " VALUES (?, ?, ?)"
                        " ON CONFLICT(provider, external_id) DO UPDATE SET user_id = excluded.user_id",
                        (user_id, provider, str(external_id)),
                    )

    def resolve_identity(self, provider: str, external_id: str) -> sqlite3.Row | None:
        """Mapped household member for an observed identity, or None."""
        with self._lock:
            return self._conn.execute(
                "SELECT u.id, u.display_name FROM identities i JOIN users u ON u.id = i.user_id"
                " WHERE i.provider = ? AND i.external_id = ? AND u.active = 1",
                (provider, str(external_id)),
            ).fetchone()

    def observe_identity(self, provider: str, external_id: str) -> bool:
        """Record an unmapped external identity (user_id NULL). True if new."""
        with self._lock, self._conn:
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO identities (user_id, provider, external_id)"
                " VALUES (NULL, ?, ?)",
                (provider, str(external_id)),
            )
            return cur.rowcount > 0

    def unmapped_identities(self) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(
                "SELECT provider, external_id FROM identities WHERE user_id IS NULL"
                " ORDER BY provider, external_id"
            ).fetchall()

    def get_user(self, user_id: str) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(
                "SELECT * FROM users WHERE id = ?", (user_id,)
            ).fetchone()

    # -- events ---------------------------------------------------------------

    def insert_event(self, event: CanonicalEvent, source_id: int) -> bool:
        """Insert a canonical event; False when source_event_key already exists."""
        received = event.received_at or _now()
        occurred = event.occurred_at or received
        with self._lock, self._conn:
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO events (id, source_event_key, source_id, origin, type,"
                " occurred_at, received_at, media_id, user_id, attrs_json)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    event.id,
                    event.source_event_key,
                    source_id,
                    event.origin,
                    event.type,
                    _iso(occurred),
                    _iso(received),
                    event.media.media_id if event.media else None,
                    event.user.user_id if event.user else None,
                    json.dumps(event.attrs),
                ),
            )
            return cur.rowcount > 0

    def event_key_exists(self, source_event_key: str) -> bool:
        with self._lock:
            return (
                self._conn.execute(
                    "SELECT 1 FROM events WHERE source_event_key = ?", (source_event_key,)
                ).fetchone()
                is not None
            )

    def get_event_by_key(self, source_event_key: str) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(
                "SELECT * FROM events WHERE source_event_key = ?", (source_event_key,)
            ).fetchone()

    def event_key_like(self, pattern: str) -> bool:
        """LIKE match over source_event_keys (reconcile's fuzzy dedupe)."""
        with self._lock:
            return (
                self._conn.execute(
                    "SELECT 1 FROM events WHERE source_event_key LIKE ? LIMIT 1", (pattern,)
                ).fetchone()
                is not None
            )

    def has_event_near(
        self,
        type_: str,
        media_id: str | None,
        occurred_at: datetime,
        window_hours: int = 24,
    ) -> bool:
        """Any event of this type for this media within +/- window (reconcile guard)."""
        if media_id is None:
            return False
        lo = _iso(occurred_at - timedelta(hours=window_hours))
        hi = _iso(occurred_at + timedelta(hours=window_hours))
        with self._lock:
            return (
                self._conn.execute(
                    "SELECT 1 FROM events WHERE type = ? AND media_id = ?"
                    " AND occurred_at BETWEEN ? AND ? LIMIT 1",
                    (type_, media_id, lo, hi),
                ).fetchone()
                is not None
            )

    def list_events(
        self,
        *,
        type_: str | None = None,
        since: datetime | None = None,
        user_id: str | None = None,
        media_id: str | None = None,
        limit: int = 200,
    ) -> list[sqlite3.Row]:
        clauses, params = [], []
        if type_:
            clauses.append("type = ?")
            params.append(type_)
        if since:
            clauses.append("occurred_at >= ?")
            params.append(_iso(since))
        if user_id:
            clauses.append("user_id = ?")
            params.append(user_id)
        if media_id:
            clauses.append("media_id = ?")
            params.append(media_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._lock:
            return self._conn.execute(
                f"SELECT * FROM events {where} ORDER BY occurred_at DESC LIMIT ?",
                (*params, limit),
            ).fetchall()

    def events_for_media(self, media_id: str) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(
                "SELECT * FROM events WHERE media_id = ? ORDER BY occurred_at", (media_id,)
            ).fetchall()

    # -- request chains -----------------------------------------------------------

    def chain_by_request_id(self, seerr_request_id: str) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(
                "SELECT * FROM request_chains WHERE seerr_request_id = ?",
                (str(seerr_request_id),),
            ).fetchone()

    def open_chain_for_media(self, media_id: str) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(
                "SELECT * FROM request_chains WHERE media_id = ? AND closed_at IS NULL"
                " ORDER BY opened_at DESC LIMIT 1",
                (media_id,),
            ).fetchone()

    def create_chain(
        self,
        *,
        media_id: str | None,
        seerr_request_id: str | None,
        requested_by: str | None,
        state: str,
        opened_at: datetime,
        closed_at: datetime | None = None,
    ) -> str:
        chain_id = new_id()
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO request_chains (id, media_id, seerr_request_id, requested_by,"
                " state, opened_at, closed_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    chain_id,
                    media_id,
                    str(seerr_request_id) if seerr_request_id is not None else None,
                    requested_by,
                    state,
                    _iso(opened_at),
                    _iso(closed_at) if closed_at else None,
                ),
            )
        return chain_id

    def update_chain(
        self,
        chain_id: str,
        *,
        state: str | None = None,
        closed_at: datetime | None = None,
        media_id: str | None = None,
        requested_by: str | None = None,
    ) -> None:
        updates: dict[str, object] = {}
        if state is not None:
            updates["state"] = state
        if closed_at is not None:
            updates["closed_at"] = _iso(closed_at)
        if media_id is not None:
            updates["media_id"] = media_id
        if requested_by is not None:
            updates["requested_by"] = requested_by
        if not updates:
            return
        sets = ", ".join(f"{c} = ?" for c in updates)
        with self._lock, self._conn:
            self._conn.execute(
                f"UPDATE request_chains SET {sets} WHERE id = ?", (*updates.values(), chain_id)
            )

    def chains_for_media(self, media_id: str) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(
                "SELECT * FROM request_chains WHERE media_id = ? ORDER BY opened_at",
                (media_id,),
            ).fetchall()

    def open_chains(self, opened_before: datetime | None = None) -> list[sqlite3.Row]:
        clause, params = "", []
        if opened_before:
            clause = "AND opened_at < ?"
            params.append(_iso(opened_before))
        with self._lock:
            return self._conn.execute(
                f"SELECT * FROM request_chains WHERE closed_at IS NULL {clause}"
                " ORDER BY opened_at",
                params,
            ).fetchall()

    # -- notifications (ledger + outbound outbox) -----------------------------------

    def enqueue_notification(
        self, event_key: str, channel: str, rendered_hash: str, now: datetime | None = None
    ) -> bool:
        """Create a pending row; False when (event_key, channel) already exists."""
        with self._lock, self._conn:
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO notifications"
                " (id, event_key, channel, rendered_hash, status, next_attempt_at)"
                " VALUES (?, ?, ?, ?, 'pending', ?)",
                (new_id(), event_key, channel, rendered_hash, _iso(now or _now())),
            )
            return cur.rowcount > 0

    def claim_notifications_due(
        self, limit: int = 20, now: datetime | None = None
    ) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(
                "SELECT * FROM notifications WHERE status IN ('pending', 'failed')"
                " AND next_attempt_at <= ? ORDER BY next_attempt_at LIMIT ?",
                (_iso(now or _now()), limit),
            ).fetchall()

    def notification_sent(self, notification_id: str, now: datetime | None = None) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE notifications SET status = 'sent', attempts = attempts + 1,"
                " sent_at = ?, last_error = NULL WHERE id = ?",
                (_iso(now or _now()), notification_id),
            )

    def notification_retry(
        self, notification_id: str, error: str, next_attempt_at: datetime
    ) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE notifications SET status = 'failed', attempts = attempts + 1,"
                " last_error = ?, next_attempt_at = ? WHERE id = ?",
                (error, _iso(next_attempt_at), notification_id),
            )

    def notification_defer(self, notification_id: str, next_attempt_at: datetime) -> None:
        """Push back without burning an attempt (kill switch / rate limit)."""
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE notifications SET next_attempt_at = ? WHERE id = ?",
                (_iso(next_attempt_at), notification_id),
            )

    def notification_dead(self, notification_id: str, error: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE notifications SET status = 'dead', attempts = attempts + 1,"
                " last_error = ? WHERE id = ?",
                (error, notification_id),
            )

    def notifications_by_key(self, event_key: str) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(
                "SELECT * FROM notifications WHERE event_key = ? ORDER BY channel", (event_key,)
            ).fetchall()

    def notification_counts(self) -> dict[str, int]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT status, COUNT(*) AS n FROM notifications GROUP BY status"
            ).fetchall()
        return {r["status"]: r["n"] for r in rows}

    def dead_notifications(self, limit: int = 20) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(
                "SELECT * FROM notifications WHERE status = 'dead' ORDER BY next_attempt_at"
                " LIMIT ?",
                (limit,),
            ).fetchall()

    # -- job cursors -------------------------------------------------------------

    def get_cursor(self, job: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT cursor_json FROM job_cursors WHERE job = ?", (job,)
            ).fetchone()
        return json.loads(row["cursor_json"]) if row else None

    def set_cursor(self, job: str, cursor: dict, now: datetime | None = None) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO job_cursors (job, cursor_json, updated_at) VALUES (?, ?, ?)"
                " ON CONFLICT(job) DO UPDATE SET cursor_json = excluded.cursor_json,"
                " updated_at = excluded.updated_at",
                (job, json.dumps(cursor), _iso(now or _now())),
            )

    # -- kill switch ----------------------------------------------------------------

    def kill_switch_state(self) -> dict:
        """Latest audit row; defaults to engaged (safe: silent until turned off)."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM kill_switch_audit ORDER BY id DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return {"engaged": True, "set_by": "default", "via": "default", "set_at": None}
        return {
            "engaged": bool(row["engaged"]),
            "set_by": row["set_by"],
            "via": row["via"],
            "set_at": row["set_at"],
        }

    def set_kill_switch(
        self, engaged: bool, set_by: str, via: str = "api", now: datetime | None = None
    ) -> dict:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO kill_switch_audit (engaged, set_by, via, set_at)"
                " VALUES (?, ?, ?, ?)",
                (int(engaged), set_by, via, _iso(now or _now())),
            )
        return self.kill_switch_state()
