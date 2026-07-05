# Council domain model

The council layer is a set of first-class aggregates
([ADR-0007](../adr/0007-council-domain-layer.md)) that sit **above** the
substrate's event ledger. Council rows *reference* events and media as
evidence; they never duplicate them. `signals` stays what it is today —
raw reaction capture, no domain meaning.

## Tables (schema sketch; ships as ordinary store migrations)

```
members(user_id PK -> users.id,
        role ENUM(admin, adult, kid),
        vote_weight REAL DEFAULT 1.0,
        optin_accountability INTEGER DEFAULT 1,   -- opt-OUT model, OQ-14
        optin_watch_debt INTEGER DEFAULT 1,
        optin_public_stats INTEGER DEFAULT 0,     -- DM-first default
        joined_at)
  -- extends users/identities (the substrate identity map IS the member
  -- registry); a users row without a members row cannot vote.

proposals(id PK, media_id -> media.id,
          proposed_by -> members.user_id,
          origin ENUM(member, seed, wrapped, watch_debt),
          pitch TEXT,                      -- member's why-suggested
          tmdb_snapshot_json,              -- card facts at proposal time
          state ENUM(suggested, gauging, voting, decided, archived),
          opened_at, state_changed_at, decided_at,
          decision_id -> decisions.id NULL,
          thread_ref TEXT)                 -- Discord thread id, nullable

interest(member_id -> members.user_id,
         media_id -> media.id,
         level ENUM(definite, maybe, no, seen),
         set_at,
         via ENUM(discord, api, import),
         UNIQUE(member_id, media_id))
  -- keyed on MEDIA, not proposal: interest outlives any one card and a
  -- re-proposal starts warm. Latest write wins; history of changes goes
  -- to signals for taste memory.

cases(id PK,
      skin ENUM(court, which_stays),
      media_ids_json,                      -- [one] for court, [two] for which_stays
      evidence_json,                       -- snapshot, see below
      state ENUM(open, deliberating, decided, expired),
      thread_ref TEXT,
      opened_at, closes_at, decided_at,
      decision_id -> decisions.id NULL,
      policy_version INTEGER)

votes(id PK,
      context_kind ENUM(proposal, case),
      context_id,                          -- proposals.id | cases.id
      member_id -> members.user_id,
      choice TEXT,                         -- per-context vocabulary
      weight REAL,                         -- copied from members at cast time
      cast_at,
      via ENUM(discord, api),
      interaction_ref TEXT,                -- Discord interaction id (dedupe)
      UNIQUE(context_kind, context_id, member_id))
  -- re-voting updates the row (latest wins) and appends to signals.

pleas(id PK, case_id -> cases.id,
      member_id -> members.user_id,
      text TEXT,
      llm_summary TEXT NULL,               -- ADR-0005 boundary, never a score
      created_at)

protections(id PK, media_id -> media.id,
            reason ENUM(comfort_watch, family_favorite, kids, sentimental,
                        hard_to_reacquire, demo_material, seasonal,
                        admin_override),
            note TEXT,
            granted_by -> members.user_id,
            granted_at, review_at NULL,
            released_at NULL, released_by NULL)

decisions(id PK,
          kind ENUM(request, keep, delete_candidate, downgrade, protect,
                    release_protection, watch_next, archive),
          subject_kind ENUM(proposal, case, media),
          subject_id,
          outcome TEXT,                    -- human-readable result
          reason TEXT,                     -- the household's why
          trigger ENUM(threshold, vote, admin, veto),
          policy_version INTEGER NULL,     -- REQUIRED when trigger=threshold
          decided_at,
          vetoed_by NULL, veto_reason NULL,
          execution_id NULL)               -- -> executions (execution.md)

policy_versions(version PK, content_hash, loaded_at, source_note)
```

Executions (`executions` table) are specified in
[execution.md](execution.md); the policy file contract in
[policy.md](policy.md).

## State machines

### Proposal

```
suggested ──card posted──► gauging ──3 Maybes (policy)──► voting ──► decided
    │                        │                                          │
    │                        ├─ 2 household DW / 1 admin DW (policy) ───┤
    │                        │            (straight to decided:request) │
    │                        └─ stale Maybe 30d (policy) ──► archived   ▼
    └────────── admin veto (public, with reason) ─────────────────► decided
```

- `gauging` collects interest button presses; threshold evaluation runs on
  every interest change and on a daily sweep (staleness).
- Every automatic transition records `trigger=threshold` +
  `policy_version` on the resulting decision. Vote outcomes record
  `trigger=vote`; admin actions `trigger=admin|veto`.
- `decided` proposals with `kind=request` flow into the execution model
  (phase A: admin-confirm button; phase B: flagged auto-request).
- Archived proposals keep their interest rows — a later re-proposal of the
  same media starts from the accumulated picture.

### Case (one machine, two skins)

```
open ──evidence assembled, thread created──► deliberating ──closes_at──► decided
  │                                              │                          │
  └── expired (nobody engaged by closes_at; no outcome recorded as decision) 
```

- `court`: one title; votes are `keep | delete_candidate | downgrade |
  protect`; pleas welcome.
- `which_stays`: two titles; votes are `media_ids[0] | media_ids[1] |
  both_stay`; capped at one open case per week by policy cadence.
- Kids' votes are excluded from `delete_candidate` tallies but counted
  for `watch_next` contexts (OQ-11).
- A protection on any involved title blocks `delete_candidate` outcomes:
  the engine surfaces the protection instead of putting it to a vote.

### Interest

`definite | maybe | no | seen` — a flat latest-wins state per
member × media, changed only by that member (or import from Seerr
watchlists later). Transitions carry no workflow; the *proposal* machine
reads aggregate interest, the taste memory reads the change history from
signals.

## Events as evidence (the substrate relationship)

- Council rows point at `media.id` and `users.id` — the same rows the
  substrate maintains. No council table stores titles, watch counts, or
  timelines.
- `cases.evidence_json` is a **snapshot** assembled at case-open time from
  substrate queries (timeline, watch counts per member, request chain,
  size/quality attrs from events) plus TMDB facts. It embeds the source
  `events.id` list so the case can always be re-derived and audited. The
  snapshot exists so a verdict is judged against what the household *saw*,
  even if reconcile later back-fills history.
- Accountability and watch-debt are pure substrate queries (request chains
  joined to watch events) filtered through member opt-ins; they create
  council rows only when they open a proposal or check-in decision.
- `signals` remains append-only raw capture (button presses, reaction
  emoji, veto occurrences) feeding taste memory in v1.x. Nothing reads it
  on a hot path; nothing but capture writes it.

## What this deliberately avoids

- **No shoehorning into `signals`** (ADR-0007): votes with weights and
  uniqueness constraints, protections with reasons and reviews, and
  decisions with provenance are relational aggregates, not events.
- **No duplicate media/user identity:** the hardest substrate problems
  (identity, dedupe) stay solved in exactly one place.
- **No cross-layer writes:** the council layer never inserts canonical
  events; if a council action needs to appear in timelines (e.g. an
  executed request), the *source system's webhook* reports it back through
  the front door, which keeps the ledger honest.
