# Deployment notes (reference only)

Real manifests live in the home-ops repo (`kubernetes/apps/default/costanza/app/`),
per docs/handoff.md — this repo ships none by design.

Shape (mirrors Resolute and the handoff):

- bjw-s app-template HelmRelease + OCIRepository; single replica,
  `strategy: Recreate` (SQLite single-writer).
- PVC 5Gi mounted at `/data`, volsync-labelled like peer apps.
- ConfigMap mounting `routing.yaml` at `/config/routing.yaml`.
- ExternalSecret providing `DISCORD_TOKEN`, `WEBHOOK_SECRET__{SOURCE}`,
  `{SOURCE}_API_KEY`, `API_BEARER_TOKEN`.
- Probes: liveness `/healthz`, readiness `/readyz` (DB + config; deliberately
  NOT Discord — a dead bot must not restart-loop ingestion).
- ServiceMonitor on `/metrics`; alert later on `costanza_outbox_backlog`
  and `costanza_webhook_auth_failures_total`.
- Cluster-internal Service only (`http://costanza.default.svc:8140`);
  no ingress in v1 — Discord uses an outbound gateway connection.
- Container security context (verified against the image — it runs with a
  read-only root filesystem, all capabilities dropped, and no /tmp):

  ```yaml
  securityContext:
    runAsNonRoot: true
    runAsUser: 1033
    runAsGroup: 100
    readOnlyRootFilesystem: true
    allowPrivilegeEscalation: false
    capabilities: { drop: ["ALL"] }
  ```

  Only `/data` (PVC) needs to be writable; bytecode is precompiled at
  image build time (`PYTHONDONTWRITEBYTECODE=1` at runtime).

Rollout is the six-step plan in docs/handoff.md: shadow ingest with the
kill switch ON, reconcile confidence, private channel, household channel,
retire old Costanza, volsync restore drill.
