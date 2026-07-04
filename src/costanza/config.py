"""Env-first settings (pydantic-settings) + routing.yaml (ConfigMap) models.

Fail-fast: `load_config()` raises on a missing/invalid routing file or a
malformed users/sources block. Secrets never live in routing.yaml — webhook
secrets and API keys come from env (`WEBHOOK_SECRET__{SOURCE}`,
`{SOURCE}_API_KEY`), matching the ExternalSecret contract in handoff.md.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .schemas import IdentityProvider

SOURCE_KINDS = ("seerr", "radarr", "sonarr", "tautulli")


def _env_name(source: str) -> str:
    return source.upper().replace("-", "_")


class SourceConfig(BaseModel):
    """A config-registered webhook source instance.

    Adding e.g. `radarr-se` later is a pure config change: a new entry here
    plus a `WEBHOOK_SECRET__RADARR_SE` env var. No code change.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    kind: str  # seerr | radarr | sonarr | tautulli
    url: str | None = None  # base URL for the read-only client (reconcile etc.)
    enabled: bool = True

    @model_validator(mode="after")
    def _check_kind(self) -> SourceConfig:
        if self.kind not in SOURCE_KINDS:
            raise ValueError(f"unknown source kind {self.kind!r} (known: {SOURCE_KINDS})")
        return self

    @property
    def secret_env(self) -> str:
        return f"WEBHOOK_SECRET__{_env_name(self.name)}"

    @property
    def api_key_env(self) -> str:
        return f"{_env_name(self.name)}_API_KEY"

    def secret(self) -> str | None:
        return os.environ.get(self.secret_env)

    def api_key(self) -> str | None:
        return os.environ.get(self.api_key_env)


class ChannelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    discord_channel_id: int | None = None


class RouteRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    types: list[str]  # event-type allowlist for this rule
    channel: str
    sources: list[str] | None = None  # optionally restrict to source names


class DigestConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel: str | None = None
    cron: str = "0 18 * * 0"  # weekly, Sunday 18:00


class WatchCompletionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # OQ-3: consume Tautulli's `watched` trigger if configured; otherwise
    # derive watch.completed from playback.stopped progress >= threshold.
    tautulli_watched_trigger: bool = True
    progress_threshold: int = 85


class RateLimitConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    per_channel_per_minute: int = 10


class HouseholdUser(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display: str
    admin: bool = False
    active: bool = True
    identities: dict[IdentityProvider, str] = Field(default_factory=dict)


class RoutingConfig(BaseModel):
    """Contents of routing.yaml: sources, channels, rules, digest, identity map."""

    model_config = ConfigDict(extra="forbid")

    sources: list[SourceConfig] = Field(default_factory=list)
    channels: dict[str, ChannelConfig] = Field(default_factory=dict)
    rules: list[RouteRule] = Field(default_factory=list)
    admin_channel: str | None = None
    digest: DigestConfig = Field(default_factory=DigestConfig)
    watch_completion: WatchCompletionConfig = Field(default_factory=WatchCompletionConfig)
    rate_limits: RateLimitConfig = Field(default_factory=RateLimitConfig)
    users: list[HouseholdUser] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_refs(self) -> RoutingConfig:
        names = [s.name for s in self.sources]
        if len(names) != len(set(names)):
            raise ValueError("duplicate source names in routing.yaml")
        known = set(self.channels)
        for rule in self.rules:
            if rule.channel not in known:
                raise ValueError(f"rule routes to unknown channel {rule.channel!r}")
        if self.digest.channel and self.digest.channel not in known:
            raise ValueError(f"digest channel {self.digest.channel!r} not in channels")
        if self.admin_channel and self.admin_channel not in known:
            raise ValueError(f"admin channel {self.admin_channel!r} not in channels")
        return self

    def source(self, name: str) -> SourceConfig | None:
        for s in self.sources:
            if s.name == name:
                return s
        return None


class Settings(BaseSettings):
    """Env-first runtime settings. Prefix COSTANZA_ except named secrets."""

    model_config = SettingsConfigDict(env_prefix="COSTANZA_", extra="ignore")

    db_path: Path = Path("/data/costanza.db")
    routing_path: Path = Path("/config/routing.yaml")

    listen_host: str = "0.0.0.0"  # noqa: S104 — container service
    listen_port: int = 8140
    log_level: str = "INFO"

    # Fire-alarm override: forces silence regardless of the stored toggle.
    kill_switch: bool = False

    api_bearer_token: str | None = Field(
        default=None, validation_alias=AliasChoices("API_BEARER_TOKEN", "COSTANZA_API_BEARER_TOKEN")
    )
    discord_token: str | None = Field(
        default=None, validation_alias=AliasChoices("DISCORD_TOKEN", "COSTANZA_DISCORD_TOKEN")
    )

    webhook_body_max_bytes: int = 1_048_576
    raw_retention_days: int = 30  # OQ-7

    outbox_max_attempts: int = 5
    outbox_backoff_base_seconds: float = 2.0
    outbox_poll_interval_seconds: float = 1.0

    notify_max_attempts: int = 8
    notify_backoff_base_seconds: float = 5.0
    notify_poll_interval_seconds: float = 2.0

    reconcile_interval_minutes: int = 60
    prune_cron: str = "30 4 * * *"
    identity_sync_cron: str = "0 5 * * *"


class Config(BaseModel):
    """Settings + parsed routing.yaml, loaded once at startup."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    settings: Settings
    routing: RoutingConfig


def load_routing(path: Path) -> RoutingConfig:
    if not path.exists():
        raise FileNotFoundError(
            f"routing config not found at {path}; set COSTANZA_ROUTING_PATH "
            "(the container ships a default at /config/routing.yaml)"
        )
    data = yaml.safe_load(path.read_text()) or {}
    return RoutingConfig.model_validate(data)


def load_config(settings: Settings | None = None) -> Config:
    settings = settings or Settings()
    routing = load_routing(settings.routing_path)
    return Config(settings=settings, routing=routing)
