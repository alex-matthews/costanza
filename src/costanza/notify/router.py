"""Config-driven event-type allowlist x channel routing.

The router is the single notification policy point: every stored event
(any origin) is offered; only rule matches produce ledger rows. No rule =
stored but silent.
"""

from __future__ import annotations

from ..config import RoutingConfig
from ..schemas import CanonicalEvent


def channels_for(event: CanonicalEvent, routing: RoutingConfig) -> list[str]:
    channels: list[str] = []
    for rule in routing.rules:
        if event.type not in rule.types:
            continue
        if rule.sources is not None and event.source not in rule.sources:
            continue
        if rule.channel not in channels:
            channels.append(rule.channel)
    return channels
