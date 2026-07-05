# Council policy config

Thresholds and cadences are **household policy, not code**: a versioned
YAML file (ConfigMap, like `routing.yaml`), edited in git, hot-reloaded
on change. Every threshold-triggered action records the policy version
that fired it — provenance is the difference between "the system decided"
and "the rules we agreed on, version 7, decided".

## File format (`policy.yaml`)

```yaml
version: 7                       # monotonically increasing, bumped by hand
changelog: "lowered household DW threshold to 2 after trial month"

thresholds:
  request:
    admin_definite: 1            # 1 admin Definitely-Want -> request decision
    household_definite: 2        # 2 member DWs -> request decision
  vote_trigger:
    maybes: 3                    # 3 Maybes -> proposal moves to voting
  archive:
    stale_maybe_days: 30         # Maybe untouched this long -> archive sweep
  case:
    quorum: 3                    # min weighted votes for a case verdict
    default_duration_days: 5

cadences:
  # [second wave — parsed but nothing reads these until the retention
  #  engine / accountability features exist; activation-gated per OQ-11/14]
  which_stays:
    max_open_per_week: 1         # deletion theater cap (product-brief)
  media_court:
    max_open: 2
  watch_debt:
    min_days_between_checkins: 45   # low-frequency by design
    channel: dm                     # DM-first, never public
  wrapped:
    cron: "0 18 * * 0"
  # [v1.x — parsed but ignored until the Premiere Lobby ships (OQ-16);
  #  do NOT implement in the first loop]
  premiere_lobby:
    max_cards_per_week: 2           # unsolicited cards are the noisiest
                                    # thing Costanza can do
    deferred_max_wait_days: 180     # unmet resurface condition -> archive
    resurface_default:              # OQ-15: TMDB-only until decided otherwise
      tmdb_vote_count_gte: 50

execution:                        # see execution.md / ADR-0009
  phase_a_enabled: true           # admin-confirm buttons
  phase_b_enabled: false          # hands-free thresholds; SHIPS OFF
  phase_b_max_auto_requests_per_week: 2

membership_defaults:              # OQ-11 working defaults
  vote_weight: 1.0
  kids_vote_on: [watch_next]
  admin_veto: public_with_reason
```

Validation is a pydantic model (extra="forbid", fail-fast on load, same
discipline as `routing.yaml`); a malformed policy file keeps the previous
loaded version active and screams in the admin channel rather than
half-applying.

## Versioned provenance

- On every successful load, the store records
  `policy_versions(version, content_hash, loaded_at, source_note)`.
  A version number reused with different content is a validation error —
  the hash catches silent edits.
- Every `decisions` row with `trigger=threshold` carries
  `policy_version` (**non-null enforced at write time**); vote- and
  admin-triggered decisions record it too when a threshold opened the
  underlying vote, so the full chain is reconstructable.
- Wrapped and the admin digest can therefore answer "what changed since
  the rules changed?" — policy edits become part of household memory.

## Evaluation semantics

- Threshold evaluation is **deterministic and replayable**: a pure
  function of (current interest/vote aggregates, policy version). It runs
  on every relevant state change plus a daily sweep for time-based rules
  (staleness, case expiry).
- Threshold crossings are **edge-triggered and once-only per proposal ×
  rule**: crossing `household_definite` creates one decision; interest
  later dropping below and re-crossing does not re-fire (the decision
  ledger is the guard, same idempotency ethos as the notification
  ledger).
- Cadence caps are enforced at creation time (a second Which-Stays in a
  week is refused and queued for the sweep), never by cancelling live
  cases.
- Policy applies **prospectively only**: open proposals/cases keep the
  version they started under for their own transitions; new evaluations
  use the current version. No retroactive re-deciding.
