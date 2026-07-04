"""Read-only REST API + ops endpoints.

Static bearer token on /api/* (single household token). The ONLY write
endpoint in v1 is POST /api/v1/admin/kill-switch — a fire alarm needs to
be faster than a redeploy; the toggle is persisted and audited, and the
COSTANZA_KILL_SWITCH env override wins regardless (handoff.md).
"""

from __future__ import annotations

import hmac
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel

from .. import stats
from ..config import Config
from ..jobs.digest import DEFAULT_PERIOD, build_digest_data
from ..notify.limits import KillSwitch
from ..notify.render import render_digest
from ..schemas import EVENT_TYPES, utcnow
from ..store import Store


def _bearer_guard(config: Config):
    token = config.settings.api_bearer_token

    def guard(request: Request) -> None:
        auth = request.headers.get("authorization", "")
        presented = auth[7:] if auth.lower().startswith("bearer ") else ""
        if not token or not presented or not hmac.compare_digest(token, presented):
            raise HTTPException(status_code=401, detail="invalid or missing bearer token")

    return guard


def _event_dict(store: Store, row) -> dict:
    source = store.source_by_id(row["source_id"])
    return {
        "id": row["id"],
        "source": source["name"] if source else row["source_id"],
        "source_event_key": row["source_event_key"],
        "origin": row["origin"],
        "type": row["type"],
        "occurred_at": row["occurred_at"],
        "received_at": row["received_at"],
        "media_id": row["media_id"],
        "user_id": row["user_id"],
        "attrs": json.loads(row["attrs_json"]),
    }


def _chain_dict(row) -> dict:
    return {
        "id": row["id"],
        "media_id": row["media_id"],
        "seerr_request_id": row["seerr_request_id"],
        "requested_by": row["requested_by"],
        "state": row["state"],
        "opened_at": row["opened_at"],
        "closed_at": row["closed_at"],
    }


class KillSwitchBody(BaseModel):
    engaged: bool
    set_by: str = "api"


def build_api_router(config: Config, store: Store, kill: KillSwitch) -> APIRouter:
    router = APIRouter(
        prefix="/api/v1", dependencies=[Depends(_bearer_guard(config))]
    )

    @router.get("/media/{media_id}/timeline")
    def timeline(media_id: str) -> dict:
        media = store.get_media(media_id)
        if media is None:
            raise HTTPException(status_code=404, detail="unknown media id")
        return {
            "media": dict(media),
            "chains": [_chain_dict(c) for c in store.chains_for_media(media_id)],
            "events": [_event_dict(store, e) for e in store.events_for_media(media_id)],
        }

    @router.get("/events")
    def events(
        type: str | None = Query(default=None),  # noqa: A002 — spec'd query param name
        since: datetime | None = Query(default=None),
        user: str | None = Query(default=None),
        limit: int = Query(default=200, le=1000),
    ) -> dict:
        if type is not None and type not in EVENT_TYPES:
            raise HTTPException(status_code=422, detail=f"unknown event type {type!r}")
        rows = store.list_events(type_=type, since=since, user_id=user, limit=limit)
        return {"events": [_event_dict(store, r) for r in rows]}

    @router.get("/stats/requests")
    def stats_requests() -> dict:
        return {"per_user": stats.requests_per_user(store)}

    @router.get("/stats/watch")
    def stats_watch() -> dict:
        return {"per_user": stats.watch_per_user(store)}

    @router.get("/digest/preview")
    def digest_preview() -> dict:
        until = utcnow()
        cursor = store.get_cursor("digest") or {}
        last_end = cursor.get("period_end_at")
        since = datetime.fromisoformat(last_end) if last_end else until - DEFAULT_PERIOD
        data = build_digest_data(store, since, until)
        return {"data": data, "rendered": render_digest(data).model_dump(mode="json")}

    @router.get("/admin/kill-switch")
    def kill_switch_get() -> dict:
        return kill.state()

    @router.post("/admin/kill-switch")
    def kill_switch_post(body: KillSwitchBody) -> dict:
        return kill.set(body.engaged, body.set_by, via="api")

    @router.get("/admin/diagnostics")
    def diagnostics() -> dict:
        """Dead-letter visibility: invalid payloads + undeliverable messages."""
        dead_outbox = store.query(
            "SELECT o.id, o.last_error, o.attempts, r.received_at, s.name AS source"
            " FROM outbox o JOIN raw_events r ON r.id = o.raw_event_id"
            " JOIN sources s ON s.id = r.source_id WHERE o.state = 'dead'"
            " ORDER BY r.received_at DESC LIMIT 50"
        )
        return {
            "outbox_backlog": store.outbox_backlog(),
            "dead_outbox": [dict(r) for r in dead_outbox],
            "dead_notifications": [dict(r) for r in store.dead_notifications()],
            "unmapped_identities": [dict(r) for r in store.unmapped_identities()],
        }

    return router


def build_ops_router(config: Config, store: Store) -> APIRouter:
    """Unauthenticated probes + metrics (cluster-internal)."""
    router = APIRouter()

    @router.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    @router.get("/readyz")
    def readyz() -> dict:
        # DB reachable + config loaded. Deliberately NOT Discord: a dead bot
        # must not restart-loop ingestion (handoff.md).
        store.ping()
        assert config.routing is not None
        return {"status": "ready"}

    @router.get("/metrics")
    def metrics() -> Response:
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return router
