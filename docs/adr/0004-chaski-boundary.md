# ADR-0004: Chaski is an optional dumb tee; Costanza never depends on it

**Status:** accepted

## Context

Chaski (home-operations) is a stateless webhook relay: path routes, CEL
gates, Go-template transforms, Apprise/HTTP targets. It is not deployed in
the cluster today. Resolute already set the household precedent: direct
webhooks are the baseline, Chaski optional and unmodified-passthrough,
nothing in the service knows it exists.

Two temptations to refuse: (a) making Chaski a required front door /
pseudo-queue for Costanza, (b) growing Costanza into a general notification
router that eats Chaski's job.

## Decision

Adopt Resolute's rule verbatim, plus a division of the notification world:

- **Costanza:** stateful, correlated, identity-aware **media-domain**
  events and household communication.
- **Chaski (if deployed):** stateless glue for **non-media** traffic
  (cluster alerts → Pushover etc.) and, optionally, a tee that relays
  *unmodified* source webhooks to Costanza alongside other consumers
  (useful when a source supports only one webhook URL and both Costanza and
  Resolute want Seerr events).
- Costanza's inbound contract is the sources' native payloads; a Chaski hop
  must be invisible. Idempotency keys (ADR in architecture doc) make
  tee-induced duplicates harmless.
- Costanza does not accept non-media webhooks and does not offer template
  routing; requests for that get pointed at Chaski/Apprise.

## Consequences

- **The tee is not hypothetical for Seerr** (confirmed 2026-07-04): Seerr
  v3 allows only one webhook agent ([seerr#804](https://github.com/seerr-team/seerr/issues/804)),
  so once both Resolute and Costanza want Seerr events, Chaski becomes the
  expected production topology for that one source. The boundary rules
  above are unchanged: the relay stays unmodified-passthrough, Costanza
  still treats the payload as Seerr-native, and direct wiring remains the
  supported baseline whenever only one consumer exists.
- Costanza ships no Chaski manifests or config (same as Resolute — avoid
  guessing its syntax; consult the Chaski repo if/when deployed).
- If Chaski later grows stateful features, this ADR gets revisited rather
  than silently eroded.

## Alternatives rejected

- **Chaski as mandatory ingress:** adds a dependency and a stateless hop in
  front of a service whose whole point is state; violates the household
  baseline rule.
- **Costanza as universal router:** feature soup; Apprise/Chaski already
  cover it statelessly.
