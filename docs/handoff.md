# V1 implementation handoff

> **Ops-authority correction (2026-07-05):** where this document cites
> Resolute as the precedent for container/deployment/tooling patterns,
> read the authority as the **live cluster** instead: home-ops manifests
> (securityContext `runAsUser: 1032, runAsGroup: 100, fsGroup: 100,
> fsGroupChangePolicy: OnRootMismatch`; volsync movers at PUID 1032) and
> home-operations/containers (identity-agnostic images, `USER
> nobody:nogroup`, alpine base, no baked config). Resolute shared these
> flaws and was corrected in the same ops reset — see
> [build-notes.md](build-notes.md). Product/boundary discussion of
> Resolute-the-service is unaffected.

Everything a build session needs. Scope: Tiers 0–1 only (observe + notify).

## Repo structure

```
costanza/
├── pyproject.toml            # uv-managed; python pinned to Resolute's
│                             # current toolchain (3.14.x); fastapi,
│                             # pydantic v2, discord.py, apscheduler,
│                             # httpx, structlog
├── uv.lock
├── Dockerfile                # uv-based multi-stage, nonroot, /data volume
├── .mise/                    # config.toml + mise.lock — house task runner
│                             # (Resolute-style tasks: sync, test, lint,
│                             # golden, replay, run); no justfile
├── src/costanza/
│   ├── config.py             # pydantic-settings; env-first; fail-fast
│   ├── main.py               # wiring: FastAPI app + worker + bot + jobs
│   ├── ingest/               # webhook routes, source auth, raw archive
│   │   └── sources.py        # config-registered sources (v1: seerr, radarr, sonarr, tautulli)
│   ├── normalize/            # per-source payload → CanonicalEvent
│   │   ├── seerr.py  radarr.py  sonarr.py  tautulli.py
│   ├── correlate/            # media identity resolution, timelines,
│   │   └── identity.py       # household identity map
│   ├── store/                # sqlite repo layer + migrations/
│   ├── outbox.py             # SQLite-backed work queue (ingest → process)
│   ├── notify/
│   │   ├── router.py         # event-type allowlist × channel rules
│   │   ├── render.py         # embeds/digest templates (pure functions)
│   │   ├── ledger.py         # dedupe + audit of every outbound message
│   │   ├── limits.py         # rate limits + kill switch
│   │   └── ports.py          # Notifier protocol
│   ├── adapters/discord/     # the only module importing discord.py
│   ├── jobs/                 # digest.py, reconcile.py, prune.py, identity_sync.py
│   ├── clients/              # read-only API clients: seerr, arr, tautulli
│   ├── api/                  # read-only REST + /healthz /readyz /metrics
│   └── stats/                # aggregate queries backing api + digest
├── tests/                    # pytest, no-network default (Resolute style)
├── fixtures/                 # recorded webhook payloads per source/version
├── docs/                     # this pack, kept living
└── deploy/                   # reference k8s notes (real manifests in home-ops)
```

## Core modules and responsibilities

- **ingest:** verify per-source secret → insert raw_events row + outbox row
  → `202`. Never parses beyond JSON validity on the request path.
- **normalize:** pure functions, one per source, fixture-tested. Unknown
  event types produce a `source.unknown` canonical event (kept, not dropped)
  so new upstream types surface in logs/digest instead of vanishing.
- **correlate:** resolves media identity (tmdb/tvdb/imdb ids → `media` row),
  attaches user identity via the identity map, links events into a title
  timeline (e.g. availability event closes the matching request chain).
- **notify:** router (config-driven allowlist) → render (pure) → limits →
  ledger (idempotency: skip if `(event_key, channel)` already sent) → port.
- **jobs:** APScheduler in-process — digest (weekly cron), reconcile
  (hourly), prune (daily), identity_sync (daily, pulls Seerr/Tautulli user
  lists to flag unmapped users).

## Canonical event contract

```jsonc
{
  "id": "uuid7",
  "source": "radarr",                 // configured instance name
  "source_event_key": "radarr:Download:movie:1234:2026-07-04T…", // idempotency
  "origin": "webhook | reconcile | manual",
  "type": "request.created | request.approved | request.declined |
           request.available | media.grabbed | media.imported |
           media.upgraded | media.deleted | playback.started |
           playback.stopped | watch.completed | health.issue |
           source.unknown",
  "occurred_at": "…", "received_at": "…",
  "media": { "media_id": "…", "tmdb_id": 123, "tvdb_id": null,
             "title": "…", "year": 2026, "kind": "movie|series|season|episode",
             "detail": { "season": 2, "episode": 5 } },
  "user": { "user_id": "…", "display": "…" },   // household member if mapped
  "attrs": { }                        // normalized per-type extras (quality, size, …)
}
```

Watch-completion rule: Tautulli `watched` threshold event if configured,
else derived from playback.stopped progress ≥ 85% (configurable).

## Data model (SQLite)

