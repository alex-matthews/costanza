# Deployment notes (reference only)

Real manifests live in the home-ops repo (`kubernetes/apps/default/costanza/app/`),
per docs/handoff.md — this repo ships none by design.

**Authority:** the deployment posture below is the live cluster standard,
verified against home-ops manifests (e.g. `kubernetes/apps/default/bazarr/
app/helmrelease.yaml`, likewise atuin/maintainerr) and the volsync
component (`kubernetes/components/volsync/local/replicationsource.yaml`).
The image follows the home-operations/containers precedent
(`apps/tautulli/Dockerfile`): identity-agnostic, `USER nobody:nogroup` as
the bare-run default, no baked config, storage identity always supplied by
Kubernetes.

## Shape

- bjw-s app-template HelmRelease + OCIRepository; single replica,
  `strategy: Recreate` (SQLite single-writer).
- PVC 5Gi mounted at `/data`, volsync-labelled like peer apps.
- ConfigMap mounting `routing.yaml` at `/config/routing.yaml` — required:
  the image ships no config and fails fast without it.
- ExternalSecret providing `DISCORD_TOKEN`, `WEBHOOK_SECRET__{SOURCE}`,
  `{SOURCE}_API_KEY`, `API_BEARER_TOKEN`.
- Probes: liveness `/healthz`, readiness `/readyz` (DB + config; deliberately
  NOT Discord — a dead bot must not restart-loop ingestion).
- ServiceMonitor on `/metrics`; alert later on `costanza_outbox_backlog`
  and `costanza_webhook_auth_failures_total`.
- Cluster-internal Service only (`http://costanza.default.svc:8080`);
  no ingress in v1 — Discord uses an outbound gateway connection.

## Security context (cluster standard for stateful apps)

```yaml
defaultPodOptions:
  securityContext:
    runAsNonRoot: true
    runAsUser: 1032
    runAsGroup: 100
    fsGroup: 100
    fsGroupChangePolicy: OnRootMismatch
# per-container:
securityContext:
  readOnlyRootFilesystem: true
  allowPrivilegeEscalation: false
  capabilities: { drop: ["ALL"] }
```

Why exactly this: the volsync restic movers run as
`${VOLSYNC_PUID:=1032}` / `fsGroup ${VOLSYNC_PGID:=100}` — data written
under any other uid without `fsGroup` is a backup/restore incident. The
image bakes no storage identity, so these values are the single source of
truth. Only `/data` (PVC) needs to be writable; bytecode is precompiled at
image build time and no HOME is required (verified by
`scripts/k8s-smoke.sh`, which runs the image with `--user 1032:100
--read-only`, config mounted read-only, and only `/data` writable).

## SQLite on volsync (backup/restore posture)

- **copyMethod is `Snapshot`** (volsync component default): restic reads a
  CSI snapshot of the PVC, not the live filesystem, so a backup captures a
  crash-consistent point-in-time image — equivalent to SQLite surviving a
  power cut, which WAL mode is designed for.
- **WAL expectations:** the snapshot may contain `costanza.db` plus
  `-wal`/`-shm` sidecars. That is fine: SQLite replays the WAL on first
  open. Never back up or restore the `.db` file *without* its `-wal`
  sidecar. No application quiesce is needed at this write volume; if WAL
  files ever grow unreasonably between hourly snapshots, add a periodic
  `PRAGMA wal_checkpoint(TRUNCATE)` job — not needed today.
- **Restore drill (run once before calling the deployment done, and after
  any volsync/storage-class change):**
  1. Create a scratch PVC + ReplicationDestination in a throwaway
     namespace pointing at the costanza restic repository (same pattern as
     other apps' restore docs in home-ops).
  2. Mount it in a debug pod running as `1032:100` (`kubectl run --rm -it
     --image=python:3.14-alpine3.24 --overrides='…securityContext…'`).
  3. Open the restored DB and verify:
     `sqlite3 /data/costanza.db "PRAGMA integrity_check;"` → `ok`, then
     `SELECT COUNT(*) FROM events;` and
     `SELECT MAX(received_at) FROM events;` to confirm recency.
  4. Confirm file ownership landed as `1032:100` (or is group-writable via
     fsGroup) so the app could start against it.

## Rollout

The six-step plan in docs/handoff.md: shadow ingest with the kill switch
ON, reconcile confidence, private channel, household channel, retire old
Costanza, volsync restore drill (procedure above).
