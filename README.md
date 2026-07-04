# costanza

**Status: design pack only — no production code yet.**

Costanza is (will be) the household media event layer for a self-hosted media
stack: it normalizes request / acquisition / availability / watch / lifecycle
signals from Seerr, Radarr, Sonarr, and Tautulli into durable canonical events,
and turns them into low-noise household notifications, digests, and stats.
That durable event context is deliberately the foundation for later phases:
recommendations, voting, and library-lifecycle workflows.

This is a clean-sheet replacement for the abandoned first Costanza
(Python Discord bot + webhook receiver). No compatibility is preserved.

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
- **Runtime:** Python + uv + mise, matching [resolute](../resolute)
  conventions (pin the same Python minor Resolute is on — 3.14.x today).
- **V1 is read-only against every external system.** Costanza writes nothing
  to Seerr/Radarr/Sonarr/Maintainerr in v1; the only writes are to its own
  store and to Discord messages.
