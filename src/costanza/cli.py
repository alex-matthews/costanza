"""Entry points: `costanza serve` (production) and `costanza replay` (e2e smoke)."""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="costanza")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("serve", help="run the service (webhooks + API + workers + jobs)")
    sub.add_parser("replay", help="feed fixtures at a scratch instance and verify e2e")
    args = parser.parse_args(argv)

    if args.command == "serve":
        import asyncio

        import uvicorn

        from .config import Settings
        from .main import create_app, create_metrics_app

        settings = Settings()
        log_level = settings.log_level.lower()
        configs = [
            uvicorn.Config(
                create_app(),
                host=settings.listen_host,
                port=settings.listen_port,
                log_level=log_level,
            )
        ]
        # Metrics on a dedicated listener (org convention: 8081, off the main port).
        if settings.metrics_enabled:
            configs.append(
                uvicorn.Config(
                    create_metrics_app(),
                    host=settings.listen_host,
                    port=settings.metrics_port,
                    log_level=log_level,
                )
            )
        servers = [uvicorn.Server(c) for c in configs]

        async def _run() -> None:
            await asyncio.gather(*(s.serve() for s in servers))

        asyncio.run(_run())
        return 0

    if args.command == "replay":
        from .replay import run_replay

        return run_replay()

    return 2


if __name__ == "__main__":
    sys.exit(main())
