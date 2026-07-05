# Discord interactions contract

Discord is the v1 participation surface and stays an adapter
([ADR-0008](../adr/0008-discord-interactions-surface.md)): the
`adapters/discord` module grows from send-only publisher into an
interaction gateway, but council state lives in Costanza's store and every
mechanic must survive Discord being down.

## Surfaces

| Surface | Discord mechanism | Notes |
| --- | --- | --- |
| Proposal card | Channel message: embed (poster, pitch, facts) + button row | Buttons: `Definitely Want` / `Maybe` / `No` / `Already Seen` |
| Proposal discussion | Thread anchored to the card | `proposals.thread_ref` |
| Propose something | Slash command `/propose <title>` → TMDB search select → pitch modal | Modal captures the member's why-suggested |
| Case (court / which-stays) | Embed with evidence summary + vote buttons + `Make a plea` button | Plea button opens a modal (free text) |
| Vote (structured) | Buttons or select menu on the case message | One tap = one vote; re-tap updates |
| Admin execution confirm | Admin-gated button row on the decision message (`Request in Seerr` / `Dismiss`) | See [execution.md](execution.md) |
| Watch-debt check-in | DM with three buttons: `Still keen` / `Downgrade` / `Release` | Release is the visually neutral default |
| Wrapped | Rich embed post, no interactions required | Reactions land in signals |

## Identity and authorization

- `interaction.user.id` → `identities(provider='discord', external_id)` →
  `users.id` → `members` row. **That chain is the v1 vote-auth model** —
  no separate accounts, no tokens for humans.
- Unmapped Discord user presses a button → ephemeral reply ("ask the admin
  to map you — you're not in the council yet"), the identity is recorded
  as an unmapped observation (existing substrate mechanism), and nothing
  is counted.
- Role gates read `members.role` and are enforced **server-side on the
  interaction**, never in the component: Discord components are shared
  per-message and cannot be disabled per-user, so a kid pressing a
  `delete_candidate` vote button gets an ephemeral "kids don't vote on
  deletions (but your watch-next votes count!)" and no recorded vote;
  execution-confirm and veto interactions re-check `admin` the same way.
  The button being pressable is cosmetic; the gate is the handler.
- Weight is copied from `members.vote_weight` at cast time, so later
  weight changes never rewrite history.

## Interaction handling rules

- **Idempotent by interaction id:** every component press carries a unique
  Discord interaction id, stored on the vote/interest row
  (`interaction_ref`); retries and gateway replays collapse. State
  transitions (latest-wins interest, unique votes) are idempotent anyway —
  the id is for audit.
- **Custom-id contract:** components encode `kind:context_id:choice`
  (e.g. `interest:prop_123:maybe`, `vote:case_9:keep`,
  `exec:dec_4:confirm`) — parseable without in-memory session state, so a
  process restart never orphans live components.
- **Ack fast, work off-path:** interactions are acknowledged within
  Discord's 3-second budget (deferred ephemeral reply when work is
  needed); the actual state change goes through the same store
  transaction discipline as everything else, and the card/case message is
  edited afterwards to reflect new tallies.
- **Tallies are anonymous-by-default in public:** the card shows counts
  ("3 want this"), not names; per-member positions appear in the thread
  only when a member states them or when the case verdict summarizes
  participation. Admin veto is the exception: always public, always with
  the reason.
- **Rate limits:** message edits are debounced (one tally refresh per few
  seconds per card) so a button storm never trips Discord's per-channel
  limits; the notification pipeline's existing per-channel limiter covers
  outbound posts.

## Degraded modes (Discord down or bot dead)

- The interaction gateway is the same supervised task as the notifier
  adapter: its crash never touches ingestion or the council store, and
  `/readyz` still excludes Discord.
- **Votes pause; nothing is lost.** Open proposals/cases live in the
  store with their own clocks (`closes_at`); when the gateway reconnects,
  it re-registers commands, re-hydrates components from `custom_id`s (no
  session state to lose), and edits cards to current tallies.
- Deadlines that expire during an outage are handled leniently: the case
  sweep extends `closes_at` by the outage duration (bounded by policy)
  rather than deciding on partial participation.
- Threshold-triggered *decisions* still fire while Discord is down (they
  are store-side), but their execution confirmations queue as ordinary
  ledger notifications and drain on recovery — the existing exactly-once
  machinery, unchanged.
- The read API remains the fallback surface for inspecting state (and is
  the seam a future web UI would use); there is deliberately no
  API-token voting path in v1 (single household token cannot attribute
  votes — see [constraint-amendments.md](constraint-amendments.md)).

## What the adapter still never does

- No domain logic in the gateway: it translates interactions to typed
  council-service calls and renders state back. Policy thresholds,
  tallying, and state machines live in the council layer.
- No council state cached only in Discord: message/thread ids are
  references, never the system of record.
- `discord.py` stays confined to `adapters/discord/` (the existing
  constraint test keeps enforcing this).
