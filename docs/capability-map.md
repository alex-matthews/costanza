# Capability map

Phases: **v1** (first deploy), **v1.x** (additive, no new write scopes),
**v2** (first external writes, each gated by ADR-0006), **not ours** (lives
elsewhere permanently).

## Notifications

| Capability | Phase | Notes |
| --- | --- | --- |
| Ingest + normalize Seerr, Radarr, Sonarr, Tautulli webhooks | v1 | Per-source normalizers → canonical event schema |
| Correlated per-title timeline (request→available→watched) | v1 | The differentiator vs every webhook-to-Discord pipe |
| Real-time Discord notifications, curated allowlist | v1 | Default: request approved / available / failed only |
| Weekly household digest | v1 | New arrivals, most-watched, stale requests |
| Admin digest (ops anomalies, dead requests) | v1.x | |
| Additional channels (ntfy, Apprise, email) | v1.x | New notifier adapters, no core change |
| Per-user notification preferences / DM routing | v1.x | Needs identity map (v1) first |
| Bazarr subtitle events | v1.x | Read-only ingest |

## Recommendations

| Capability | Phase | Notes |
| --- | --- | --- |
| Watchlist/interest signal ingestion (Seerr watchlists) | v1.x | Deterministic, no LLM |
| "You might like" digest section — deterministic candidates, LLM-ranked/explained | v2 | Behind ADR-0005 boundaries; litellm gateway |
| Maybe-interested vs definitely-want capture | v1.x | Reactions/votes stored as signals |
| Auto-request when household quorum met | v2, gated | Tier-4 write; capped per week; opt-in per user |
| Personal + household taste profiles | v2 | Derived from stored events/signals |

## Social / voting

| Capability | Phase | Notes |
| --- | --- | --- |
| Identity map: Seerr ↔ Plex/Tautulli ↔ Discord user | v1 | Foundational; manual config bootstrap |
| Passive reaction capture on notifications | v1.x | Stored as signals, never acted on |
| Votes on requests / keep-or-delete polls | v2 | Discord interactions as first voting surface |
| Discussion threads per title | v2 | Discord threads anchored to the title timeline |
| Household preference learning | v2 | Consumes signals accumulated since v1.x |

## Library lifecycle

| Capability | Phase | Notes |
| --- | --- | --- |
| Observe deletions/upgrades (Radarr/Sonarr/Maintainerr events) | v1 | Ingest only |
| Deletion candidate *reports* (unwatched, stale, low-value) | v1.x | Read-only analysis over own store + Arr APIs |
| Protected/ring-fenced content registry | v1.x | Costanza-local list; admin-managed |
| Keep-or-delete household polls | v2 | |
| Feed candidates/exclusions to Maintainerr | v2, gated | Via Maintainerr API/collections; ADR-0003 |
| Quality audit advice (downgrade/upgrade/remux) | v2+ | Library files only; never request-time (Resolute's turf) |

## Subtitles

| Capability | Phase | Notes |
| --- | --- | --- |
| Subtitle status in title timeline (via Bazarr) | v1.x | Read-only |
| Subtitle request workflow ("ask for subs" → Bazarr search) | v2, gated | First and probably only Bazarr write |
| AI subtitle assessment/generation | not ours (for now) | Separate project if ever; different infra profile |

## Stats / metrics

| Capability | Phase | Notes |
| --- | --- | --- |
| Requests made vs watched; per-user request/watch stats | v1 | Read API + Prometheus metrics |
| Title timeline API | v1 | |
| Household taste trends, storage/value metrics | v1.x | Grafana dashboards over API/metrics |

## Admin controls

| Capability | Phase | Notes |
| --- | --- | --- |
| Global notification kill switch + per-channel rate limits | v1 | Day one |
| Event-type allowlist config | v1 | |
| Identity map management | v1 | Config file first; API later |
| Write-tier feature flags (per action type) | v2 | ADR-0006 |
| Audit log of every outbound action | v1 | Notification ledger doubles as audit in v1 |
