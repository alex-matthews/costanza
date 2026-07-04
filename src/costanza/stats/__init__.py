"""Aggregate queries over the store, backing the read API and the digest."""

from __future__ import annotations

from datetime import UTC, datetime

from ..store import Store


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat()


def _label(row) -> str:
    label = row["title"] or "(unknown)"
    if row["year"]:
        label = f"{label} ({row['year']})"
    return label


def new_arrivals(store: Store, since: datetime, until: datetime) -> list[dict]:
    rows = store.query(
        """
        SELECT DISTINCT m.id, m.title, m.year, m.kind
        FROM events e JOIN media m ON m.id = e.media_id
        WHERE e.type = 'media.imported' AND e.occurred_at >= ? AND e.occurred_at < ?
        ORDER BY m.title
        """,
        (_iso(since), _iso(until)),
    )
    return [{"media_id": r["id"], "label": _label(r), "kind": r["kind"]} for r in rows]


def requests_summary(store: Store, since: datetime, until: datetime) -> dict:
    counts = {
        "opened": store.query(
            "SELECT COUNT(*) AS n FROM request_chains WHERE opened_at >= ? AND opened_at < ?",
            (_iso(since), _iso(until)),
        )[0]["n"],
        "available": store.query(
            "SELECT COUNT(*) AS n FROM request_chains"
            " WHERE state IN ('available', 'partially_available')"
            " AND closed_at >= ? AND closed_at < ?",
            (_iso(since), _iso(until)),
        )[0]["n"],
        "declined": store.query(
            "SELECT COUNT(*) AS n FROM request_chains"
            " WHERE state = 'declined' AND closed_at >= ? AND closed_at < ?",
            (_iso(since), _iso(until)),
        )[0]["n"],
    }
    stale_rows = store.query(
        """
        SELECT c.opened_at, m.title, m.year
        FROM request_chains c LEFT JOIN media m ON m.id = c.media_id
        WHERE c.closed_at IS NULL AND c.opened_at < ?
        ORDER BY c.opened_at
        """,
        (_iso(since),),
    )
    counts["stale"] = [
        (_label(r) if r["title"] else "(unknown)") + f" — since {r['opened_at'][:10]}"
        for r in stale_rows
    ]
    return counts


def watch_summary(store: Store, since: datetime, until: datetime) -> dict:
    top = store.query(
        """
        SELECT m.title, m.year, COUNT(*) AS n
        FROM events e JOIN media m ON m.id = e.media_id
        WHERE e.type = 'watch.completed' AND e.occurred_at >= ? AND e.occurred_at < ?
        GROUP BY m.id ORDER BY n DESC, m.title LIMIT 10
        """,
        (_iso(since), _iso(until)),
    )
    per_user = store.query(
        """
        SELECT u.display_name, COUNT(*) AS n
        FROM events e JOIN users u ON u.id = e.user_id
        WHERE e.type = 'watch.completed' AND e.occurred_at >= ? AND e.occurred_at < ?
        GROUP BY u.id ORDER BY n DESC
        """,
        (_iso(since), _iso(until)),
    )
    return {
        "top": [{"label": _label(r), "count": r["n"]} for r in top],
        "per_user": [{"display": r["display_name"], "count": r["n"]} for r in per_user],
    }


def ops_summary(store: Store, since: datetime, until: datetime) -> dict:
    def count(sql: str, params: tuple = ()) -> int:
        return store.query(sql, params)[0]["n"]

    return {
        "gaps": count(
            "SELECT COUNT(*) AS n FROM events WHERE type = 'reconcile.gap'"
            " AND occurred_at >= ? AND occurred_at < ?",
            (_iso(since), _iso(until)),
        ),
        "unknown_events": count(
            "SELECT COUNT(*) AS n FROM events WHERE type = 'source.unknown'"
            " AND occurred_at >= ? AND occurred_at < ?",
            (_iso(since), _iso(until)),
        ),
        "dead_notifications": count(
            "SELECT COUNT(*) AS n FROM notifications WHERE status = 'dead'"
        ),
        "dead_outbox": store.outbox_dead_count(),
        "unmapped_identities": [
            f"{r['provider']}:{r['external_id']}" for r in store.unmapped_identities()
        ],
    }


def requests_per_user(store: Store) -> list[dict]:
    """Requests made vs available vs watched, per household member."""
    rows = store.query(
        """
        SELECT
            COALESCE(u.display_name, c.requested_by, '(unmapped)') AS display,
            COUNT(*) AS made,
            SUM(CASE WHEN c.state IN ('available', 'partially_available')
                THEN 1 ELSE 0 END) AS available,
            SUM(CASE WHEN EXISTS (
                SELECT 1 FROM events w
                WHERE w.media_id = c.media_id AND w.type = 'watch.completed'
            ) THEN 1 ELSE 0 END) AS watched
        FROM request_chains c LEFT JOIN users u ON u.id = c.requested_by
        GROUP BY display ORDER BY made DESC
        """
    )
    return [
        {
            "user": r["display"],
            "made": r["made"],
            "available": r["available"] or 0,
            "watched": r["watched"] or 0,
        }
        for r in rows
    ]


def watch_per_user(store: Store) -> list[dict]:
    rows = store.query(
        """
        SELECT u.display_name, COUNT(*) AS completions,
               COUNT(DISTINCT e.media_id) AS titles,
               SUM(CASE WHEN m.kind = 'movie' THEN 1 ELSE 0 END) AS movies,
               SUM(CASE WHEN m.kind = 'series' THEN 1 ELSE 0 END) AS episodes
        FROM events e
        JOIN users u ON u.id = e.user_id
        LEFT JOIN media m ON m.id = e.media_id
        WHERE e.type = 'watch.completed'
        GROUP BY u.id ORDER BY completions DESC
        """
    )
    return [
        {
            "user": r["display_name"],
            "completions": r["completions"],
            "titles": r["titles"],
            "movies": r["movies"] or 0,
            "episodes": r["episodes"] or 0,
        }
        for r in rows
    ]
