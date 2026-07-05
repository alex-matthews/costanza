# ADR-0006: Tiered write-safety and approval model

**Status:** accepted (Tier structure binds all future phases)

## Context

Costanza's roadmap ends with actions that can waste bandwidth (auto-request),
annoy the household (spam), or destroy data indirectly (deletion candidates).
The stack's scary prior art is cleanup daemons with default-on writes. The
house pattern (Resolute) is shadow-mode-first with an explicit executor gate.

## Decision

Every capability is classified into a tier. Tiers are enforced in one place
(an action gateway module), feature-flagged **per action type**, and every
Tier ≥ 1 action writes an audit record before execution.

| Tier | Meaning | Examples | Gate |
| --- | --- | --- | --- |
| 0 | Observe | ingest, correlate, stats API | none |
| 1 | Notify | Discord messages, digests | kill switch + rate limits + ledger dedupe |
| 2 | Propose | deletion-candidate reports, rec digests, keep/delete polls | flag per proposal type; writes only to own store + messages |
| 3 | Execute with approval | feed Maintainerr collections/exclusions, Bazarr subtitle search, manual "request this" relay to Seerr | explicit human approval **per action or per batch**, recorded with who/when; dry-run mode is the default until flipped per action type |
| 4 | Auto-execute | quorum auto-request in Seerr | graduates from Tier 3 only after observed dry-run history; hard caps (e.g. max N auto-requests/week); per-user opt-in; instant demotion switch |

Cross-cutting rules:

- **The substrate ships Tiers 0–1 only.** No code path to external
  writes exists in the substrate binary (not just flagged off — not
  built). *Amended by [ADR-0009](0009-staged-execution.md) (2026-07-05):
  council v1 adds exactly one designed seam — the Seerr create-request
  executor, phase A (Tier 3, admin-confirm) on by default and phase B
  (Tier 4, hard-capped) shipping OFF. Everything else in this table and
  these rules binds unchanged, and ADR-0009 is that table's first
  concrete instance.*
- Approval UX rides the notifier port (Discord buttons/reactions from
  admin-mapped identities in v2), but approval *state* lives in Costanza's
  store, not in Discord.
- Destructive-adjacent actions (anything feeding deletion) additionally
  require the ADR-0003 exclusion-sync check to pass.
- A single global `COSTANZA_READ_ONLY=true` override forces Tiers ≥ 2 into
  dry-run regardless of individual flags — the fire-alarm setting.
- Rate limiting and idempotency apply to Tier 1 like everything else:
  notification storms are treated as a write-safety failure, not a cosmetic
  one.

## Consequences

- Some ceremony per new capability (classify, flag, audit) — deliberate
  friction.
- The tier table doubles as the roadmap's safety review checklist;
  [ADR-0009](0009-staged-execution.md) instantiates Tier 3/Tier 4 for the
  vote→request loop and [council/execution.md](../council/execution.md)
  carries the executor mechanics (write-ahead audit, caps, instant
  demotion).

## Alternatives rejected

- **Per-integration allowlists only:** protects systems, not the household
  (spam and bad auto-requests hit people, not APIs).
- **Everything-manual forever:** wastes the accumulated signal; the point
  of the ledgered history is to eventually earn narrow automation.
