# v1 build notes

Implementation record for the v1 build (2026-07-04, per
[v1-build-prompt.md](history/v1-build-prompt.md)). The design pack was followed;
everything below is either a small deviation, a choice the pack left
open, or a discovery worth carrying into open-questions.

## Deviations from the handoff

1. **`kill_switch_audit` table added.** handoff.md requires the kill
   switch to be "persisted, audited" but the data model gives the toggle
   no home. Added one table (id, engaged, set_by, via, set_at); latest
   row is current state; empty table = **engaged** (a fresh deploy is
   silent until someone turns it off, matching the shadow-rollout plan).
2. **`reconcile.gap` added to the event-type enum.** The build prompt
   mandates gap *markers*; the handoff enum predates them. Markers are
   ordinary events (origin=reconcile), keyed
   `{source}:reconcile.gap:{window_start}`, routable via the allowlist
   (example config routes them to `#media-admin`).
3. **Seerr `MEDIA_FAILED` maps to `health.issue`** with
   `attrs.kind=request_failed` — the enum has no `request.failed`. The
   renderer special-cases it back to "Request failed: <title>".
4. **`GET /api/v1/admin/diagnostics` added** (read-only). Constraint 6
   requires invalid-JSON/dead items "surfaced in admin diagnostics";
   the handoff API list has no such surface. It also gives `mise run
   replay` its drain/deadness checks. No write ability.
5. **Digest ledger rows use a synthetic key** (`digest:{period_end}`)
   and are rendered at send time from the digest job cursor — the
   `notifications` schema (kept verbatim) has no payload column, so
   re-rendering from stored state is the only option. The cursor only
   advances when a row is actually enqueued (or when suppressed by the
   kill switch, so disengaging never dumps weeks of backlog).

## Choices the pack left open

- **Kill-switch semantics:** engaged at *enqueue* time suppresses row
  creation (counted in metrics) so disengaging doesn't flood channels
  with backlog; engaged at *send* time defers rows without burning
  attempts, so a brief flip never dead-letters anything.
- **Notification fan-out is origin-blind:** every stored event passes
  through the router allowlist, including reconcile-synthesized ones
  (they render with an "Origin: reconcile" field). Policy lives in
  routing.yaml alone.
- **Arr reconcile dedupe:** webhook and history keys share the
  `downloadId` discriminator; a LIKE match
  (`{src}:{type}:{media}:%{downloadId}`) collapses grouping mismatches
  (season-pack grab webhook vs per-episode history records). File
  deletes share no id across the two paths, so synthesis is guarded by
  "same type + same media within ±24 h" instead.
- **Tautulli watch keys are identical for both OQ-3 paths**
  (`{src}:watch.completed:{user}:{rating_key}`), so flipping
  `watch_completion.tautulli_watched_trigger` later cannot double-count
  historical watches.
- **Seerr partial vs full availability get distinct keys** (media
  status is part of the key); partial availability sets chain state
  `partially_available` without closing; only full availability (or
  decline) closes a chain. Closed chains never reopen.
- **Discord adapter connects with `Intents.none()`** — enough to
  publish embeds. v1.x reaction capture will need intent and handler
  additions (adapter-local by design).

## Fixtures

- Seerr request-lifecycle payloads and the Tautulli recently-added
  sample were seeded from the old repo's recordings (vendor shapes
  only). The old repo's Radarr/Sonarr samples used non-vendor shapes
  (`MovieImported`/`EpisodeImported`) and were **not** carried over; all
  Radarr/Sonarr and remaining Tautulli/Seerr fixtures are built from
  official webhook schemas and flagged `synthetic: true` in per-source
  `NOTES.md` sidecars for replacement during shadow ingest.
- The expected Tautulli webhook JSON template Costanza consumes is
  documented in `fixtures/tautulli/NOTES.md` — configuring Tautulli's
  webhook agent with exactly that template is a rollout step.

## Hardening pass (post-review, 2026-07-05)

- **Client secrets can no longer leak into logs.** All read-client
  failures are re-raised as a sanitized `ClientError` (path + status
  only, cause chain severed) because httpx exceptions embed the full
  URL — for Tautulli that includes `?apikey=...` — and reconcile /
  identity_sync log `str(exc)` into logs and summaries.
- **Digest rendering is period-stable.** Ledger keys now encode both
  period bounds (`digest:{start}|{end}`) and each pending row renders
  its own window at send time; previously two rows pending across a
  channel outage would both render the newest cursor window. A 1-hour
  minimum period guards against scheduler double-fires; legacy
  date-only keys fall back to the cursor.
