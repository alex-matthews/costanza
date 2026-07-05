# Costanza v1 — scoped build prompt

> **Historical artifact.** This is the prompt that built what is now the substrate layer; it is preserved verbatim as the record of what that build was told (including conventions since corrected — see build-notes.md) and is not current spec. Current product: [../product-brief.md](../product-brief.md) and [../council/](../council/).

You are implementing **Costanza v1** in this repository (`~/src/costanza`).
A complete, reviewed design pack exists and is **authoritative**. Your job
is execution, not redesign.

## Read first, in this order

1. [docs/handoff.md](../handoff.md) — your primary spec: repo layout, modules,
   canonical event contract, SQLite schema, API surface, jobs, config,
   testing, rollout.
2. [docs/adr/](../adr/) — ADRs 0001–0006. These are settled. Do not relitigate
   them; if implementation reveals a genuine conflict, stop and surface it
   rather than "resolving" it silently.
3. [docs/architecture.md](../architecture.md) — especially the reconciliation
   guarantees matrix and the eventing/idempotency rules.
4. [docs/open-questions.md](../open-questions.md) — **the recommended defaults
   are binding.** OQ-1 and OQ-6 are already answered; nothing is left that
   blocks the build.
5. [docs/system-boundaries.md](../system-boundaries.md) and
   [docs/capability-map.md](../capability-map.md) — for scope arbitration when
   you're tempted to add something.

## Scope: exactly this

Tiers 0–1 from ADR-0006 — observe and notify:

- Webhook ingestion for sources `seerr`, `radarr`, `sonarr`, `tautulli`:
  per-source shared-secret auth, body-size caps, raw archive,
  SQLite-backed outbox, fast 202. Sources are **config-registered by
  name** — `radarr-se` (a personal, non-Seerr Radarr instance) is
  deliberately NOT configured in v1, and adding a second Arr instance
  later must be a pure config change, no code change.
- Per-source normalizers → the canonical event schema in handoff.md,
  including `source.unknown` for unrecognized payloads (keep, never drop).
- Correlation: media identity (tmdb/tvdb/imdb → `media`), household
  identity map from config, request chains / per-title timelines.
- Notification pipeline: config-driven event-type allowlist × channel
  routing → pure renderers → rate limits + kill switch → `notifications`
  ledger (which doubles as the retrying outbound outbox: pending/sent/
  failed/dead, attempts, backoff, `UNIQUE(event_key, channel)` dedupe) →
  notifier port.
- Discord adapter: the **only** module importing `discord.py`; supervised
  in-process async task; publishes embeds/digests; its failure must never
  block or crash ingestion.
- Jobs (APScheduler in-process): weekly digest, hourly reconcile
  (honoring the guarantees matrix — synthesize `origin=reconcile` events
  only where the matrix says reconstructable, `reconcile.gap` markers
  otherwise), daily raw-payload prune (30d), daily identity_sync flagging
  unmapped external users.
- Read API + `/healthz` `/readyz` `/metrics` per handoff.md, bearer-token
  auth on `/api/*`. The **single** write endpoint is
  `POST /api/v1/admin/kill-switch` (persisted, audited); env
  `COSTANZA_KILL_SWITCH=true` overrides everything.
- Read-only clients for Seerr, Radarr/Sonarr, Tautulli (reconcile +
  identity_sync + library/disk stats only).
- Dockerfile (uv multi-stage, nonroot, `/data` volume), versioned SQLite
  migrations, structlog logging, low-cardinality Prometheus metrics
  (including `costanza_outbox_backlog`, `costanza_webhook_auth_failures`).

## Hard constraints (violating any of these is a failed build)

1. **No write code paths to any external system.** Not flagged off —
   absent. No Seerr/Arr/Tautulli/Maintainerr/Plex mutation calls anywhere,
   including tests. Discord message sends and the kill-switch endpoint are
   the only outbound writes.
2. **No LLM calls, no litellm client, no prompt templates.** (ADR-0005
   binds later phases; v1 contains zero LLM code.)
