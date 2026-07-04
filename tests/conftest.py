import json
import socket
from datetime import UTC, datetime
from pathlib import Path

import pytest

from costanza.config import (
    ChannelConfig,
    DigestConfig,
    HouseholdUser,
    RateLimitConfig,
    RouteRule,
    RoutingConfig,
    Settings,
    SourceConfig,
)
from costanza.store import Store

FIXTURES = Path(__file__).parent.parent / "fixtures"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Tests never touch the network (house rule: offline by default)."""

    def guard(*args, **kwargs):
        raise RuntimeError("network access is disabled in tests")

    monkeypatch.setattr(socket.socket, "connect", guard)


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture
def store(tmp_path: Path) -> Store:
    return Store(tmp_path / "test.db")


@pytest.fixture
def routing() -> RoutingConfig:
    return RoutingConfig(
        sources=[
            SourceConfig(name="seerr", kind="seerr"),
            SourceConfig(name="radarr", kind="radarr"),
            SourceConfig(name="sonarr", kind="sonarr"),
            SourceConfig(name="tautulli", kind="tautulli"),
        ],
        channels={
            "media-feed": ChannelConfig(discord_channel_id=111),
            "media-digest": ChannelConfig(discord_channel_id=222),
            "media-admin": ChannelConfig(discord_channel_id=333),
        },
        rules=[
            RouteRule(types=["request.approved", "request.available"], channel="media-feed"),
            RouteRule(types=["health.issue", "reconcile.gap"], channel="media-admin"),
        ],
        admin_channel="media-admin",
        digest=DigestConfig(channel="media-digest"),
        rate_limits=RateLimitConfig(per_channel_per_minute=10),
        users=[
            HouseholdUser(
                display="Alice",
                admin=True,
                identities={
                    "seerr": "alice",
                    "plex": "alice",
                    "tautulli": "12",
                    "discord": "123456789",
                },
            ),
            HouseholdUser(
                display="Bob", identities={"seerr": "bob", "plex": "bob", "tautulli": "13"}
            ),
        ],
    )


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        db_path=tmp_path / "app.db",
        routing_path=tmp_path / "routing.yaml",
        kill_switch=False,
    )


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 7, 4, 12, 0, 0, tzinfo=UTC)


def load_fixture(*parts: str) -> dict | list:
    return json.loads(FIXTURES.joinpath(*parts).read_text())
