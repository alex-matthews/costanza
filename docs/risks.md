# Risk register

Severity × likelihood is post-mitigation. Phases: substrate (shipped), council v1, v2.

| # | Risk | Phase | Mitigation | Residual |
| --- | --- | --- | --- | --- |
| R1 | **Notification spam** (retry storms, normalizer bug, digest loop) annoys household and burns trust permanently | v1 | Ledger idempotency, per-channel rate limits, event-type allowlist default-minimal, kill switch, private-channel soak before household exposure | Low |
| R2 | **Privacy: watch history is sensitive** (who watched what, when). Store leak or over-sharing in digests embarrasses household members | v1 | Data stays in-cluster on encrypted-at-rest PVC; digests show household aggregates by default, per-user detail only where that user is the audience; API behind bearer token, cluster-internal | Low-Med |
| R3 | **Webhook endpoint abuse** (unauthenticated posts, payload bombs) | v1 | Per-source shared secrets, body size caps, cluster-internal service (no ingress), auth-failure metric + alert | Low |
| R4 | **Accidental deletion** | v2 | Structurally impossible today (no deletion code path in any phase, ADR-0003); council verdicts are reports until the gated v2 Maintainerr feed (exclusion-sync precondition, Tier 3 approvals, dry-run default) | Low now; revisit at v2 |
| R5 | **Unwanted auto-requests** waste disk+bandwidth and erode trust | council v1 (phase B) | ADR-0009: phase B ships OFF, hard weekly caps, dry-run reporting while off, phase A admin-confirm history required before graduation, instant demotion via COSTANZA_READ_ONLY | Low while B is off; Med at graduation |
| R6 | **Prompt injection via media metadata** (titles/overviews steering LLM output) | v2 | ADR-0005: data-not-instructions framing, schema validation, candidate-set whitelist, no tool use, no write influence | Low-Med at v2 |
| R7 | **LLM cost/reliability creep** | v2 | litellm gateway spend caps; feature works with LLM off; per-call audit rows | Low |
| R8 | **Missed webhooks silently corrupt history** (source down, secret rotated, Costanza redeploying) | v1 | Reconciliation jobs are ground truth; `origin=reconcile` events flag gaps; outbox never drops accepted payloads | Low |
| R9 | **SQLite single-replica availability** (node drain = brief ingest outage) | v1 | Sources retry webhooks; reconcile heals anything missed; acceptable for household SLO | Accepted |
| R10 | **Data loss of household-only state** (signals/votes/ledger exist nowhere else) | v1 | volsync backups of PVC; restore drill in rollout step 6 | Low |
| R11 | **Maintenance burden / second-system feature soup** — the thing that killed Costanza v1 | all | Phase gates in capability map; ADR boundaries; tier ceremony makes scope creep visible; one process, no broker, no UI | Med (honest) |
| R12 | **Upstream payload drift** (Seerr/Arr webhook schema changes on upgrade) | all | `source.unknown` events surface novelty instead of dropping it; versioned fixtures; Renovate-driven upgrades reviewed against normalizer tests | Med |
| R13 | **Discord dependency risk** (lib churn, token leak, API policy) | v1 | Adapter isolation (ADR-0001); token in ExternalSecret; bot has minimal intents/permissions (send/read-reactions in two channels) | Low |
| R15 | **Social harm from the council itself** (deletion anxiety from retention games, punitive-feeling accountability, LLM judging family members' pleas) | council v1 | Which-Stays capped ~1/week; accountability playful + opt-out + DM-first; watch-debt release is shame-free default; LLM summarizes but never scores people, aggregate-only prompts until a local route (ADR-0005/OQ-13); admin veto public with reason | Med — the honest product risk |
| R14 | **Identity map staleness** (new household member unmapped → their events invisible/misattributed) | v1 | identity_sync job flags unmapped external users into the admin digest | Low |
