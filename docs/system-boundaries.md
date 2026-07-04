# System boundaries

The rule of thumb: **each neighbor keeps its job as system of record;
Costanza is the system of record only for household context** (events
history, identity, signals, votes, protections) — things no neighbor stores.

## Costanza vs Resolute

- **Resolute owns:** the pending-TV-request 1080p vs 2160p decision in Seerr,
  its executor, and its calibration loop. It is deliberately standalone.
- **Costanza owns:** telling the household what happened, including
  (optionally) surfacing Resolute's decisions as events if Resolute exposes
  them (webhook or API poll — read-only).
- **Never:** Costanza touching Seerr quality profiles, request-time quality
  decisions, or Sonarr profile assignment. Later library *audit* advice
  (existing files: downgrade/upgrade/protect) is allowed because it is a
  different lifecycle stage, different control point, and different data —
  and if that ever grows an executor, it should consult Resolute's
  calibration data rather than duplicate it.
- Not folded together because: different risk profiles (Resolute writes to
  Seerr today; Costanza must earn writes), different release cadences, and
  Resolute is already shadow-ready.

## Costanza vs Maintainerr

- **Maintainerr owns:** retention rule evaluation, "leaving soon" Plex
  collections, and deletion *execution* against the Arrs/Plex.
- **Costanza owns:** household judgment about *what deserves* deletion or
  protection — watch-informed, vote-informed candidate lists and a protected
  registry.
- **Boundary (ADR-0003):** Costanza never deletes media itself, in any phase.
  In v2 it feeds Maintainerr (candidates via collections/rules, protections
  as exclusions) and Maintainerr remains the only deleter. In v1 Costanza
  only *observes* deletion events.

## Costanza vs Chaski

- **Chaski owns:** stateless webhook relay/transform/fanout — cluster alerts
  to Pushover, generic glue. If it gets deployed, it may sit in front of
  Costanza as a tee/relay.
- **Costanza owns:** stateful, correlated, identity-aware media-domain
  events. Anything needing memory, dedupe, or history is Costanza's side of
  the line.
- **Boundary (ADR-0004):** same rule Resolute set — direct webhooks are the
  supported baseline, Chaski is optional and unmodified-passthrough only,
  and nothing inside Costanza knows Chaski exists. Costanza does not become
  a general notification router for non-media traffic.

## Costanza vs Seerr

- **Seerr owns:** the request UI, discover/browse, watchlists, blacklists,
  user accounts, per-user permissions/quotas, and request state.
- **Costanza owns:** what happens around requests — correlation to outcomes,
  household communication, interest aggregation.
- **v1:** webhooks in, read-only API polls for reconciliation and user sync.
  **v2:** at most two write verbs, both gated: create request (quorum
  auto-request) and comment/annotate if Seerr supports it. Costanza never
  approves/denies requests in Seerr on its own (that's admin policy, and
  partially Resolute's flow for TV).

## Costanza vs Plex / Tautulli

- **Tautulli owns:** watch truth (sessions, history, per-user stats).
  Costanza consumes Tautulli webhooks for real-time playback events and its
  API for backfill/reconciliation. Costanza never scrapes Plex sessions
  directly and never writes to Plex (Maintainerr's collections are the only
  Plex-visible surface, via Maintainerr).
- Plex direct integration is a non-goal until a concrete need appears that
  Tautulli can't serve.

## Costanza vs Radarr / Sonarr / Bazarr

- **Arrs own:** acquisition, quality profiles, file management, disk truth.
- **Costanza:** ingests grab/import/upgrade/delete/health webhooks from
  config-registered instances — v1 configures `radarr` only; `radarr-se`
  is the admin's personal instance and stays out of household scope
  (OQ-1), addable later by config alone; polls read-only
  APIs for library snapshots, disk stats, and reconciliation. No writes in
  any currently planned phase — lifecycle writes go through Maintainerr,
  request writes through Seerr.
- **Bazarr:** v1.x read-only subtitle status; a single gated "search
  subtitles for X" write is the v2 candidate.
