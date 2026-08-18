FROM python:3.14-alpine3.24@sha256:05b2b8b732ecd268fee8727a369f936f022d1321b59befd13c30ede22769dcdc AS build

COPY --from=ghcr.io/astral-sh/uv:0.12.5@sha256:e85be844203885286c60ffad8a858d48afb6c5a5c237ca0e67f12e74b8f174b1 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
RUN uv sync --locked --no-dev --no-editable

FROM python:3.14-alpine3.24@sha256:05b2b8b732ecd268fee8727a369f936f022d1321b59befd13c30ede22769dcdc

ARG VERSION=dev
ARG REVISION=unknown
LABEL org.opencontainers.image.source="https://github.com/alex-matthews/costanza" \
      org.opencontainers.image.description="Household media event hub: observe + notify (Tiers 0-1)" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}"

COPY --from=build /app/.venv /app/.venv

# Identity-agnostic image (home-operations/containers precedent, e.g.
# apps/tautulli): no user is created, nothing is chown'd, and no config is
# baked in. Kubernetes owns storage identity (runAsUser/runAsGroup/fsGroup —
# 1032:100 in this cluster) and supplies /data (PVC) and
# /config/routing.yaml (ConfigMap); `nobody:nogroup` is only the default
# for bare `docker run`s. Bytecode is precompiled at build time, so the
# image runs with a read-only rootfs under any arbitrary uid:gid.
# /config and /data exist empty (no chown) so ConfigMap subPath/file
# mounts and PVC mount points have stable targets under kubelet with a
# read-only rootfs, not just under Docker bind mounts.
RUN mkdir -p /config /data

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    COSTANZA_DB_PATH=/data/costanza.db \
    COSTANZA_ROUTING_PATH=/config/routing.yaml

# Numeric uid:gid (= nobody:nogroup) so hosts and Kubernetes runAsNonRoot
# checks can resolve it without the image's /etc/passwd (DL3066).
USER 65534:65534
# 8080 main app, 8081 metrics (home-operations org port convention).
EXPOSE 8080 8081

ENTRYPOINT ["costanza"]
CMD ["serve"]
