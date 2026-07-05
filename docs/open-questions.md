# Open questions

Only questions that block implementation or materially change scope.
Each has a recommended default; building to the default is safe. Items
answered during the substrate build stay here for the record.

## Substrate-era questions (settled)

**OQ-1 — What is `radarr-se`? ANSWERED (2026-07-04).** The admin's
*personal* Radarr instance: not hooked into Seerr, Plex library visible
only to the admin.
*Resolution:* not a configured source. Household feeds must never include
its content; adding it later (admin-only channel) is pure config.

**OQ-2 — Discord channel topology (substrate notifications).**
*Default (in use):* `#media-feed` (real-time allowlist), `#media-digest`
(weekly), `#media-admin` (unmapped users, health, ops) — mapped in
routing.yaml; trivially collapsible. Council surfaces add to this: OQ-14.

**OQ-3 — Watch-completion source of truth.**
*Default (built):* consume Tautulli's `watched` trigger if configured,
else derive at ≥85% progress. Both paths share one idempotency key, so
flipping the config never double-counts.

**OQ-4 — Maintainerr API surface (blocks v2 candidate feeds, not the
council).** Verify at v2 time that Maintainerr exposes
collection/exclusion manipulation adequate for ADR-0003; until verified,
the council's retention outcomes degrade to human-readable reports.
*Default:* reports-only until verified.

**OQ-5 — Does Resolute expose decisions for consumption?** A decision
webhook/API would let proposal cards say "Resolute chose 1080p because…".
*Default:* omit; add as an ordinary ingest source when Resolute publishes
one (read-only, zero coupling).

**OQ-6 — Seerr webhook multiplexing. ANSWERED (2026-07-04).** Seerr v3
supports exactly one webhook agent (seerr#804).
*Resolution:* Seerr → Costanza direct while Resolute is undeployed; once
Resolute deploys, Chaski joins as the Seerr tee (unmodified JSON to both,
per ADR-0004). Radarr/Sonarr/Tautulli stay direct.

**OQ-7 — Raw payload retention. ANSWERED (built).** 30 days, enforced for
dead-lettered rows too (bodies redacted past retention); canonical events
kept indefinitely.

**OQ-8 — Household identity bootstrap.** Who are the members and their
Seerr/Plex/Discord ids? Pure config data, needed at rollout step 3.
*Default:* routing.yaml `users:` block filled by the admin during rollout.
The council layer extends the same map (members = users + role/weight/
opt-ins), so this bootstrap is also the council's member registry.

## Council-era questions (defaults adopted 2026-07-05; confirm with the household)

**OQ-9 — Substrate deployment timing.** Deploy the shipped substrate in
shadow now, or hold everything until council v1?
*Default (adopted):* deploy substrate in shadow now — taste memory needs
months of accumulated events, and every council feature is an
event-history query. The social layer is useless without history.

**OQ-10 — Sequencing vs Resolute.** *Default (adopted):* Resolute
ops-fix + deploy first — its deployment forces the Chaski tee decision
(OQ-6) into place before the council needs Seerr events too.

**OQ-11 — Council membership mechanics.** Do kids vote? Equal weights?
Is the admin veto public?
*Default (adopted, genuinely needs household confirmation):* all mapped
members vote with weight 1; kids' votes count on watch-next but not
delete; admin veto is public with a reason — vetoes are taste signals
too.

**OQ-12 — Execution stance for council v1.** Phase A only (admin-confirm
buttons), or phase B hands-free thresholds behind a flag from day one?
*Default (adopted):* build both, ship with B off
([ADR-0009](adr/0009-staged-execution.md)).

**OQ-13 — LLM posture for family text.** Pleas and pitches are personal;
litellm may route to external providers.
*Default (adopted):* aggregate-only prompts until a local model route
exists; member-authored text never leaves the cluster before then; the
LLM never publicly scores individual members (ADR-0005 addendum).

**OQ-14 — Council Discord topology + accountability visibility.** Which
channels host the Lobby, Court, and Wrapped; are accountability stats
opt-in or opt-out per member (playful can read as punitive)?
*Default:* Lobby and Court as dedicated channels beside the existing
three; Wrapped posts to the household channel; stats are opt-out with
gentle defaults, DM-first before any public leaderboard. Genuinely open:
the household should choose the channel names and the opt-in/opt-out
stance together.
