"""Production wiring: FastAPI app + outbox worker + notify worker + bot + jobs.

One process, one container, one PVC (architecture.md Option A). Tests
bypass this and wire components directly.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI

from . import metrics
from .api import build_api_router, build_ops_router
from .clients import build_clients
from .config import Config, load_config
from .correlate import Correlator
from .ingest import SourceRegistry, build_ingest_router
from .jobs import run_digest, run_identity_sync, run_prune, run_reconcile
from .jobs.digest import digest_renderer
from .logging import configure_logging, get_logger
from .notify import KillSwitch, RateLimiter
from .notify.ports import Notifier
from .store import Store
from .worker import NullNotifier, build_processor, notify_loop, outbox_loop

log = get_logger(__name__)


@dataclass
class Runtime:
    config: Config
    store: Store
    correlator: Correlator
    kill: KillSwitch
    limiter: RateLimiter
    notifier: Notifier
    clients: dict[str, object] = field(default_factory=dict)
    scheduler: AsyncIOScheduler | None = None


def build_runtime(config: Config | None = None) -> Runtime:
    config = config or load_config()
    configure_logging(config.settings.log_level)

    store = Store(config.settings.db_path)
    store.sync_sources(config.routing.sources)
    store.sync_users(config.routing.users)

    kill = KillSwitch(store, env_override=config.settings.kill_switch)
    limiter = RateLimiter(config.routing.rate_limits.per_channel_per_minute)

    notifier: Notifier = NullNotifier()
    if config.settings.discord_token:
        # The adapter package is imported lazily and only here: core code
        # paths never load discord.py (ADR-0001).
        from .adapters.discord import DiscordNotifier

        notifier = DiscordNotifier(config.settings.discord_token, config.routing)

    # Pre-touch per-source label values so the alertable counters are
    # visible from the very first scrape, not the first event.
    for source in config.routing.sources:
        metrics.WEBHOOKS_RECEIVED.labels(source=source.name)
        metrics.WEBHOOK_AUTH_FAILURES.labels(source=source.name)

    metrics.bind_backlog_gauges(
        store.outbox_backlog,
        store.outbox_dead_count,
        lambda: sum(
            n for s, n in store.notification_counts().items() if s in ("pending", "failed")
        ),
    )

    return Runtime(
        config=config,
        store=store,
        correlator=Correlator(store),
        kill=kill,
        limiter=limiter,
        notifier=notifier,
        clients=build_clients(config.routing),
    )


def _build_scheduler(rt: Runtime) -> AsyncIOScheduler:
    settings = rt.config.settings
    routing = rt.config.routing
    kinds = {s.name: s.kind for s in routing.sources}
    scheduler = AsyncIOScheduler(timezone="UTC")

    async def reconcile_job() -> None:
        await asyncio.to_thread(
            run_reconcile, rt.store, rt.correlator, routing, rt.clients, rt.kill
        )

    async def digest_job() -> None:
        await asyncio.to_thread(run_digest, rt.store, routing, rt.kill)

    async def prune_job() -> None:
        await asyncio.to_thread(run_prune, rt.store, settings.raw_retention_days)

    async def identity_sync_job() -> None:
        await asyncio.to_thread(run_identity_sync, rt.store, rt.clients, kinds)

    scheduler.add_job(
        reconcile_job,
        IntervalTrigger(minutes=settings.reconcile_interval_minutes),
        id="reconcile",
    )
    scheduler.add_job(
        digest_job, CronTrigger.from_crontab(routing.digest.cron, timezone="UTC"), id="digest"
    )
    scheduler.add_job(
        prune_job, CronTrigger.from_crontab(settings.prune_cron, timezone="UTC"), id="prune"
    )
    scheduler.add_job(
        identity_sync_job,
        CronTrigger.from_crontab(settings.identity_sync_cron, timezone="UTC"),
        id="identity_sync",
    )
    return scheduler


def create_app(config: Config | None = None) -> FastAPI:
    rt = build_runtime(config)
    processor = build_processor(rt.store, rt.correlator, rt.config, rt.kill)
    special_renderers = {"digest": digest_renderer(rt.store)}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        tasks = [
            asyncio.create_task(outbox_loop(rt.store, processor, rt.config), name="outbox"),
            asyncio.create_task(
                notify_loop(
                    rt.store, rt.notifier, rt.limiter, rt.kill, rt.config, special_renderers
                ),
                name="notify",
            ),
        ]
        if hasattr(rt.notifier, "start"):
            rt.notifier.start()
        rt.scheduler = _build_scheduler(rt)
        rt.scheduler.start()
        log.info(
            "costanza started",
            sources=[s.name for s in rt.config.routing.sources],
            kill_switch=rt.kill.engaged(),
            notifier=type(rt.notifier).__name__,
        )
        try:
            yield
        finally:
            rt.scheduler.shutdown(wait=False)
            for task in tasks:
                task.cancel()
            if hasattr(rt.notifier, "stop"):
                await rt.notifier.stop()
            rt.store.close()

    app = FastAPI(title="costanza", version="0.1.0", lifespan=lifespan)
    app.include_router(
        build_ingest_router(
            SourceRegistry(rt.config.routing),
            rt.store,
            rt.config.settings.webhook_body_max_bytes,
        )
    )
    app.include_router(build_api_router(rt.config, rt.store, rt.kill))
    app.include_router(build_ops_router(rt.config, rt.store))
    app.state.runtime = rt
    return app
