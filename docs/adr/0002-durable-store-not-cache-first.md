# ADR-0002: Durable SQLite store, not cache-first state

**Status:** accepted

## Context

The prompt floated Dragonfly/Redis-style ephemeral state "if truth can be
reconstructed from source systems". Interrogating that premise: it can't.

- **Watch events:** Tautulli retains history, but correlation *at event
  time* (which request this fulfilled, who the user mapped to then) is lossy
  to reconstruct later.
- **Notification ledger:** "did we already tell the household about this?"
  is reconstructable from nowhere. Losing it means re-spamming on every
  restart — the exact noise failure v1 exists to prevent.
- **Digests:** need "what happened since the last digest", a durable cursor
  plus history.
- **Signals/votes/preferences (v1.x+):** exist only in Costanza; losing
  them destroys the learning the whole roadmap depends on.
- **Audit:** ADR-0006's write-safety model is meaningless without a durable
  action log.

## Decision

**SQLite in WAL mode on a volsync-backed PVC is the system of record.**
Canonical events, media entities, identity map, notification ledger,
signals, and job cursors are durable. Raw payload archive is durable but
pruned (default 30 days). No Redis/Dragonfly dependency in v1; in-process
caching suffices for a single replica. Any future cache tier must be
lose-able without behavior change beyond latency.

## Consequences

- Single-writer constraint → single replica, `Recreate` strategy. Fine for
  household scale and already the house pattern (Resolute, most stack apps).
- Backup/restore rides existing volsync machinery; restore drill belongs in
  the rollout checklist.
- Migrations needed from day one (small, e.g. sqlite + hand-rolled
  versioned migrations or alembic).

## Alternatives rejected

- **Cache-first Dragonfly:** fails the ledger/signals/audit tests above;
  "reconstructable truth" only covers library state, the least valuable
  slice.
- **Postgres:** no operator in the cluster; operational cost unjustified
  until a second writer process exists (none planned).
