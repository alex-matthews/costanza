# costanza

**Status: substrate shipped (observe + notify, awaiting shadow rollout);
Council v1 designed, implementation next.**

Costanza is the **household media council**: the place where a family
decides, debates, and remembers what their library is for. Proposals with
Definitely Want / Maybe / No buttons, structured keep/delete decisions
with evidence and pleas, a Protected Shelf with human reasons, playful
accountability, and Library Wrapped — with automation staged in behind
admin confirmation. Automation executes elsewhere (Seerr, the Arrs,
Maintainerr, Resolute); Costanza owns participation, reasons, and memory.

Under the council sits the shipped **substrate**: every request, grab,
import, availability change, deletion, and watch from Seerr, Radarr,
Sonarr, and Tautulli, normalized into durable canonical events, correlated
into per-title timelines, mapped to household members, and delivered as
low-noise notifications and digests with exactly-once guarantees.

This is a clean-sheet replacement for the abandoned first Costanza
(Python Discord bot + webhook receiver). No compatibility is preserved.

## Quickstart

```sh
mise run sync       # uv sync --locked
mise run test       # pytest (offline)
mise run lint       # ruff
mise run replay     # e2e smoke: fixtures -> scratch instance -> assertions
mise run k8s-smoke  # image under cluster constraints (uid 1032:100, ro rootfs)
mise run run        # local dev server against config/routing.example.yaml
mise run build      # docker build (identity-agnostic alpine image)
```

Configuration is env-first (`COSTANZA_*`, `WEBHOOK_SECRET__{SOURCE}`,
`{SOURCE}_API_KEY`, `API_BEARER_TOKEN`, `DISCORD_TOKEN`) plus a
`routing.yaml` for sources, channels, allowlist rules, digest schedule, and
the household identity map — see [config/routing.example.yaml](config/routing.example.yaml).
The image ships no config; deployments mount the ConfigMap. A fresh store
boots with the notification kill switch **engaged**; disengage via
`POST /api/v1/admin/kill-switch` when shadow ingest looks healthy.

## Docs

| Doc | Contents |
| --- | --- |
| [docs/product-brief.md](docs/product-brief.md) | The council product: core loops, users, outcomes, non-goals |
| [docs/architecture.md](docs/architecture.md) | Two-layer architecture (substrate + council), eventing, deployment model |
| [docs/capability-map.md](docs/capability-map.md) | Capabilities by phase (substrate / council v1 / v1.x / v2 / not-ours) |
| [docs/council/](docs/council/) | Council v1 design pack: domain model, interactions, policy, retention engine, execution, metadata, constraint amendments |
| [docs/adr/](docs/adr/) | ADRs 0001–0010 (the contested decisions) |
| [docs/system-boundaries.md](docs/system-boundaries.md) | Costanza vs Resolute, Maintainerr, Chaski, Seerr, Plex/Tautulli, *arr |
| [docs/handoff.md](docs/handoff.md) | Substrate implementation record: modules, contracts, data model, jobs, rollout |
| [docs/build-notes.md](docs/build-notes.md) | Implementation reality: deviations, hardening, ops reset |
| [docs/open-questions.md](docs/open-questions.md) | Open questions with working defaults and activation gates (OQ-1–16) |
| [docs/risks.md](docs/risks.md) | Risk register |
| [docs/prior-art.md](docs/prior-art.md) | Survey of adjacent tools and what was borrowed/rejected |
| [docs/history/](docs/history/) | Historical artifacts (superseded specs, kept for the record) |
| [deploy/README.md](deploy/README.md) | Cluster deployment posture: securityContext, volsync/SQLite, restore drill |

## Decisions already locked (by the household)

- **The product is the council; the event layer is its substrate.**
  Participation, reasons, and memory are the job; notifications are
  plumbing that happens to be visible.
- **Household:** 4–8 mixed users; per-member identity is foundational.
  Discord interactions resolved through the identity map are the v1
  voting surface ([ADR-0008](docs/adr/0008-discord-interactions-surface.md)).
- **Runtime:** Python + uv + mise (3.14.x). Ops/tooling precedent is the
  live cluster: home-ops manifests for deployment posture and
  home-operations/containers (e.g. `apps/tautulli`) for the container
  pattern — identity-agnostic images, storage identity from Kubernetes.
- **Writes are staged, never sprinkled.** The substrate is read-only
  against every external system. Council v1 adds exactly one executor
  (Seerr create-request) behind admin confirmation, audit rows, and flags
  ([ADR-0009](docs/adr/0009-staged-execution.md)); Maintainerr remains the
  only deleter ([ADR-0003](docs/adr/0003-maintainerr-boundary.md)).