```
sources(id, kind, name, secret_ref, enabled)
raw_events(id, source_id, received_at, headers_subset, body_json)   -- pruned @30d
events(id, source_event_key UNIQUE, source_id, origin, type,
       occurred_at, received_at, media_id?, user_id?, attrs_json)
media(id, tmdb_id?, tvdb_id?, imdb_id?, kind, title, year, added_at)
request_chains(id, media_id, seerr_request_id?, requested_by?,
               state, opened_at, closed_at?)                        -- timeline spine
users(id, display_name, is_admin, active)
identities(user_id, provider ENUM(seerr,plex,tautulli,discord), external_id, UNIQUE(provider, external_id))
notifications(id, event_key, channel, rendered_hash,
              status ENUM(pending,sent,failed,dead), attempts,
              next_attempt_at?, last_error?, sent_at?)
  -- doubles as ledger (dedupe/audit) AND outbound outbox: rows are
  -- created 'pending'; a worker sends with backoff; Discord downtime
  -- accumulates pending rows and drains on recovery; 'dead' after N
  -- attempts surfaces in the admin digest. UNIQUE(event_key, channel)
  -- is the dedupe guarantee regardless of retry path.
signals(id, user_id?, media_id?, kind, value, at)                   -- empty in v1; reactions land here in v1.x
job_cursors(job, cursor_json, updated_at)
outbox(id, raw_event_id, state, attempts, next_attempt_at)
schema_migrations(version)
```

## Read API (v1)

```
GET /api/v1/media/{id}/timeline      GET /api/v1/events?type=&since=&user=
GET /api/v1/stats/requests           # made vs available vs watched, per user
GET /api/v1/stats/watch              # per-user/household watch aggregates
GET /api/v1/digest/preview           # renders next digest without sending
GET /api/v1/admin/kill-switch        # current state + who set it
POST /api/v1/admin/kill-switch       # the ONLY write endpoint in v1:
                                     # toggle persisted in store; audited
GET /healthz  /readyz  /metrics
POST /webhooks/{source}              # inbound only
```

Static bearer token on `/api/*` (single household token, ExternalSecret).
The API is read-only **except** the kill-switch toggle above — a fire
alarm needs to be faster than a redeploy. The `COSTANZA_KILL_SWITCH=true`
env var additionally forces silence regardless of the stored toggle.

## Integrations (v1)

| System | Inbound | Outbound (read-only) |
| --- | --- | --- |
| Seerr | webhook (all request lifecycle) | user list, request list (reconcile/identity) |
| Radarr | webhook (grab/import/upgrade/delete/health) | movie library, disk stats |
| Sonarr | webhook (same) | series library |
| Tautulli | webhook (playback/watched) | history API (reconcile/backfill) |
| Discord | reaction events (recorded to signals only, may slip to v1.x) | bot publishes embeds/digests |

## Config & secrets

- Env-first via pydantic-settings; a small `routing.yaml` (ConfigMap) for
  event-type allowlist, channel map, digest schedule, identity map
  (`users:` with per-provider ids).
- ExternalSecrets: `DISCORD_TOKEN`, `WEBHOOK_SECRET__{SOURCE}`,
  `{SOURCE}_API_KEY`, `API_BEARER_TOKEN`.
- Kill switch: `POST /api/v1/admin/kill-switch` (persisted, audited) or
  `COSTANZA_KILL_SWITCH=true` env override; either alone silences all
  outbound.

## Kubernetes (home-ops)

- `kubernetes/apps/default/costanza/app/`: HelmRelease (bjw-s app-template,
  single replica, Recreate), OCIRepository, ExternalSecret, PVC (5Gi,
  volsync label like peers), ConfigMap for routing.yaml.
- Probes: `/healthz` liveness, `/readyz` (DB + config loaded; **not**
  Discord — bot down must not restart-loop ingestion).
- ServiceMonitor; alerts later on `costanza_outbox_backlog` and
  `costanza_webhook_auth_failures`.

## Testing strategy

- **Normalizers:** golden fixture tests per source/version — the highest-value suite; fixtures recorded from real webhooks (redacted).
- **Correlation:** scenario tests replaying fixture sequences → assert
  timeline/chain state.
- **Rendering:** snapshot tests of embeds/digests (pure functions).
- **Ledger/limits:** property-style tests: same event twice ⇒ one send;
  storm ⇒ rate-limited + logged.
- **Reconcile:** diff logic against canned API responses; synthesized
  events carry `origin=reconcile`.
- **No-network default;** a `mise run replay` task feeds fixture payloads
  at a running instance for e2e smoke (mirrors Resolute's golden/fixtures
  ethos).

## Rollout plan

1. **Shadow ingest:** deploy with kill switch ON. Point one source
   (Radarr) at it; watch store/metrics for a few days. Add remaining
   sources (Sonarr, Tautulli — both support multiple webhook targets
   natively, so Costanza is added alongside existing consumers). **Seerr
   supports exactly one webhook agent** (OQ-6, confirmed): point it
   directly at Costanza while Resolute is undeployed; the moment Resolute
   deploys, insert the Chaski tee (one route, unmodified JSON relayed to
   both — see ADR-0004). Idempotency keys make the switchover safe.
2. **Reconcile confidence:** compare reconcile-synthesized vs webhook
   events; fix normalizer gaps until reconcile is quiet.
3. **Private channel:** kill switch off, notifications to an admin-only
   Discord channel; tune allowlist + digest until it earns trust.
4. **Household channel:** move real-time notifications + weekly digest to
   the household channel. Announce the identity map; fix mappings.
5. **Retire old Costanza:** decommission its deployment/webhooks; keep its
   DB dump archived; delete the repo's cluster resources.
6. **Restore drill:** volsync restore of the PVC into a scratch namespace
   once, before calling v1 done.