3. **Nothing in the codebase knows Chaski exists** (ADR-0004). Inbound
   contract is the sources' native payloads; idempotency keys make any
   future tee invisible.
4. **SQLite WAL on `/data` is the only store.** No Redis/Dragonfly/
   Postgres dependencies. Single-writer, single-replica assumptions are
   fine and expected.
5. **Core never imports `discord.py`**; everything channel-shaped goes
   through the notifier port (ADR-0001).
6. Webhook handlers never parse beyond JSON validity on the request path;
   normalization happens off-path via the outbox. After source auth and
   body-size checks pass, **always archive the raw payload and return
   202**; invalid JSON becomes a raw archived failure / dead outbox item
   surfaced in admin diagnostics — never a source-facing 4xx/5xx that
   creates a retry storm.
7. No web UI, no votes/signals writers (the `signals` table may exist,
   empty), no subtitle features, no recommendation code.

## Conventions (mirror `~/src/resolute`)

- Python pinned to the same minor Resolute pins (**3.14.x** — check its
  `.mise/config.toml` for the current patch), `uv` with `uv.lock`,
  `.mise/config.toml` + `mise.lock` with tasks: `sync`, `run`, `test`,
  `lint`, `lint-fix`, `replay`, plus Dockerfile/workflow lint tasks if you
  add CI. **No justfile.**
- FastAPI + uvicorn, pydantic v2 for all contracts, pydantic-settings
  env-first config that fails fast on missing required values.
- ruff for lint, pytest with **no network access by default**; fixtures
  under `fixtures/` drive normalizer golden tests.
- Fixture seeding: you may copy recorded webhook payload samples from the
  old repo (`/Users/alex/costanza`, its tests/data) — those are upstream
  vendor formats, not design. **Do not port its code, schema, or module
  structure.** Where no sample exists, build from official webhook docs
  and mark the fixture `synthetic: true` in a sidecar note so real
  captures replace it during rollout.
- Repo layout: follow the tree in handoff.md. Keep `docs/` as-is (living
  design pack); add code without reorganizing it.

## Testing bar (from handoff.md — all required)

- Golden fixture tests per normalizer per source.
- Correlation scenario tests (fixture sequences → expected chain state).
- Renderer snapshot tests (pure functions).
- Ledger/limits properties: same event twice ⇒ one send; storm ⇒
  rate-limited; Discord-down ⇒ pending rows accumulate and drain.
- Reconcile diff tests against canned API responses, asserting the
  guarantees matrix (reconstructable vs gap-marker) per source.
- `mise run replay` feeds fixtures at a running instance end-to-end.

## Suggested build order

1. `store/` + migrations + config — the schema in handoff.md verbatim.
2. `ingest/` + outbox + raw archive (test: accept, archive, 202, dedupe).
3. Normalizers + fixtures (the highest-value suite — do these carefully).
4. `correlate/` (media identity, identity map, request chains).
5. `notify/` (router → render → limits → ledger/outbox → port) with a
   fake notifier; then the Discord adapter.
6. Jobs (reconcile first — it forces the read clients — then digest,
   prune, identity_sync).
7. API + metrics; Dockerfile; replay task; final acceptance pass.

## Definition of done

- All tests green offline; `mise run replay` produces correct timelines
  and exactly-once notifications against a scratch DB.
- Fresh clone → `mise run sync && mise run test` works.
- `docker build` succeeds; container runs nonroot with `/data` mounted,
  starts with kill switch ON by default config, and serves
  `/healthz`/`/readyz`/`/metrics`.
- `grep` proves the constraints: no `discord` import outside
  `adapters/discord/`, no HTTP verbs other than GET in `clients/`, no
  llm/redis/postgres deps in `pyproject.toml`.
- A short `docs/build-notes.md` recording deviations (there should be
  few) and anything discovered that belongs in open-questions.

## Explicitly out of scope (do not build, even "behind a flag")

Kubernetes manifests (they go in the home-ops repo later, per
handoff.md), Chaski config, Maintainerr/Bazarr integration, votes/polls,
reaction capture, recommendations, LLM anything, ntfy/Apprise adapters,
web UI, multi-replica support.
