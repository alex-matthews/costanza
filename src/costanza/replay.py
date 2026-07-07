"""`costanza replay`: feed recorded fixtures at a real running instance
against a scratch DB, end to end, and assert the outcomes the design
promises — correct per-title timeline and exactly-once notifications.

Every payload is POSTed twice (simulating source retries / a relay tee):
the canonical event count and the notification ledger must not change.
"""

from __future__ import annotations

import json
import os
import socket
import tempfile
import threading
import time
from pathlib import Path

import httpx
import uvicorn
import yaml

FIXTURES = Path(__file__).parent.parent.parent / "fixtures"

SECRET = "replay-secret"
TOKEN = "replay-token"

_ROUTING = {
    "sources": [
        {"name": "seerr", "kind": "seerr"},
        {"name": "radarr", "kind": "radarr"},
        {"name": "sonarr", "kind": "sonarr"},
        {"name": "tautulli", "kind": "tautulli"},
    ],
    "channels": {
        "media-feed": {"discord_channel_id": None},
        "media-digest": {"discord_channel_id": None},
        "media-admin": {"discord_channel_id": None},
    },
    "rules": [
        {"types": ["request.approved", "request.available"], "channel": "media-feed"},
        {"types": ["health.issue", "reconcile.gap"], "channel": "media-admin"},
    ],
    "admin_channel": "media-admin",
    "users": [
        {
            "display": "Alice",
            "admin": True,
            "identities": {"seerr": "alice", "plex": "alice", "tautulli": "12"},
        }
    ],
}

# The Arrival story: request -> grab -> import -> available -> watched.
_STORY: list[tuple[str, str | None, dict | None]] = [
    ("seerr", "request-auto-approved.json", None),
    ("radarr", "grab.json", None),
    ("radarr", "download-new.json", None),
    (
        "seerr",
        "request-available.json",
        {
            "subject": "Arrival (2016)",
            "media": {"media_type": "movie", "tmdbId": "329865", "status": "AVAILABLE"},
            "request": {"request_id": "RQ-3001", "requestedBy_username": "alice"},
        },
    ),
    ("tautulli", "watched-movie.json", None),
]

_EXPECTED_TIMELINE = [
    "request.approved",
    "media.grabbed",
    "media.imported",
    "request.available",
    "watch.completed",
]
# Allowlisted: the approval and the availability -> exactly one row each.
_EXPECTED_NOTIFICATIONS = {
    ("seerr:request.approved:RQ-3001", "media-feed"),
    ("seerr:request.available:RQ-3001:AVAILABLE", "media-feed"),
}


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _check(label: str, ok: bool, detail: str = "") -> bool:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f" — {detail}" if detail else ""))
    return ok


def run_replay() -> int:
    scratch = Path(tempfile.mkdtemp(prefix="costanza-replay-"))
    routing_path = scratch / "routing.yaml"
    routing_path.write_text(yaml.safe_dump(_ROUTING))

    env = {
        "COSTANZA_DB_PATH": str(scratch / "replay.db"),
        "COSTANZA_ROUTING_PATH": str(routing_path),
        "API_BEARER_TOKEN": TOKEN,
        **{f"WEBHOOK_SECRET__{n}": SECRET for n in ("SEERR", "RADARR", "SONARR", "TAUTULLI")},
    }
    os.environ.update(env)
    os.environ.pop("COSTANZA_KILL_SWITCH", None)
    os.environ.pop("DISCORD_TOKEN", None)

    from .main import create_app

    port = _free_port()
    app = create_app()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    base = f"http://127.0.0.1:{port}"
    auth = {"Authorization": f"Bearer {TOKEN}"}
    ok = True
    try:
        with httpx.Client(base_url=base, timeout=5.0) as client:
            for _ in range(100):
                try:
                    if client.get("/readyz").status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                time.sleep(0.1)
            else:
                print("FAIL server never became ready")
                return 1

            print(f"replay instance up at {base} (scratch: {scratch})")

            # Fresh DB boots with the kill switch engaged (safe default).
            state = client.get("/api/v1/admin/kill-switch", headers=auth).json()
            ok &= _check("kill switch defaults ON", state["engaged"] is True)
            client.post(
                "/api/v1/admin/kill-switch",
                headers=auth,
                json={"engaged": False, "set_by": "replay"},
            )

            # Feed the story; every payload twice.
            for source, name, override in _STORY:
                payload = json.loads((FIXTURES / source / name).read_text())
                if override:
                    payload.update(override)
                for attempt in range(2):
                    resp = client.post(
                        f"/webhooks/{source}",
                        json=payload,
                        headers={"X-Webhook-Token": SECRET},
                    )
                    ok &= _check(
                        f"{source}/{name} delivery {attempt + 1} -> 202",
                        resp.status_code == 202,
                        str(resp.status_code),
                    )

            # Auth failure is rejected and archived nowhere.
            resp = client.post(
                "/webhooks/radarr", json={}, headers={"X-Webhook-Token": "wrong"}
            )
            ok &= _check("bad webhook secret -> 401", resp.status_code == 401)

            # Wait for the outbox to drain.
            for _ in range(100):
                diag = client.get("/api/v1/admin/diagnostics", headers=auth).json()
                if diag["outbox_backlog"] == 0:
                    break
                time.sleep(0.1)
            ok &= _check("outbox drained", diag["outbox_backlog"] == 0)
            ok &= _check("no dead ingest items", diag["dead_outbox"] == [])

            # Timeline: five events, one media row, chain closed available.
            events = client.get(
                "/api/v1/events", headers=auth, params={"limit": 100}
            ).json()["events"]
            media_ids = {e["media_id"] for e in events if e["media_id"]}
            ok &= _check(
                "duplicates collapsed to one event each",
                len(events) == len(_EXPECTED_TIMELINE),
                f"{len(events)} events",
            )
            ok &= _check("single media identity", len(media_ids) == 1, str(media_ids))
            if media_ids:
                timeline = client.get(
                    f"/api/v1/media/{media_ids.pop()}/timeline", headers=auth
                ).json()
                got = [e["type"] for e in timeline["events"]]
                ok &= _check(
                    "timeline order", got == _EXPECTED_TIMELINE, " -> ".join(got)
                )
                chains = timeline["chains"]
                ok &= _check(
                    "request chain closed available",
                    len(chains) == 1
                    and chains[0]["state"] == "available"
                    and chains[0]["closed_at"] is not None,
                )
                watch = [e for e in timeline["events"] if e["type"] == "watch.completed"]
                ok &= _check(
                    "watch mapped to household member",
                    watch and watch[0]["user_id"] == "u:alice",
                )

            # Exactly-once notifications, straight from the ledger.
            rt = app.state.runtime
            rows = rt.store.query("SELECT event_key, channel, status FROM notifications")
            got_keys = {(r["event_key"], r["channel"]) for r in rows}
            ok &= _check(
                "exactly-once notification ledger",
                len(rows) == len(_EXPECTED_NOTIFICATIONS)
                and got_keys == _EXPECTED_NOTIFICATIONS,
                f"{len(rows)} rows",
            )
            ok &= _check(
                "no adapter -> rows retained for later drain",
                all(r["status"] in ("pending", "failed") for r in rows),
            )

            stats = client.get("/api/v1/stats/requests", headers=auth).json()["per_user"]
            ok &= _check(
                "request stats per user",
                stats == [{"user": "Alice", "made": 1, "available": 1, "watched": 1}],
                json.dumps(stats),
            )
    finally:
        server.should_exit = True
        thread.join(timeout=10)

    print("replay:", "PASS" if ok else "FAIL")
    return 0 if ok else 1
