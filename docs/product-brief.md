# Product brief

## What Costanza is

**Costanza is the household media council: the place where a family
decides, debates, and remembers what their library is for.** Automation
executes elsewhere — Seerr requests, the Arrs acquire, Maintainerr
deletes, Resolute picks quality. Costanza owns the three things none of
them have: **participation, reasons, and memory.**

It is built as two layers of one service:

- **Substrate (shipped):** a durable, canonical event history — every
  request, grab, import, availability change, upgrade, deletion, and
  watch, correlated per title and per household member, with exactly-once
  notification plumbing. This is the evidence base and the memory. It is
  deliberately not the product; on its own it is a well-behaved notifier.
  Record: [handoff.md](handoff.md), [build-notes.md](build-notes.md).
- **Council (the product, designed in [council/](council/)):** proposals,
  interest, votes, cases, pleas, protections, and decisions — the loops
  below.

## The core loops

1. **The Lobby.** Proposal cards — title, poster, why-suggested, who it
   suits, time commitment, likely format — with four buttons: **Definitely
   Want / Maybe / No / Already Seen**, and a discussion thread. Cards come
   from members first, and later (v1.x) from the **Premiere Lobby**: a
   curated, policy-capped feed of upcoming releases filtered through what
   the household has loved and flopped — smart enough not to surface what
   most of the family would call rubbish, honest enough to stay
   conservative until taste memory has real data. Interest
   accumulates; policy thresholds convert it into action (e.g. one admin
   Definitely-Want → request; two household Definitely-Wants → request;
   three Maybes → a proper vote; a Maybe stale for 30 days → archive;
   "remind us later once reviews land" → a deferred card that returns
   when its condition is met).
   Thresholds are versioned policy config with provenance — every
   threshold-triggered action records the policy version that fired it
   ([council/policy.md](council/policy.md)).
2. **The Council.** Structured household decisions: request it? keep it?
   delete it? downgrade from 4K? protect it forever? watch it next?
   Participation is the point; automation is the byproduct.
3. **Retention games.** *Which Stays* (head-to-head, capped at about one
   per week) and *Media Court* (an evidence-based case for one title) are
   **one decision engine with two skins**: both assemble evidence from the
   event history (who requested it, who watched it, size, quality, how
   hard it is to reacquire, Maintainerr rule exposure), collect votes and
   pleas, and persist a reasoned outcome
   ([council/retention-engine.md](council/retention-engine.md)). Costanza
   never deletes — Maintainerr remains the only executioner
   ([ADR-0003](adr/0003-maintainerr-boundary.md)).
4. **The Protected Shelf.** A first-class protection registry with human
   reasons — comfort watch, family favorite, kids, sentimental, hard to
   reacquire, demo material, seasonal, admin override. Costanza owns the
   reason; Maintainerr later consumes the result as exclusions.
5. **Accountability & memory.** Request accountability (playful, never
   punitive, opt-out-able), watch-debt check-ins ("still keen, downgrade,
   or release?" — low-frequency, DM-first, with a shame-free release
   default), taste memory learned from every signal, and **Library
   Wrapped** as the fun weekly/monthly face of all of it.

The payoff loop is designed in, not deferred: **the moment two people
Definitely-Want something and it shows up is the moment the council feels
alive.** Execution is staged ([ADR-0009](adr/0009-staged-execution.md),
[council/execution.md](council/execution.md)): phase A ships with
admin-confirm one-click execution into Seerr; phase B (hands-free
thresholds, hard-capped) exists behind a flag and ships OFF.

## Where people live: Discord — as an adapter

The household lives in Discord, so Discord interactions (buttons, selects,
modals, threads) are the v1 participation surface, and Discord user ids
resolved through the identity map are the v1 vote-auth model
([ADR-0008](adr/0008-discord-interactions-surface.md),
[council/interactions.md](council/interactions.md)). But Discord is an
adapter, never the product: council state lives in Costanza's store, the
read API can drive any future surface, and a dead bot degrades to "votes
pause" — never "history lost".

## Target users

- **Household members (4–8, mixed engagement, including kids):** propose,
  vote with a button press, defend a title in Media Court, see Wrapped.
  Working defaults ([open-questions.md](open-questions.md) OQ-11): all
  mapped members vote with weight 1; kids vote on watch-next but not
  deletions; the admin veto is public, carries a reason, and is itself
  recorded as a taste signal.
- **The admin:** confirms executions with one click, curates policy
  thresholds in git, and keeps the ops view (dead requests, unmapped
  users, reconcile gaps) the substrate already provides.

## Outcomes that matter

- Requests stop being a black box: proposals show who wanted something and
  what happened to it, end to end.
- Deletion stops being scary: nothing leaves without a case, a vote, or a
  protection reason on record — and Maintainerr does the deleting.
- The library develops a memory: taste signals, decisions with reasons,
  and Wrapped make the household's history legible and fun.

## Non-goals

- Costanza never deletes media and never touches quality profiles
  (ADR-0003; request-time quality is Resolute's territory — see
  [system-boundaries.md](system-boundaries.md)).
- No LLM in the council loop until the loop works without one; after
  that, the LLM summarizes pleas and surfaces tradeoffs behind the
  litellm gateway — it never publicly scores individual family members,
  never triggers writes, and member-authored text stays out of external
  routes until a local model route exists
  ([ADR-0005](adr/0005-llm-and-recommendation-boundary.md)).
- No web UI (the read API + Discord cover v1); no subtitle workflows; no
  multi-tenant ambitions; not a general notification router — cluster
  alerts and non-media webhooks are Chaski/Apprise territory
  ([ADR-0004](adr/0004-chaski-boundary.md)).
- No engagement mechanics for their own sake: no login streaks, no public
  shame leaderboards. Badges and superlatives exist only where they
  provoke conversation (Wrapped); accountability stats are DM-first and
  opt-out-able; retention games are capped because deletion theater at
  high frequency breeds anxiety and mute buttons.

## Scope pushback (recorded so the reasoning survives)

- **The original prompt described four products** (notifier, recommender,
  social hub, librarian) and the first build ratified "event layer first,
  social later" — defensible sequencing that structurally produced a
  notifier as the visible product. The reset keeps the event layer as
  substrate and recenters the product on the council. The substrate was
  the hard, vision-neutral majority of the work; nothing built is wasted.
- **Auto-request is taste-risky automation** — which is why it is staged
  behind admin confirmation first and hard caps later, not why it should
  be deferred indefinitely. The vote→request loop is the product's
  payoff.
- **Subtitle AI is a different product** (media processing, GPU, QA)
  wearing the same trench coat. Cut entirely.
- **Quality/format advice overlaps Resolute's calibration territory.**
  Costanza limits itself to *library audit* framing (existing files),
  never request-time decisions; a downgrade decided by the council is
  executed through the same staged executor discipline, never by touching
  profiles directly.
- **"Ephemeral state may be enough" is wrong for this scope** — votes,
  reasons, protections, and taste memory exist nowhere else and are
  unreconstructable. See
  [ADR-0002](adr/0002-durable-store-not-cache-first.md).
