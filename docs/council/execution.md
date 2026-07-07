# Staged execution — the vote→request loop

The payoff loop ("two Definitely-Wants and it *shows up*") is designed in
from day one and gated hard ([ADR-0009](../adr/0009-staged-execution.md)).
Two phases, one executor.

## Phase A — admin-confirm one-click (Tier 3; council v1 default ON)

```
decision(kind=request, trigger=threshold|vote)
   └─► admin channel message: proposal summary + [Request in Seerr] [Dismiss]
            └─(admin-gated button, identity-checked)─► executor ─► Seerr
```

- The confirm button is rendered only to `members.role=admin` (and
  re-checked server-side on press — component gating is UX, the check is
  authz).
- One press executes exactly once: the execution row is created first
  (see audit) with a UNIQUE constraint on `decision_id`; a second press
  answers "already requested by <admin> at <time>".
- `Dismiss` records a decision amendment with the admin's reason — a
  dismissal is taste signal, not deletion of history.

## Phase B — threshold auto-request (Tier 4; ships OFF)

- Flag: `execution.phase_b_enabled` in [policy.md](policy.md) — default
  `false` in the shipped example and in code.
- Hard caps enforced in the executor, not just policy:
  `phase_b_max_auto_requests_per_week` (default 2); cap reached → falls
  back to phase A confirmation.
- Graduates only after phase A history demonstrates the thresholds are
  sane (ADR-0006's dry-run-first ethos); the admin digest reports what
  phase B *would* have done while it is off.
- **Instant demotion:** `COSTANZA_READ_ONLY=true` (env, fire-alarm) forces
  every execution path into dry-run regardless of flags; flipping
  `phase_b_enabled` off requires only a ConfigMap edit.

## The executor module

- **One module** (`executors/seerr.py` when built) owns the only outbound
  write verb in the codebase: create request in Seerr (movie / TV with
  seasons). Nothing else — no approve/decline (admin policy and
  Resolute's flow), no deletes (ADR-0003), no profile changes (Resolute's
  turf).
- Isolated and flagged: constructed only when phase A is enabled;
  disabled = not constructed = no code path (the substrate's
  "not flagged off — absent" discipline continues to apply to everything
  *except* this one deliberate, designed-in seam).
- The constraint-test allowlist grows by exactly this module
  ([constraint-amendments.md](constraint-amendments.md)).
- Secrets: Seerr API key via the existing env contract; the executor
  reuses the sanitized error path (no secrets in exceptions/logs).

## Audit rows (before, not after)

```
executions(id PK,
           decision_id UNIQUE -> decisions.id,
           actor -> members.user_id NULL,   -- NULL = phase B automatic
           phase ENUM(a, b),
           dry_run INTEGER,
           requested_payload_json,          -- what we asked Seerr for
           state ENUM(pending, succeeded, failed, dry_run),
           seerr_request_id NULL,           -- Seerr's id on success
           error NULL,
           created_at, completed_at)
```

- The row is written `pending` **before** the HTTP call (write-ahead
  audit: a crash mid-execution leaves evidence, and the UNIQUE decision_id
  means recovery never double-fires; an interrupted `pending` older than
  a timeout is reconciled against Seerr's request list before any retry).
- Success closes the loop honestly: Costanza does **not** synthesize a
  request event for itself — Seerr's own webhook (request created /
  auto-approved) arrives through the front door and lands in the timeline
  like any other event, which is how the proposal card learns to show
  "requested ✓".
- Failures render on the decision message with a retry button (phase A)
  or fall back to phase A (phase B); the notification ledger's backoff
  discipline is not reused here — executions are human-paced, not
  queue-paced.

## Metrics / observability

`costanza_executions_total{phase, state}`,
`costanza_phase_b_cap_remaining` gauge, and every execution in the admin
digest. Silence is never an execution: dry-run and cap-fallback outcomes
notify too.