- **Crash-safe event processing.** Event insert, chain update, and
  notification enqueue are separate SQLite transactions; a crash
  between them used to strand the event with no notification (retry
  deduped the insert and skipped fan-out). Reprocessing is now
  idempotent repair: chain advancement runs for deduped events too
  (forward-only via a state-rank guard, which also fixes a latent
  out-of-order regression bug), and the worker enqueues
  unconditionally — `UNIQUE(event_key, channel)` keeps already-sent
  rows untouched, preserving exactly-once.
- **Reconcile now routes through the notification allowlist** (via the
  same enqueue path, gated by the kill switch) — previously
  reconcile-synthesized events and `reconcile.gap` markers were stored
  but never enqueued, making the example `reconcile.gap -> #media-admin`
  rule dead config and contradicting these notes.
- **Raw retention now covers dead-lettered payloads.** Prune previously
  deleted only raws whose outbox rows were done; a dead row (e.g.
  invalid JSON) pinned its raw body forever. Bodies and archived
  headers of any raw older than retention are now redacted in place,
  keeping the diagnostics row (source, timestamps, last_error) intact.
- **Kill-switch `set_by` is user-supplied text**, not a strong audit
  identity — acceptable for v1 single-household ops behind the bearer
  token; revisit if the API ever grows more writers.
- Repo hygiene: `.dockerignore`, `.editorconfig`, `.gitattributes`
  added; `Store.enqueue_outbox` accepts an injected clock (fixed a
  time-of-day-dependent flake in worker tests).

## Reviewer follow-up round (2026-07-05)

- **Reconcile crash repair.** The notifying applier gained a `repair()`
  path: when reconcile meets an exact-key duplicate, it re-enqueues the
  ledger rows a crashed previous run may have skipped. Bounded to
  reconcile-origin events with `received_at` strictly after the current
  window start, so webhook twins stay the ingest worker's job and
  kill-switch-suppressed history from completed runs is never backfilled
  (the strict bound works because a successful run advances the cursor
  to exactly its own `now`). Gap markers repair via a newest-marker
  lookup; gap marking moved inside the per-source error boundary.
  Repairs are never counted as recovered.
- **CI/release/Renovate** added (patterns shared with Resolute; the
  action pins were later re-verified against the live home-ops workflows —
  see the ops reset section below): tests
  (lock check, pytest, replay) + no-push container build on PRs; lint
  (ruff, hadolint, actionlint+zizmor); release-please (python type);
  release via the docker/github-builder reusable workflow to
  ghcr.io/alex-matthews/costanza with SBOM, provenance, and cosign
  keyless signing; self-hosted Renovate on the bot-app pattern
  (BOT_APP_CLIENT_ID / BOT_APP_PRIVATE_KEY); Trivy scan report-only with
  the same rationale as Resolute. All actions SHA-pinned, minimal
  per-job permissions, persist-credentials false. mise gained
  workflow-lint and ci tasks; mise.lock now carries full checksums.
- **App version** derives from package metadata (importlib.metadata),
  so release-please version bumps flow into `/docs` and the FastAPI app
  without code edits.
- **Container hardening:** `PYTHONDONTWRITEBYTECODE=1`,
  `PYTHONUNBUFFERED=1`; verified the image serves probes under
  `--read-only --cap-drop=ALL --security-opt no-new-privileges` with no
  tmpfs — only /data needs write. Deploy notes carry the securityContext.

## Ops reset (2026-07-05, external review "Prompt A", H1-H10)

Blocker-grade container/deploy conflicts with the live cluster, fixed:

- **H1/H3 image user model + base:** the image no longer bakes storage
  identity (dropped `useradd -u 1033`, `chown`, `VOLUME`). Base is
  `python:3.14-alpine3.24` (SHA-pinned), uv multi-stage kept,
  `USER nobody:nogroup` as the bare-run default — the
  home-operations/containers precedent (apps/tautulli). The image runs
  correctly as any arbitrary uid:gid; Kubernetes supplies identity. No
  musl wheel problems: the alpine build resolved every dependency from
  the existing lockfile unchanged.
- **H2 deploy docs:** previous deploy/README.md said `runAsUser: 1033`
  and omitted `fsGroup` entirely — data written as 1033 without fsGroup
  breaks the volsync restic movers (`${VOLSYNC_PUID:=1032}`). Corrected
  to the verified cluster standard: `runAsUser: 1032, runAsGroup: 100,
  fsGroup: 100, fsGroupChangePolicy: OnRootMismatch, runAsNonRoot: true`
  plus read-only rootfs / drop ALL / no privilege escalation.
- **H4 no baked config:** `COPY routing.example.yaml /config/routing.yaml`
  removed from the image; the app fails fast with a clear error when the
  ConfigMap is absent. Smoke tooling mounts the example config
  explicitly and read-only.
