# ADR-0011: Downgrade execution — the council decides, Resolute executes against Sonarr

**Status:** accepted; amended 2026-08-13 (fulfils the "dedicated ADR naming
the exact system and verb" required by [ADR-0009](0009-staged-execution.md)
and [council/retention-engine.md](../council/retention-engine.md); moves the
`downgrade` verdict from report-only to a staged executor. Leaves
`delete_candidate` and [ADR-0003](0003-maintainerr-boundary.md) —
Maintainerr as the only deleter — untouched.)

## Amendment (2026-08-13): the objective read is model-derived

Resolute ADR-0003 (alex-matthews/resolute,
`docs/adr/0003-llm-primary-decision-engine.md`, accepted 2026-08-13) makes
the LLM Resolute's primary decision-maker and removes its deterministic
scoring engine. That supersedes this ADR's premise that the evidence seam
returns a formula-derived score. What changes, and what deliberately does
not:

- **The evidence becomes categorical and model-derived.** The numeric
  `objective_score` (a weighted sum) is removed at Resolute's v2 cutover;
  the read returns `worth` (resolution), `confidence`, and `reasons`. The
  reasons are preserved as attributed evidence bullets, subject to the
  presentation layer's normal escaping and length limits — a model-stated
  "why" replaces a formula-stated one, and unlike v1's formula-generated
  reasons it is derived from potentially hostile metadata, so it is data to
  present, never text to trust. No implemented Costanza consumer of
  `objective_score` existed at amendment time, so no runtime migration is
  required; case-assembly code written after this amendment must consume
  the categorical fields only.
- **The objective/household isolation survives its vocabulary.** Resolute
  v2 also dissolves the structured household terms named below
  (`requester_preference`, `franchise_priority`, `storage_pressure` as
  policy knobs) into household-preference prose — but the anti-double-
  counting boundary this ADR draws is preserved *more* strictly, as an
  invocation contract: an objective-worth call receives no household prose,
  requester preferences, storage state, pins, votes, or feedback at all.
- **The snapshot, not determinism, was always the stability mechanism.**
  The read was never re-evaluated inside a case; `cases.evidence_json`
  freezes it at assembly with source attribution, and that is unchanged.
  Resolute additionally audits each worth invocation (model, prompt
  version, evidence hash, validation result, raw output, latency).
- **Degradation is unchanged and now also covers the model.** `worth:
  unavailable` never blocks a case; Resolute maps model unavailability to
  the same value.
- **The execution seam is untouched.** The downgrade executor, its phases,
  kill switches, and this ADR's boundary (Costanza never touches quality
  profiles) are unaffected by Resolute's v2 pivot.

The body below is preserved as accepted; where it describes
`objective_score` or Resolute's deterministic lanes, this amendment
governs.

## Context

The retention engine already emits a `downgrade` verdict, deliberately
report-only: ADR-0009 scopes Costanza's only executor to Seerr
create-request, and ADR-0003 plus the product brief forbid Costanza from
touching quality profiles ("Resolute's turf"). So today the council can
reach a reasoned "downgrade this from 4K" — with evidence, votes, and
pleas — and then a human must re-derive and apply it by hand in the Arrs.

