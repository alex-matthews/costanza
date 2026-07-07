# Architecture

Costanza is one service with **two layers**:

- **Substrate layer (shipped):** ingest → normalize → correlate → store →
  notify, plus reconcile/digest/prune jobs, read-only source clients, and
  the read API. It turns webhook noise into a durable, correlated,
  identity-mapped event history and delivers exactly-once notifications.
  This layer is the system of record and the evidence source — it is not
  the product.
- **Council layer (designed, next):** the household media council —
  proposals, interest, votes, cases, pleas, protections, decisions — a
  domain model that *references* substrate events as evidence and drives
  participation through Discord interactions. See
  [council/domain-model.md](council/domain-model.md) and
  [ADR-0007](adr/0007-council-domain-layer.md).

The sections below cover the substrate's architecture decisions (still
accurate as built) and the deployment model shared by both layers.

## Options considered (substrate)

### Option A — Modular monolith (recommended)

One Python process, one container, one PVC. Hexagonal internally:

```
                         ┌──────────────────────────────────────────────┐
 Seerr ──webhook──►      │  ingest (verify, raw-archive)                │
 Radarr/-se ──webhook──► │    │                                         │
 Sonarr ──webhook──►     │    ▼                                         │
 Tautulli ──webhook──►   │  normalize (per-source) ──► canonical events │
                         │    │                                         │
 (Chaski optional tee)   │    ▼                                         │
                         │  correlate (media identity, timelines,       │
                         │             household identity map)          │
                         │    │                                         │
                         │    ▼                            ┌─────────┐  │
                         │  SQLite (WAL) on PVC ◄──────────┤ jobs:   │  │
                         │    │   events, media, users,    │ digest, │  │
                         │    │   ledger, signals          │ reconcile│ │
                         │    ▼                            └─────────┘  │
                         │  route/render ──► notifier ports             │
                         │    │                 │                       │
                         │  read-only API     Discord adapter (bot)     │
                         │  /metrics          [ntfy/Apprise later]      │
                         └──────────────────────────────────────────────┘
```

- In-process event dispatch (plain function calls / small internal bus), no
  broker. Webhook handlers do verify→persist→enqueue-in-SQLite and return
  2xx fast; a worker loop processes the outbox.
- Discord gateway bot runs as an async task in the same process. Shipped:
  publishing via the notifier port. Council layer: the same supervised task
  grows into an interaction gateway (buttons/selects/modals/threads —
  [ADR-0008](adr/0008-discord-interactions-surface.md)); the port boundary
  still lets it split out without touching the core if discord.py churn
  ever hurts.
- Single replica, which SQLite requires anyway and household load trivially
  permits (< 1 event/sec forever).

**Pros:** matches the cluster's proven single-replica stateful-app
pattern; one thing to deploy,
back up (volsync), and debug; fixture-driven testing stays trivial; no
infra dependencies beyond a PVC.
**Cons:** Discord lib in the same venv as core logic; a bot crash-loop can
take ingestion down (mitigated: bot task is supervised and non-fatal;
ingestion never awaits Discord).

### Option B — Event pipeline on Dragonfly streams

Ingest deployment → Dragonfly (Redis streams) → worker deployment →
Discord-adapter deployment; SQLite or Dragonfly-persisted state.

**Pros:** adapters isolated; independent restarts; "proper" eventing.
**Cons:** three deployments and a broker dependency for one household's
~dozens of events/day; consistency between stream state and durable state
becomes a real problem; harder fixture testing; Dragonfly here is
cache-tier, not a durability guarantee. Classic overbuild. **Rejected.**

### Option C — Chaski-front, Costanza-as-consumer

Chaski receives all webhooks and fans out to Costanza + channels directly.

**Cons:** Chaski is stateless — no dedupe, correlation, digests, or
identity; the interesting notifications all need state, so Costanza ends up
doing the work anyway and Chaski becomes a mandatory hop. Violates the
household rule that the relay stays optional. **Rejected as baseline;
retained as optional tee** ([ADR-0004](adr/0004-chaski-boundary.md)).

## Recommendation

**Option A.** Complexity budget goes to the domain (correlation, identity,
noise control), not to infrastructure.

## Language / runtime

**Python 3.14.x + uv + mise (pinned via `.python-version`/`.mise`)**,
FastAPI + uvicorn, pydantic v2 models for all contracts, `discord.py`
behind a notifier port, APScheduler (or a simple asyncio cron loop) for
jobs. Toolchain (uv, pytest, ruff, fixtures, no-network tests) is the
shared house style across this household's services.
Go/TypeScript were considered and declined: the workload is
integration- and (later) LLM-heavy, where Python iteration speed wins, and
a third runtime buys nothing a port boundary doesn't.

