# ADR-0007: Council domain layer as first-class aggregates

**Status:** accepted

## Context

The product reset recentered Costanza on the household council: proposals,
interest, votes, cases, pleas, protections, decisions. The substrate's
data model anticipated social features only as a `signals` table ("empty
in v1; reactions land here in v1.x") — the implicit plan being that
social state would grow out of raw signal capture. Interrogating that:
votes need per-member uniqueness and weights; protections need reasons,
grantors, and review dates; decisions need provenance (policy version,
trigger, veto trail); proposals and cases are state machines. None of
that is an event stream — it is a relational domain model. Meanwhile the
substrate's genuinely hard parts (media identity, member identity,
idempotent history) are already solved and must not be re-solved.

## Decision

The council is a **first-class domain layer**: its own tables (members,
proposals, interest, votes, cases, pleas, protections, decisions,
policy_versions — [council/domain-model.md](../council/domain-model.md)),
its own state machines, and a policy engine, layered **above** the event
ledger in the same process and the same SQLite store (ordinary
migrations; ADR-0002 unchanged).

- Council rows **reference** substrate rows (`media.id`, `users.id`,
  `events.id` lists inside evidence snapshots); they never duplicate
  titles, watch history, or identity.
- `signals` is demoted from "future social home" to what it actually is:
  append-only raw reaction/interest-change capture feeding taste memory.
  No domain reads on hot paths, no writers beyond capture.
- The council layer never writes canonical events. Externally caused
  facts (an executed request) re-enter through the source's own webhook,
  keeping the ledger honest.

## Consequences

- Migrations add ~9 tables; the store layer grows a council repository
  section. Acceptable: the alternative is entangling domain semantics
  into the event schema that four normalizers and the reconcile matrix
  depend on.
- Two models must stay consistent at their seams (media/user FKs) — a
  cost the substrate's identity discipline already pays for once.
- The tier-model framing "Tiers 0–1 *are* v1" is superseded: the
  substrate is the foundation, the council is the product
  ([product-brief.md](../product-brief.md)).

## Alternatives rejected

- **Grow it out of `signals`:** shoehorns relational aggregates into an
  append-only event table; uniqueness, weights, reasons, and provenance
  all fight the shape. Rejected as the structural bias that produced a
  notifier instead of a product.
- **Separate council service:** two deployments, one SQLite writer
  problem split in half, and every evidence query crossing a network
  boundary. The modular monolith already has the seam (a council package)
  without the operational tax.
- **Events-as-everything (votes as canonical events):** provenance and
  latest-wins semantics become replay queries over the ledger; simple
  questions ("current tally?") stop being simple. The ledger records
  what happened; the council decides what it means.
