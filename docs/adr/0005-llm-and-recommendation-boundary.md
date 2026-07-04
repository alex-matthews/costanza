# ADR-0005: LLM is optional garnish behind the litellm gateway, never load-bearing

**Status:** accepted (constrains v1.x/v2; v1 contains no LLM)

## Context

The roadmap wants AI-assisted recommendations and possibly LLM-written
digest prose. Prior art (Recommendarr/Suggestarr) shows the failure modes:
hallucinated titles, unbounded API spend, recommendations nobody asked for.
Resolute already established the house LLM discipline (optional, bounded,
schema-validated, audited, system works with it off). The cluster has a
litellm gateway in the `ai` namespace. Additional hazard specific to
Costanza: its inputs include internet-derived text (titles, overviews,
review snippets) — prompt-injection carriers — and its outputs eventually
influence requests and deletions.

## Decision

- **v1 ships zero LLM calls.** Digests are template-rendered.
- All future LLM traffic goes through the **litellm gateway** (model
  routing, spend caps, logging live there), never direct to providers.
- **Deterministic-first pipeline:** candidate generation, filtering, and
  eligibility are deterministic (watch history, watchlists, signals, TMDB
  metadata). The LLM may only **rank, group, and explain** within the
  candidate set, returning schema-validated output; any title not in the
  input candidate set is dropped on validation.
- **LLM output never triggers writes.** Auto-request quorum math (v2) is
  deterministic over stored signals; the LLM at most decorates the
  notification about it.
- **Injection posture:** third-party metadata is data, never instructions —
  delimited, length-capped, and the response schema rejects anything but
  the expected structure. No tool-use given to the model.
- **Privacy:** litellm may route to external providers; household watch
  history is sensitive. Recommendation prompts carry aggregate/anonymized
  context (household-level tallies, not "Alice watched X at 2am") unless
  the configured route is a local model. Per-user personalization prompts
  require an explicitly local-model route or per-user opt-in.
- Every call and validated response is recorded (model, cost, latency,
  outcome) in the store — same calibration ethos as Resolute.

## Consequences

- Recs quality is bounded by deterministic candidate generation — fine;
  that's also the anti-hallucination guarantee.
- A "recs are boring" complaint is solved by better signals, not by giving
  the model more rope.

## Alternatives rejected

- **LLM-first recommender:** hallucination + injection + cost exposure for
  marginal quality gain at household scale.
- **Direct provider SDK calls:** bypasses the cluster's existing spend and
  routing controls.
