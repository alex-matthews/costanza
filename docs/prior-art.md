# Prior art survey

What already exists, what it teaches, and what Costanza deliberately does
differently. Nothing here is cloned wholesale.

## Request surfaces & Discord bots

| Project | What it is | Lesson for Costanza |
| --- | --- | --- |
| **Seerr v3** (running) | Unified Overseerr/Jellyseerr successor: requests, discover, watchlist, blacklist (incl. tag/collection blocklists), per-user permissions/quotas, notification agents | Seerr already owns request UX, discover browsing, and per-user request permissions. Costanza must not rebuild a request UI or a discover page. Seerr's own notifications are per-user and shallow — Costanza's value is household-level correlation and digests, not another webhook-to-Discord pipe. |
| **Requestrr / Doplarr / Membarr** | Discord-first request bots | The Discord-bot-first shape ages badly: locked to one channel's interaction model, hard to test, dies when Discord libs churn. Validates ADR-0001 (service with adapters). |
| **Old Costanza** (abandoned) | Python webhook receiver + Discord bot; normalizers for Seerr/Radarr/Sonarr/Tautulli; SQLite; pipelines | The normalizer-per-source and low-cardinality-metrics disciplines were right and are kept. What failed: no correlation layer, no identity map, no digest/ledger, bot and product logic entangled. |

## Watch/stats layer

| Project | Lesson |
| --- | --- |
| **Tautulli** (running) | Watch truth. Its newsletters prove digest demand but are Plex-only and template-rigid. Costanza consumes Tautulli webhooks + history API; never re-derives watch state from Plex directly. |
| **Jellystat / Streamystats** | Stats dashboards people actually check. Costanza exposes stats via API/metrics and lets Grafana render; no bespoke UI in v1. |

## Library lifecycle

| Project | Lesson |
| --- | --- |
| **Maintainerr** (running) | Rule-based collections → deletion with Plex-visible "leaving soon" collections. It owns *execution and scheduling* of deletion. Costanza should feed it judgment (candidates, protections) rather than compete. Its rule language can't express "nobody who requested it ever watched it and two people voted to keep" — that's exactly the household-context gap Costanza fills later. |
| **Janitorr / Decluttarr** | Cleanup daemons with auto-delete defaults. Their scary failure mode (surprise deletions) is the anti-pattern ADR-0006's tiered write model exists to prevent. |

## Recommendations

| Project | Lesson |
| --- | --- |
| **Recommendarr / Suggestarr** | LLM/TMDB recommenders bolted to Sonarr/Radarr/watch history. They demonstrate feasibility and the failure modes: hallucinated titles, no household concept, recommend-then-forget. Costanza's later recs phase differs by (a) deterministic candidate generation with LLM only ranking/explaining, (b) household interest gating, (c) closing the loop with watch data it already stores. |
| **Watchlistarr / Seerr watchlist sync** | Watchlist as interest signal — cheap, structured, no LLM. Use as a first-class interest input before any model. |

## Eventing & notifications

| Project | Lesson |
| --- | --- |
| **Chaski** (available, not deployed) | Stateless CEL/Go-template webhook relay → Apprise/HTTP. Great dumb pipe; explicitly not a queue or state store. Costanza is the opposite: stateful, domain-aware, correlating. Boundary in ADR-0004. Resolute already established the household rule: Chaski optional, direct webhooks the baseline, nothing in the service knows Chaski exists. |
| **Notifiarr** | Hosted notification hub for the *arr ecosystem. Validates demand for the "one place, curated notifications" job, but hosted/closed and household-blind. |
| **Apprise / ntfy** | Channel fanout libraries. Costanza's notifier port should stay thin enough that adding an Apprise or ntfy adapter later is a leaf change. |

## In-house prior art

| Project | Lesson |
| --- | --- |
| **Resolute** (~/src/resolute) | The house style to inherit: uv + pytest, fixture-driven no-network tests, shadow-mode-first rollout, durable SQLite on PVC, bounded schema-validated optional LLM, ADRs for contested decisions, "works when the optional relay is removed". Costanza adopts all of these conventions; it does not adopt Resolute's scope. |
| **home-ops repo** | Deployment idioms: bjw-s app-template HelmReleases, OCIRepository, ExternalSecrets, volsync-backed PVCs, single-replica stateful apps in `default` namespace, litellm gateway in `ai` namespace for any future LLM calls. |

Sources: [Seerr v3.2/3.3 release notes](https://docs.seerr.dev/blog/seerr-3-2-0-and-3-3-0-release-notes/), [Seerr releases](https://github.com/seerr-team/seerr/releases), [chaski](https://github.com/home-operations/chaski).
