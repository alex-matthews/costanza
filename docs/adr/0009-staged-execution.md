# ADR-0009: Staged execution — the vote→request loop ships in council v1

**Status:** accepted (amends ADR-0006: concretizes Tier 3/Tier 4 for the
Seerr create-request action; the tier table and cross-cutting rules stand)

## Context

ADR-0006 classified every write into tiers and the substrate shipped
Tiers 0–1 with *no external write code path at all* — right for earning
trust, but the tier framing pushed all interaction to a vague "v2",
structurally biasing the roadmap toward broadcast. The reset's product
insight: **the vote→request loop is the payoff.** "Two Definitely-Wants
and it shows up" is the moment the council feels alive; defer it
indefinitely and the product is a poll that never pays out. The risk
(taste-risky automation, bandwidth waste, household annoyance) is what
ADR-0006's gates exist to manage — not a reason to not build the loop.

## Decision

Execution ships in council v1, staged, as one isolated executor
([council/execution.md](../council/execution.md)):

- **Phase A (Tier 3, default ON in council v1):** threshold- or
  vote-triggered request decisions render as an **admin-confirm one-click
  button** (admin-gated via the identity map, re-checked server-side).
  One press = one Seerr create-request, exactly once
  (UNIQUE per decision), write-ahead audit row before the HTTP call.
- **Phase B (Tier 4, built alongside, ships OFF):** hands-free
  auto-request when thresholds fire, behind a policy flag
  (`phase_b_enabled: false` shipped), hard-capped
  (`max_auto_requests_per_week`, executor-enforced), falling back to
  phase A at the cap. Graduates only after phase A history proves the
  thresholds; while off, the admin digest reports what it *would* have
  done (dry-run calibration, the house pattern).
- **Instant demotion:** `COSTANZA_READ_ONLY=true` forces all execution
  into dry-run regardless of flags (ADR-0006's fire alarm, now with a
  concrete subject).
- Scope of the executor is exactly **create request** — one system
  (Seerr), one verb. Never approve/decline (admin policy + Resolute's
  flow), never delete (ADR-0003), never profile changes (Resolute's
  turf). Council downgrade verdicts are **report-only**; if downgrade
  execution is ever wanted, it requires a new ADR naming the exact
  system and verb — it does not inherit this seam.
- The no-external-writes constraint test lifts by exactly this one module
  ([council/constraint-amendments.md](../council/constraint-amendments.md)).

## Consequences

- ADR-0006's "v1 ships Tiers 0–1 only / no write code path exists" line
  is superseded for this single, designed seam; every other cross-cutting
  rule there (audit before execution, per-action flags, caps, opt-in for
  Tier 4) now has its first concrete instance.
- Seerr gains a second writer besides humans and Resolute — but through
  its own request pipeline (quotas, permissions, approval flow), so Seerr
  remains the system of record for requests.
- The executor is a standing temptation to add "just one more verb"; the
  allowlist guard test and this ADR are the fence.

## Alternatives rejected

- **Defer all writes to v2 (status quo):** the council becomes a poll
  with no payout; participation decays before the data that would justify
  automation ever accumulates.
- **Hands-free from day one:** taste-risky automation with zero observed
  threshold history; exactly the Janitorr-class surprise ADR-0006 exists
  to prevent.
- **Deep-link into Seerr instead of executing:** breaks the moment ("go
  log into another app" is not a payoff), loses the audit trail, and
  still requires the admin to re-find the context.