## State / storage

**SQLite (WAL) on a PVC, volsync-backed** — durable system of record for
events, media, identity, ledger, signals ([ADR-0002](adr/0002-durable-store-not-cache-first.md)).

- Raw webhook payloads archived to a pruned table (30-day default) for
  replay/debugging; canonical events kept indefinitely (tiny).
- No Dragonfly/Redis in v1: single process makes in-process debounce/locks
  sufficient. If a cache tier is ever needed, it must remain lose-able.
- Postgres reconsidered only if a second writer process becomes necessary;
  there is no Postgres operator in the cluster today and adding one for a
  household event log is not justified.

## Eventing / webhook model

- **Inbound:** `POST /webhooks/{source}` per configured source instance
  (v1: `seerr`, `radarr`, `sonarr`, `tautulli`; later e.g. `bazarr` or a
  second Arr instance — registration is config-only by design).
  Shared-secret per source (header token; HMAC where the source supports
  it). Handler: verify → store raw → 202. Normalization/correlation happen
  off the request path via a SQLite-backed outbox, so a bad payload never
  drops a webhook.
- **Idempotency:** deterministic `source_event_key` per normalizer
  (source + native id/timestamp hash); duplicates from retries/Chaski tees
  collapse.
- **Reconciliation:** scheduled polls of Seerr/Arr/Tautulli APIs diff
  against the store and synthesize missed events (marked `origin=reconcile`).
  Webhooks are the fast path; polls are ground truth **only for state the
  source retains**. Transient events (grabs that later failed, health
  blips, playback starts) are not fully reconstructable — reconcile either
  recovers them from source history APIs or flags the gap, per this matrix:

  | Source | Event kinds | Reconcile guarantee |
  | --- | --- | --- |
  | Seerr | request created/approved/declined/available | **Reconstructable** (request list API retains lifecycle + terminal state) |
  | Radarr/Sonarr | import, upgrade, delete, grab | **Mostly reconstructable** via `/history` API (grab/import/delete records); exact timestamps may shift to history-record time |
  | Radarr/Sonarr | health issues, failed downloads | **Flag-only** — transient; a `reconcile.gap` marker event is stored instead of a synthesized event |
  | Tautulli | watch.completed | **Reconstructable** (history API) |
  | Tautulli | playback.started/stopped | **Flag-only** — sessions age out; watch.completed from history is the durable residue |

  Consequence: request/library/watch analytics can be trusted after any
  outage; transient-event notifications are best-effort and the digest
  notes detected gaps rather than pretending completeness.
- **Outbound:** routing rules (event-type allowlist × channel) →
  renderer → notifier port → ledger write (dedupe + audit) → send. Rate
  limiter and kill switch sit between router and ports.

## Deployment model

Standard home-ops shape, namespace `default` alongside the media apps.
**Ops authority is the live cluster**: securityContext and storage
identity follow the home-ops manifests for stateful apps
(`runAsUser: 1032, runAsGroup: 100, fsGroup: 100, fsGroupChangePolicy:
OnRootMismatch, runAsNonRoot: true` — the volsync restic movers run as
PUID 1032, so any other data owner breaks backup/restore), and the
container pattern follows home-operations/containers (identity-agnostic
image, `USER nobody:nogroup` default, SHA-pinned alpine base, no baked
config; storage identity always comes from Kubernetes, never the image).
See [../deploy/README.md](../deploy/README.md) for the full posture,
including the SQLite-on-volsync backup/restore drill.

- bjw-s **app-template HelmRelease** + OCIRepository; single replica,
  `strategy: Recreate`.
- **PVC** (1–5 Gi) for SQLite, volsync-backed like other stateful apps.
- **ExternalSecret** for Discord token, per-source webhook secrets, API
  keys for Seerr/Arrs/Tautulli.
- Cluster-internal Service; webhook sources reach it as
  `http://costanza.default.svc`. No external ingress in v1 (Discord uses an
  outbound gateway connection, not inbound webhooks).
- `/healthz`, `/readyz`, `/metrics` + ServiceMonitor; low-cardinality
  metric labels (carried over from old repo's hard-won rule).
- Image built in the costanza repo via GitHub Actions → GHCR (SBOM,
  provenance, cosign-signed); Renovate bumps the digest in home-ops — the
  same publish flow every self-built app in the cluster uses.
