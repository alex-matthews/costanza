# Retention decision engine — one engine, two skins

*Media Court* (evidence-based case for one title) and *Which Stays*
(head-to-head) are presentation skins over **one** engine: assemble
evidence → open a case → collect votes and pleas → persist a reasoned
outcome. Build it once; the skins differ only in candidate count, vote
vocabulary, and tone.

The skin pattern is deliberately extensible beyond retention: the
**divided-interest playoff** (v1.x, capability map) reuses this engine on
the acquisition side — when gauging splits the household, a case opens
with the contested titles, votes and pitches instead of pleas, and the
verdict feeds the proposal machine rather than a retention decision.

## Pipeline

```
candidate selection ─► evidence assembly ─► case open (skin) ─► deliberation
        │                                                            │
   (policy caps)                                    votes + pleas + thread
                                                                     │
                                              verdict ─► decisions row ─► handoff
```

### 1. Candidate selection (deterministic)

Inputs, all substrate queries: unwatched-since-import age, requester
watch-through, size on disk (event attrs), last watch recency, protection
status (protected titles are **excluded**, surfaced as "protected because
<reason>" instead), Maintainerr rule exposure where observable from
ingested events. Candidate *ordering* may later use internal scoring —
that score is never displayed per person and never published
(ADR-0005 addendum). Cadence caps from [policy.md](policy.md) apply
(default: one open Which-Stays per week, two open Courts).

### 2. Evidence assembly

A snapshot (`cases.evidence_json`) built from the per-title timeline:

- request chain: who asked, when, how long to available;
- watch record: completions per member (aggregate framing), last watched;
- cost: file size, quality tier, upgrade history;
- reacquisition difficulty heuristic (recent availability of the release
  — conservative, explainable);
- protection and prior-decision history (a title acquitted in court
  carries its precedent);
- TMDB card facts ([metadata.md](metadata.md)).

The snapshot embeds source event ids for auditability
([domain-model.md](domain-model.md)).

### 3. Deliberation

- **Court:** vote vocabulary `keep | delete_candidate | downgrade |
  protect`; any member may file a plea (modal, free text). Pleas are
  first-class rows and quoted verbatim in the verdict summary.
- **Which Stays:** `title A | title B | both stay`. "Both stay" winning is
  a fine outcome — the game exists to provoke the conversation, not to
  guarantee a deletion.
- Kids vote on neither skin's `delete_candidate` outcomes (OQ-11);
  quorum and duration come from policy; admin veto is public with a
  reason and recorded as a taste signal.

### 4. LLM boundary (carried from ADR-0005, with the reset addendum)

- The engine is fully functional with the LLM off — deterministic
  evidence, human pleas, human votes.
- When enabled (behind the litellm gateway, schema-validated): the LLM
  may **summarize pleas** and **surface tradeoffs** ("large file, watched
  once, but two pleas cite rewatch intent"). It never scores or ranks
  *people*, never generates the verdict, never triggers writes.
- Member-authored text (pleas, pitches) is personal: aggregate-only
  prompts until a local model route exists (OQ-13).

### 5. Outcome and handoff

Every verdict persists a `decisions` row with reason, trigger, vote
tally, and policy version. Then, by kind:

- `keep` — recorded; the precedent shields the title from re-candidacy
  for a policy-defined cooldown.
- `protect` — creates a `protections` row (reason required).
- `downgrade` — **report-only**: a decision record rendered as an
  admin-channel report; a human acts (or doesn't) in the Arrs. There is
  no downgrade execution path in any currently specified phase —
  executing one would need a dedicated ADR naming the exact system and
  verb, and it sits next to Resolute's calibration territory
  (ADR-0009 scopes the executor to create-request only).
- `delete_candidate` — **Costanza never deletes**
  ([ADR-0003](../adr/0003-maintainerr-boundary.md) unchanged). Council
  v1: the verdict renders as a human-readable report in the admin
  channel; a human acts (or doesn't) in Maintainerr. v2 (gated): feed
  candidates/exclusions through Maintainerr's own mechanisms, only after
  the protection-sync precondition — every Costanza protection must be
  confirmed as a Maintainerr exclusion before any candidate feed goes
  live, else the feed aborts.

## Why one engine matters

Two separate features here would drift: different evidence, different
fairness rules, different audit trails. One engine means the cap logic,
the protection guard, the plea handling, the LLM boundary, and the
Maintainerr handoff are each written and tested once.
