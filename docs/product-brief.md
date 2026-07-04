# Product brief

## What Costanza is

Costanza is the **household media event layer** for a self-hosted media stack.
It sits beside Seerr, Radarr, Sonarr, Tautulli, Plex, Bazarr, and Maintainerr,
consumes their webhooks and APIs, and produces three things:

1. **A durable, canonical event history** — every request, grab, import,
   availability change, upgrade, deletion, and watch, correlated per media
   item and per household member.
2. **Low-noise household communication** — real-time notifications for the
   few events people actually care about, and scheduled digests for
   everything else. Discord is the first channel, not the identity.
3. **Household context** — who requested what, who watched it, what sits
   unwatched — which later phases (recommendations, voting, lifecycle
   advice) consume instead of re-deriving.

The name-appropriate framing: Costanza watches everything, remembers
everything, and tells everyone about it — but in v1 it *does* nothing.

## Target users

- **Household members (4–8, mixed engagement):** get told when their request
  is ready, see a weekly digest of what's new and what people watched, and
  eventually vote/react on requests and deletions.
- **The admin (you):** gets an operational view — request-to-watch
  conversion, dead requests, noisy sources — and a foundation to automate
  lifecycle decisions later without giving any tool write access yet.

## V1 outcomes

By the end of v1, deployed in the cluster:

- All Seerr, Radarr, Sonarr, and Tautulli webhooks land in Costanza, are
  normalized into one event schema, and are persisted with idempotent dedupe.
- Events are correlated into per-title timelines (requested → grabbed →
  imported → available → watched) and mapped to household members via an
  explicit identity map (Seerr user ↔ Plex/Tautulli user ↔ Discord user).
- Discord receives: per-event notifications for a curated allowlist of event
  types (request approved, request available, request failed), and a weekly
  household digest (new arrivals, most-watched, requests still unfulfilled).
- A read-only HTTP API exposes event timelines and basic stats; Prometheus
  metrics exposed for observability.
- A reconciliation job repairs missed webhooks by polling source APIs, so
  the event store can be trusted.
- Zero writes to any external system. A global notification kill switch and
  per-channel rate limits exist from day one.

**Definition of "genuinely useful":** the household stops asking "is it on
Plex yet?" and the admin can answer "did anyone actually watch the things we
requested last quarter?" from one API call.

## Non-goals (v1)

- No auto-requesting, no deletion, no quality changes, no Seerr/Arr writes.
- No voting/quorum mechanics (reactions may be *recorded* as raw signals,
  never acted on).
- No LLM anywhere in v1. The recommendation phase adds it behind the
  boundaries in [ADR-0005](adr/0005-llm-and-recommendation-boundary.md).
- No subtitle workflows (Bazarr integration is a later read-only add).
- No web UI. Discord + API + (existing) Grafana are the v1 surfaces.
- No multi-tenant / public-instance ambitions. One household, one cluster.
- Not a general notification router — cluster alerts and non-media webhooks
  are Chaski/Apprise territory ([ADR-0004](adr/0004-chaski-boundary.md)).

## Scope pushback (prompt interrogation)

Recorded here so the reasoning survives:

- **The prompt describes at least four products** (notifier, recommender,
  social hub, librarian). Building them concurrently is how the first
  Costanza died as feature soup. The unifying primitive they all share is
  *the durable, identity-mapped event history* — so v1 builds exactly that
  plus its cheapest visible payoff (notifications/digests).
- **"Auto-request on household interest" is a write with taste risk**; it
  needs interest signals that don't exist until reactions/votes have
  accumulated. It cannot be v1 by construction, not just by caution.
- **Subtitle AI generation is a different product** (media processing, GPU,
  quality QA) wearing the same trench coat. Cut entirely; revisit as its own
  project if Bazarr's ecosystem doesn't solve it first.
- **Quality/format advice overlaps Resolute's calibration territory.**
  Costanza limits itself to *library audit* framing (existing files), never
  *request-time* decisions, and even that is v2+.
- **"Ephemeral state may be enough" is wrong for this scope** — digests,
  dedupe, identity, and any future votes/preferences all need history that
  source systems don't retain faithfully. See
  [ADR-0002](adr/0002-durable-store-not-cache-first.md).
