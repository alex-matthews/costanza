# costanza

**Status: v1 implemented (Tiers 0–1: observe + notify) — awaiting shadow rollout.**

Costanza is the household media event layer for a self-hosted media
stack: it normalizes request / acquisition / availability / watch / lifecycle
signals from Seerr, Radarr, Sonarr, and Tautulli into durable canonical events,
and turns them into low-noise household notifications, digests, and stats.
That durable event context is deliberately the foundation for later phases:
recommendations, voting, and library-lifecycle workflows.

This is a clean-sheet replacement for the abandoned first Costanza
(Python Discord bot + webhook receiver). No compatibility is preserved.

## Quickstart

```sh
mise run sync      # uv sync --locked
mise run test      # pytest (offline)
mise run lint      # ruff
mise run replay    # e2e smoke: fixtures -> scratch instance -> assertions
mise run run       # local dev server against config/routing.example.yaml
mise run build     # docker build (nonroot, /data volume)
```

Configuration is env-first (`COSTANZA_*`, `WEBHOOK_SECRET__{SOURCE}`,
`{SOURCE}_API_KEY`, `API_BEARER_TOKEN`, `DISCORD_TOKEN`) plus a
`routing.yaml` for sources, channels, allowlist rules, digest schedule, and
the household identity map — see [config/routing.example.yaml](config/routing.example.yaml).
A fresh store boots with the notification kill switch **engaged**; disengage
via `POST /api/v1/admin/kill-switch` when shadow ingest looks healthy.
Implementation deviations from the design pack are recorded in
[docs/build-notes.md](docs/build-notes.md).

## Design pack

| Doc | Contents |
| --- | --- |
| [docs/product-brief.md](docs/product-brief.md) | What Costanza is, users, v1 outcomes, non-goals, scope pushback |
| [docs/prior-art.md](docs/prior-art.md) | Survey of adjacent tools and what was borrowed/rejected |
| [docs/capability-map.md](docs/capability-map.md) | Capabilities by phase (v1 / v1.x / v2 / not-ours) |
| [docs/system-boundaries.md](docs/system-boundaries.md) | Costanza vs Resolute, Maintainerr, Chaski, Seerr, Plex/Tautulli, *arr |
| [docs/architecture.md](docs/architecture.md) | Architecture options, recommendation, state, eventing, deployment |
| [docs/adr/](docs/adr/) | ADRs 0001–0006 (the six contested decisions) |
| [docs/handoff.md](docs/handoff.md) | V1 implementation handoff: repo layout, modules, contracts, data model, jobs, config, k8s, testing, rollout |
| [docs/risks.md](docs/risks.md) | Risk register |
| [docs/open-questions.md](docs/open-questions.md) | Blocking questions with recommended defaults |
| [docs/v1-build-prompt.md](docs/v1-build-prompt.md) | Scoped build prompt: hand this to the implementing model |

## Decisions already locked (by the household)

- **V1 core job:** household media event layer — normalize, persist, notify,
  digest. Everything else layers on top.
- **Household:** 4–8 mixed users; per-user identity is foundational, voting
  mechanics are deferred but designed-for.
- **Runtime:** Python + uv + mise (3.14.x). Ops/tooling precedent is the
  live cluster: home-ops manifests for deployment posture and
  home-operations/containers (e.g. `apps/tautulli`) for the container
  pattern — identity-agnostic images, storage identity from Kubernetes.
- **V1 is read-only against every external system.** Costanza writes nothing
  to Seerr/Radarr/Sonarr/Maintainerr in v1; the only writes are to its own
  store and to Discord messages.