- **H5 constraint test scope:** the no-external-writes scan now covers
  ALL of src/costanza (previously clients/ only, while prose claimed the
  whole binary — overclaim confirmed by the review). Explicit allowlist:
  `replay.py` (self-targeting dev tool POSTing fixtures at a local
  scratch instance); inbound `@router.post` route declarations are
  skipped per-line; a guard test keeps the allowlist from growing.
- **H6 Kubernetes-constraint smoke:** `scripts/k8s-smoke.sh` (+ mise
  `k8s-smoke`, wired into the CI container job) runs the built image with
  `--user 1032:100 --read-only --cap-drop ALL`, no HOME, only a mounted
  /data writable, config read-only — asserts probes, DB creation in
  /data, and clean logs.
- **H7 SQLite-on-volsync posture** documented in deploy/README.md:
  Snapshot copyMethod = crash-consistent point-in-time; WAL sidecars
  restore together and replay on open; concrete restore drill (scratch
  PVC -> debug pod as 1032:100 -> `PRAGMA integrity_check` + recency
  queries).
- **H8 docs authority sweep:** "Resolute as house style" removed from
  living docs; architecture.md/handoff.md carry an ops-authority
  correction note pointing at home-ops live manifests and
  home-operations/containers. v1-build-prompt.md (now docs/history/) is left as the
  historical record of what the build was told. Product/boundary
  discussion of Resolute-the-service unchanged.
- **H9 workflow parity audit:** the shared action pins
  (actions/checkout, jdx/mise-action, actions/create-github-app-token,
  renovatebot/github-action) match the live home-ops workflows exactly.
  Intentional divergences kept: pinned `RENOVATE_VERSION` +
  `RENOVATE_REPOSITORIES` + mise unsafe-execution env (code repos need
  `mise lock`; home-ops uses autodiscover + latest), and the
  docker/release-please/trivy/codeql actions have no home-ops
  counterpart (SHA-pinned, adopted deliberately). No cosmetic churn.
- **H10 secrets audit:** Seerr/Arr clients verified to inherit the
  sanitized ReadOnlyClient error path (tests added, mirroring the
  Tautulli ones); a new test proves neither presented nor configured
  webhook secrets ever appear in ingest logs (auth failures log the
  source name only). Resolute's Seerr/Sonarr clients were checked in the
  same pass — see its build notes.

Accepted risks restated from the review: kill-switch `set_by` free text
(H14), Tautulli apikey in cluster-internal URLs (H15), single household
bearer token (H16), repair-based (not transactional) consistency (H17),
Trivy image-scan first-run failure until `:main` exists (H18).

## Discoveries / candidates for open-questions

- **Seerr request-id consistency (reconcile dedupe):** webhook
  `{{request_id}}` and the request-list API `id` must render the same
  value for webhook/reconcile twins to collapse. Stock Seerr does; worth
  a one-time verification during rollout step 2 (reconcile confidence).
- **Prometheus naming:** client convention appends `_total` to
  counters, so alerts must target `costanza_webhook_auth_failures_total`
  (the gauge `costanza_outbox_backlog` is unsuffixed as designed).
- **Arr library/disk stats clients were not built.** The scope line
  permits them ("reconcile + identity_sync + library/disk stats only")
  but no v1 API endpoint or digest section consumes them; adding unused
  client surface seemed worse than adding it alongside its first
  consumer (likely the v1.x Grafana work).
- **Radarr `MovieAdded` and Tautulli `recently_added` normalize to
  `source.unknown`** on purpose (imports come from Arr `Download`
  events; keeping both would double-count arrivals). If the household
  ever wants "added to Plex" distinct from "imported by Arr", that's a
  new canonical type, not a normalizer tweak.
- **Replay asserts the ledger directly** (same process) for the
  exactly-once check; everything else goes through the public API.

## Definition-of-done results (historical — original v1 build, 2026-07-04)

> **Superseded on container facts:** the uid-1033/`VOLUME /data` image
> described below was replaced in the ops reset (see the ops-reset section
> above) with an identity-agnostic alpine image (`USER nobody:nogroup`, no
> baked uid, no baked config; the cluster sets 1032:100 via
> securityContext), and the write-verb constraint test now scans all of
> `src/`, not just `clients/`. Test counts have grown since. Kept as the
> record of the original definition-of-done pass.

- All 166 tests green offline; `mise run replay` PASS (timeline order,
  single media identity, chain closure, exactly-once ledger, 202-always,
  auth rejection).
- Fresh clone → `mise run sync && mise run test` verified.
- `docker build` succeeds; container runs nonroot (uid 1033) with
  `/data` volume, boots with kill switch ON, serves
  `/healthz` `/readyz` `/metrics`. hadolint clean.
- Constraint greps clean (and encoded as tests in
  `tests/test_constraints.py`): no discord import outside
  `adapters/discord/`, no non-GET verbs in `clients/`, no
  llm/redis/postgres dependencies, no relay awareness in code.
