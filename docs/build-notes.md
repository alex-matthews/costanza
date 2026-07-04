# v1 build notes

Implementation record for the v1 build (2026-07-04, per
[v1-build-prompt.md](v1-build-prompt.md)). The design pack was followed;
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

## Definition-of-done results

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
