# ADR-0003: Maintainerr owns deletion; Costanza owns judgment

**Status:** accepted

## Context

Maintainerr already runs and does rule-based retention: rule → collection →
"leaving soon" visibility in Plex → deletion. Its rules can't express
household context ("requested by someone who never watched it", "two people
voted keep", "protected because it's the kids' comfort show"). Costanza will
have exactly that context. The tempting failure mode is Costanza growing its
own deleter — the Janitorr/Decluttarr surprise-deletion anti-pattern.

## Decision

**Costanza never deletes media, in any phase.** The division:

- **v1:** Costanza only ingests deletion-related events (Arr delete
  webhooks; Maintainerr activity if observable) into timelines/digests.
- **v1.x:** Costanza produces *reports*: deletion candidates and a
  Costanza-local protected registry. Humans act on them manually in
  Maintainerr (or don't).
- **v2 (gated, Tier 3 in ADR-0006):** Costanza feeds Maintainerr through
  its API — populating candidate collections and exclusion lists — after
  explicit admin approval per batch. Maintainerr's own countdown/"leaving
  soon" flow remains the last line of defense and the only executor.
- Protected registry semantics: protection in Costanza *must* be reflected
  as a Maintainerr exclusion before any candidate feed goes live; if the
  sync can't confirm the exclusion, the candidate feed aborts.

## Consequences

- Two systems hold retention opinion (Maintainerr rules + Costanza
  judgment). Acceptable: Maintainerr stays authoritative; Costanza's input
  arrives only through Maintainerr's own mechanisms, so there is exactly one
  deletion path to reason about.
- Costanza needs Maintainerr API stability only at the collection/exclusion
  surface, verified at v2 time (open question OQ-4).

## Alternatives rejected

- **Costanza deletes via Arr APIs directly:** duplicates a running,
  Plex-visible, countdown-capable executor and doubles the blast-radius
  surface.
- **Replace Maintainerr:** rebuilding scheduling/collection UX for zero
  household benefit.