That dead-ends exactly when it matters most. Under storage pressure new
requests are throttled and **reclamation becomes the active loop**; the
payoff principle ADR-0009 established for requests ("the council decides
and it *happens*") is at least as valuable here. Two facts make it
cleanly executable without breaching any boundary:

- **A downgrade keeps the title** (it changes format), so it is a
  *quality* operation — Resolute/Sonarr territory — categorically distinct
  from `delete_candidate`, which *removes* a title and stays with
  Maintainerr. The engine's two verdicts were always a fork; this ADR
  gives each its executor.
- **Resolute already owns the pieces:** the quality-profile write path to
  Sonarr, and a deterministic **objective** UHD-worthiness score for any
  title (`engine/policy.py` produces separate `objective` and `household`
  recommendations).

## Decision

`downgrade` verdicts hand off to **Resolute** as their executor. One
system (**Sonarr**), one verb (**set the title to a downgrade-target
quality profile and reclaim the UHD files**). Costanza never performs the
quality operation itself — it decides and hands off, exactly as it hands
requests to Seerr. Two seams:

### 1. Evidence seam (Resolute → Costanza, read-only)

During evidence assembly (retention-engine step 2), Costanza reads the
title's **objective** UHD-worthiness from Resolute — the `objective` lane
**only** (`objective_score`: visual genre, network tier, era, acclaim),
never `household_score`. Explicitly:

- `household_score` folds in `requester_preference`, `franchise_priority`
  / `title_override`, and `storage_pressure` — the household's *subjective
  voice* and the *storage context*, both of which the council already
  expresses natively (votes, pleas, the Protected Shelf, capped candidate
  selection). Feeding them as evidence double-counts the household and
  pits Resolute's static policy model against Costanza's taste memory.
- `storage_pressure` is circular here: it is the reason the case is open,
  not a per-title property.
- `episode_burden` is a cost proxy; Costanza already holds true
  size-on-disk.

So **Resolute contributes objectivity** ("disregarding storage and who
asked, how much does this title benefit from UHD, and *why*"); **Costanza
contributes subjectivity** (votes, watch record, protections, cost,
context). Resolute's `objective` reasons render verbatim as evidence
bullets alongside Costanza's. The read is snapshotted into
`cases.evidence_json` with source attribution; if Resolute is
unreachable the field degrades to "objective worthiness unavailable" and
never blocks a case.

### 2. Execution seam (Costanza → Resolute), staged — mirrors ADR-0009

- **Phase A (report-only; council-v1 default):** the verdict renders as
  an admin-channel report, now carrying Resolute's dry-run of the exact
  Sonarr change. A human acts or doesn't. (Unchanged trust posture.)
- **Phase B (admin-confirm one-click; behind a flag, ships OFF):** an
  admin-gated, server-side-identity-checked button hands the verdict to
  Resolute's downgrade executor, which applies the Sonarr change exactly
  once (write-ahead audit, UNIQUE per decision).
- **Phase C (hands-free, hard-capped; ships OFF, far future):** only after
  Phase B history proves the thresholds; cap-fallback to Phase B.
- The **executor lives in Resolute** (its own `executors/sonarr_downgrade`
  module), not Costanza. Costanza's no-external-writes allowlist does
  **not** grow — the write verb is Resolute's, so the substrate's write
  discipline is untouched.
- **Kill switches:** Resolute's existing `RESOLUTE_ALLOW_WRITES=false`
  forces its executor to dry-run regardless of phase; Costanza's
  `COSTANZA_READ_ONLY` still governs whether Costanza hands anything off
  at all.
- **Protection precondition:** protected titles are already excluded from
  candidacy (retention-engine step 1) — the Protected Shelf shields UHD
  keeps, not just deletions.
- **Reclaim mechanics** (profile change + cutoff-replace vs. delete-UHD-
  and-regrab-1080p) are Resolute's to specify precisely in a companion
  Resolute ADR; either way the title is retained, only its format changes.

## Consequences

- The `downgrade` line in retention-engine.md moves from "no execution
  path in any specified phase" to "staged executor in Resolute." ADR-0009's
  "requires a new ADR naming the exact system and verb" is satisfied —
  system: Sonarr; verb: downgrade profile + reclaim; executor: Resolute.
- ADR-0003 is intact: `delete_candidate` → Maintainerr; `downgrade`
  (quality replacement, title retained) → Resolute/Sonarr. The two
  verdicts now have two distinct executors.
- Resolute becomes a **bidirectional quality brain** — request-time
  up-selection and retention down-selection — under one policy vocabulary
  and one audit trail. Sonarr gains a programmatic downgrade driver.
- Costanza's boundary holds: it never touches a quality profile; the write
  code path stays absent from its codebase.
- New coupling: Costanza depends on Resolute for evidence (soft, degrades
  gracefully) and, only when Phase B+ is enabled, for execution (hard). A
  Resolute outage degrades cases to "objective worthiness unavailable" and
  downgrade execution to report-only — it never blocks the council.
- Requires a companion **Resolute ADR** specifying the executor and the
  `objective`-worthiness read endpoint; this ADR is the authoritative
  cross-system decision it references.

## Alternatives rejected

- **Extend Costanza to execute the downgrade.** Breaks ADR-0003 / the
  product brief ("never touches quality profiles"), forces Costanza to
  replicate Resolute's scoring, and grows a second write verb the whole
  substrate discipline exists to prevent. The council should decide, not
  operate the Arrs.
- **A standalone downgrader app straddling both.** An anemic orchestrator:
  it re-derives Resolute's scoring or Costanza's evidence, adds a third
  deploy and audit trail, and owns no domain. The decision/execution split
  already exists (council → Seerr executor); a downgrade is that same split
  with a different executor.
- **Feed `household_score` as evidence.** Double-counts the household's
  live voice, imports storage-pressure circularity, and pits Resolute's
  static household model against Costanza's taste memory. Objective lane
  only.
- **Route downgrades through Seerr.** Seerr is forward-only request
  territory with no concept of an existing file's quality. A downgrade is a
  library-quality operation — wrong system.
