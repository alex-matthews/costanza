# ADR-0008: Discord interactions as the voting surface, identity-map attributed

**Status:** accepted (supersedes-in-part ADR-0001: the "Discord is only a
send-only notifier port" half; the "headless core, adapter boundary" half
stands)

## Context

ADR-0001 made Costanza a headless service with Discord as a send-only
notifier adapter — correct for the substrate, and its core rule (core
never imports discord.py; a dead bot never breaks ingestion) has proven
itself. But the council product is participatory: proposals, votes,
pleas, confirmations. The household lives in Discord; asking 4–8 mixed
users (including kids) to adopt a web UI or API tokens would kill
participation before it starts. Separately, votes need *attribution* —
and the substrate already maintains an identity map keyed by provider,
including Discord user ids.

## Decision

- The Discord adapter grows from publisher into an **interaction
  gateway**: application commands, buttons, selects, modals, threads
  ([council/interactions.md](../council/interactions.md)). Still inside
  `adapters/discord/`, still the only discord.py importer, still a
  supervised task whose death never touches ingestion or the store.
- **Discord interaction user ids resolved through the identity map are
  the v1 vote-auth model.** `interaction.user.id` → identities(provider
  discord) → member. Unmapped users are refused ephemerally and recorded
  as unmapped observations. Role/weight come from the members table at
  cast time. No API voting path in v1: the single household bearer token
  cannot attribute votes, and an unattributed vote is worse than none.
- Discord remains an adapter, never the system of record: council state,
  tallies, and deadlines live in the store; message/thread ids are
  references; components encode their context in custom_ids so a restart
  or outage loses nothing ("votes pause, history never lost").
- **Discussion-mining boundary (added 2026-07-05):** free-form message
  content may be read **only inside proposal/case threads** — spaces where
  members knowingly talk *to* the council — and only as taste signal for
  that thread's subject. The bot requests message-content access scoped as
  narrowly as Discord permits, never joins general channels for reading,
  and whole-server chat mining is rejected outright: inferring taste from
  the family's ambient conversation turns the council secretary into an
  eavesdropper, and no recommendation quality is worth that. Organic
  discussion outside threads influences Costanza only when a member brings
  it in (a button press, a `/propose`, a message in the thread).

## Consequences

- The adapter needs gateway intents and command registration — more
  discord.py surface, all confined behind the existing import constraint.
- Interaction handling gets the same idempotency discipline as ingest
  (interaction ids as dedupe refs; latest-wins interest; unique votes).
- A future non-Discord surface (web UI) plugs into the council service
  layer, not into Discord-shaped code — the ADR-0001 boundary keeps
  paying for itself.
- ADR-0001's status line is amended to point here.

## Alternatives rejected

- **Web UI first:** a login-having second surface nobody in the household
  asked for; participation dies at the login screen. Later, additive.
- **API-token voting:** one shared household token = anonymous votes;
  per-member tokens = secret management for children. Discord already
  authenticated everyone.
- **Reactions as votes (passive capture only):** ambiguous semantics
  (remove-and-re-add? which emoji?), no modals for pleas/pitches, no
  admin-gated confirmation buttons. Reactions stay as raw signals; votes
  are explicit components.
