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
        import uvicorn

        from .config import Settings

        settings = Settings()
        uvicorn.run(
            "costanza.main:create_app",
            factory=True,
            host=settings.listen_host,
            port=settings.listen_port,
            log_level=settings.log_level.lower(),
        )
        return 0

    if args.command == "replay":
        from .replay import run_replay

        return run_replay()

    return 2


if __name__ == "__main__":
    sys.exit(main())
