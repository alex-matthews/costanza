# Open questions

Only questions that block implementation or materially change scope.
Each has a recommended default; building to the default is safe.

**OQ-1 — What is `radarr-se`?** Second Radarr instance (standard edition?
anime? 4K?). Affects normalizer config and whether events need an
instance-quality dimension in digests.
*Default:* treat as an independent configured source with its own secret
and label; no special semantics until told otherwise.

**OQ-2 — Discord channel topology.** One feed channel vs
feed + digest + admin.
*Default:* three channels — `#media-feed` (real-time allowlist),
`#media-digest` (weekly), `#media-admin` (unmapped users, health, ops) —
mapped in routing.yaml; trivially collapsible.

**OQ-3 — Watch-completion source of truth.** Does Tautulli have a watched
threshold notification configured, or should Costanza derive completion
from progress?
*Default:* consume Tautulli's `watched` trigger if configured; otherwise
derive at ≥85% progress. Both paths normalize to `watch.completed`.

**OQ-4 — Maintainerr API surface (blocks v2, not v1).** Verify at v2 time
that current Maintainerr exposes collection/exclusion manipulation adequate
for ADR-0003; if not, the Tier-3 integration degrades to human-readable
candidate reports only.
*Default:* design assumes reports-only until verified.

**OQ-5 — Does Resolute expose decisions for consumption?** A decision
webhook/API would let v1.x timelines show "Resolute chose 2160p".
*Default:* omit; add as an ordinary ingest source when Resolute publishes
one (read-only, zero coupling).

**OQ-6 — Seerr webhook multiplexing. ANSWERED (2026-07-04).** Seerr v3
supports **exactly one** webhook agent instance; multi-instance support is
an open upstream request ([seerr#804](https://github.com/seerr-team/seerr/issues/804),
inherited from [overseerr#972](https://github.com/sct/overseerr/issues/972)).
*Resolution:* Seerr → Costanza direct while Resolute is undeployed; once
Resolute deploys, Chaski joins the v1 topology as the Seerr tee (one
route, unmodified JSON to both consumers, per ADR-0004). Radarr/Sonarr/
Tautulli support multiple webhook targets natively and stay direct.

**OQ-7 — Raw payload retention.** 30 days default balances replay/debug
value vs storing watch behavior in raw form.
*Default:* 30 days; canonical events indefinite.

**OQ-8 — Household identity bootstrap.** Who are the 4–8 members and their
Seerr/Plex/Discord ids? Pure config data, needed at rollout step 3.
*Default:* `routing.yaml` `users:` block filled in by admin during rollout.
