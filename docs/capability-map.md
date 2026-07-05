# Capability map

Phases: **substrate** (shipped — observe + notify, the evidence layer),
**council v1** (the product: Lobby, Council, protections, staged
execution), **council v1.x** (additive once the loop is proven), **v2**
(wider write scopes, each gated by ADR-0006/0009), **not ours** (lives
elsewhere permanently).

## Substrate (shipped)

| Capability | Notes |
| --- | --- |
| Ingest + normalize Seerr, Radarr, Sonarr, Tautulli webhooks | Per-source normalizers → canonical event schema; 202-always; idempotent |
| Correlated per-title timeline (request→available→watched) | The evidence assembler every council feature reads |
| Household identity map (Seerr ↔ Plex/Tautulli ↔ Discord) | The council's member registry already exists |
| Real-time Discord notifications, curated allowlist + weekly digest | Exactly-once ledger, kill switch, rate limits |
| Reconcile / prune / identity-sync jobs; read-only source clients | Honest per-source guarantees matrix |
| Read API + `/metrics`; request/watch stats | Wrapped and accountability inputs |

## Council v1 (the product)

| Capability | Notes |
| --- | --- |
| Lobby proposal cards with DW / Maybe / No / Already Seen | Discord buttons; identity-map attribution ([ADR-0008](adr/0008-discord-interactions-surface.md)) |
| Interest accumulation + policy thresholds with provenance | Versioned policy YAML ([council/policy.md](council/policy.md)) |
| Proposal/discussion threads | One thread per proposal/case |
| Retention decision engine, two skins (Media Court, Which Stays) | One engine; Which Stays capped ~1/week ([council/retention-engine.md](council/retention-engine.md)) |
| Protected Shelf with human reasons | Costanza-owned registry; Maintainerr consumes later |
| Decisions ledger with reasons + policy provenance | The council's memory |
| Phase A execution: admin-confirm one-click Seerr request | Tier 3, isolated flagged executor, audit rows ([council/execution.md](council/execution.md)) |
| Phase B execution: threshold auto-request | Tier 4, behind flag, hard caps, ships OFF |
| TMDB metadata client + cache (posters, runtime, trailers) | Read-only ([ADR-0010](adr/0010-tmdb-metadata-dependency.md)) |
| Request accountability + watch-debt check-ins | Playful, DM-first, opt-out; shame-free release |
| Library Wrapped (weekly/monthly) | Superlatives that provoke conversation, nothing streak-shaped |

## Council v1.x (additive)

| Capability | Notes |
| --- | --- |
| Taste memory / preference profiles | Derived from accumulated interest, votes, vetoes, watches |
| **Premiere Lobby**: curated upcoming-release proposal cards | TMDB calendar/discover sourcing + deterministic suppression gate (taste-filtered once taste memory exists; conservative franchise/genre matching before); policy-capped cards/week ([domain-model.md](council/domain-model.md), OQ-16) |
| Deferred interest: "remind us later once reviews mature" | `deferred` proposal state with snapshotted re-surface conditions (review maturity via OQ-15, dates, availability) |
| Divided-interest playoff (third skin of the decision engine) | When gauging splits the household, the case engine runs a head-to-head/vote-off for acquisition, same machinery as Which Stays ([retention-engine.md](council/retention-engine.md)) |
| Watch-next scheduling ("what do we watch tonight?") | Kids vote here (OQ-11) |
| Additional notification channels (ntfy, Apprise, email) | New notifier adapters, no core change |
| Per-member notification preferences / DM routing | Identity map already supports it |
| Bazarr subtitle status in timelines | Read-only ingest |
| Deterministic "you might like" candidates | No LLM required |

## v2 (wider writes, gated)

| Capability | Notes |
| --- | --- |
| Feed deletion candidates/exclusions to Maintainerr | Via its API/collections; exclusion-sync precondition; ADR-0003 unchanged |
| LLM plea summaries + tradeoff surfacing, rec ranking/explanation | Behind litellm; aggregate-only prompts until a local route; never public per-member scoring (ADR-0005) |
| Library quality audit advice (downgrade/upgrade/remux) | Library files only; never request-time (Resolute's turf) |
| Subtitle request workflow ("ask for subs" → Bazarr search) | First and probably only Bazarr write |

## Not ours

| Capability | Lives in |
| --- | --- |
| Deletion execution, "leaving soon" collections | Maintainerr (ADR-0003) |
| Request-time quality decisions (1080p vs 2160p) | Resolute |
| Acquisition, files, disk truth | Radarr/Sonarr |
| Watch truth (sessions, history) | Tautulli |
| Request UI, discover, user accounts/quotas | Seerr |
| Stateless webhook relay / non-media notification glue | Chaski/Apprise (ADR-0004) |
| AI subtitle generation | A different product entirely |
