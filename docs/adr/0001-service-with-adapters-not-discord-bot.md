# ADR-0001: Service with channel adapters, not a Discord bot

**Status:** accepted

## Context

Old Costanza was a Discord bot + webhook receiver in one tangle; bot
concerns leaked into domain logic. Prior art (Requestrr, Doplarr) shows
Discord-first designs age badly: coupled to one interaction model, hard to
test, hostage to Discord library churn. Meanwhile the household genuinely
lives in Discord, and later phases (reactions, votes, threads) need a
gateway bot, not just webhook posts.

## Decision

Costanza is a **headless domain service**. All channel interaction goes
through a **notifier port** (send message, edit message, capture
interaction signals). Discord is the first adapter and runs in-process as a
supervised async task, but:

- Core modules import the port interface, never `discord.py`.
- Ingestion and jobs never await Discord; a dead bot degrades to
  "notifications queued in ledger", not "webhooks lost".
- Interactive input (reactions, later slash commands/votes) arrives as
  normalized *signal events* through the same port, so a future web UI or
  ntfy channel is additive.

Discord is therefore **secondary UX**: the primary product surface is the
event store + API; Discord is the default renderer of it.

## Consequences

- Adding ntfy/Apprise/email later is a leaf change (validated by prior art:
  Notifiarr/Apprise demand).
- Slightly more ceremony in v1 (a port interface with one implementation) —
  accepted cost.
- If discord.py churn ever becomes painful, the adapter can move to its own
  process speaking to the read API + a small internal send API without core
  changes.

## Alternatives rejected

- **Discord bot first:** repeats the old repo's failure; blocks non-Discord
  household members and future surfaces.
- **Separate bot microservice now:** premature; two deployments and an
  internal API for one consumer.
