"""Inbound webhook endpoint: verify -> archive raw -> outbox -> 202.

Hard rule (build prompt constraint 6): after source auth and body-size
checks pass, the raw payload is ALWAYS archived and the response is ALWAYS
202. Invalid JSON becomes a dead outbox item surfaced in admin diagnostics,
never a source-facing 4xx/5xx that could create a retry storm. Nothing on
the request path parses beyond JSON validity.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Request, Response

from .. import metrics
from ..logging import get_logger
from ..store import Store
from .sources import SourceRegistry

log = get_logger(__name__)

# Small allowlist of request headers worth archiving for debugging.
_HEADERS_SUBSET = ("content-type", "user-agent", "x-request-id", "content-length")

TOKEN_HEADER = "x-webhook-token"


def _presented_token(request: Request) -> str | None:
    token = request.headers.get(TOKEN_HEADER)
    if token:
        return token
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:]
    return None


def build_ingest_router(
    registry: SourceRegistry, store: Store, body_max_bytes: int
) -> APIRouter:
    router = APIRouter()

    @router.post("/webhooks/{source_name}")
    async def receive_webhook(source_name: str, request: Request) -> Response:
        source = registry.get(source_name)
        if source is None:
            metrics.WEBHOOK_REJECTED.labels(reason="unknown_source").inc()
            return Response(status_code=404)

        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > body_max_bytes:
            metrics.WEBHOOK_REJECTED.labels(reason="oversize").inc()
            return Response(status_code=413)

        if not SourceRegistry.authenticate(source, _presented_token(request)):
            metrics.WEBHOOK_AUTH_FAILURES.labels(source=source_name).inc()
            log.warning("webhook auth failure", source=source_name)
            return Response(status_code=401)

        body = await request.body()
        if len(body) > body_max_bytes:
            metrics.WEBHOOK_REJECTED.labels(reason="oversize").inc()
            return Response(status_code=413)

        # Auth + size passed: from here on we archive and 202, no matter what.
        source_row = store.source_by_name(source_name)
        headers_subset = {
            k: v for k, v in request.headers.items() if k.lower() in _HEADERS_SUBSET
        }
        raw_id = store.archive_raw(source_row["id"], headers_subset, body.decode(errors="replace"))

        try:
            json.loads(body)
        except (ValueError, UnicodeDecodeError) as exc:
            store.enqueue_outbox(raw_id, dead=True, error=f"invalid_json: {exc}")
            log.warning("webhook body is not JSON", source=source_name, raw_event_id=raw_id)
        else:
            store.enqueue_outbox(raw_id)

        metrics.WEBHOOKS_RECEIVED.labels(source=source_name).inc()
        return Response(status_code=202, content='{"status":"accepted"}',
                        media_type="application/json")

    return router
