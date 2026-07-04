"""Adapter-boundary tests: embed mapping + failure isolation.

This file never imports discord directly; the adapter package is the only
place that dependency lives (grep-enforced in test_constraints.py).
"""

import pytest

from costanza.adapters.discord import DiscordNotifier, build_embed
from costanza.notify.ports import Notifier, NotifierUnavailable
from costanza.schemas import RenderedMessage


def _message(**overrides) -> RenderedMessage:
    base = dict(
        kind="embed",
        title="Now available: Arrival (2016)",
        description="Requested by Alice",
        fields=[("Quality", "WEBDL-2160p")],
        color=0x9B59B6,
        footer="source: seerr",
    )
    base.update(overrides)
    return RenderedMessage(**base)


def test_build_embed_maps_all_parts():
    embed = build_embed(_message())
    assert embed.title == "Now available: Arrival (2016)"
    assert embed.description == "Requested by Alice"
    assert embed.colour is not None and embed.colour.value == 0x9B59B6
    assert [(f.name, f.value, f.inline) for f in embed.fields] == [
        ("Quality", "WEBDL-2160p", False)
    ]
    assert embed.footer.text == "source: seerr"


def test_build_embed_truncates_discord_limits():
    embed = build_embed(
        _message(
            title="t" * 300,
            description="d" * 5000,
            fields=[(f"n{i}", "v" * 2000) for i in range(30)],
        )
    )
    assert len(embed.title) == 256
    assert len(embed.description) == 4000
    assert len(embed.fields) == 25
    assert all(len(f.value) <= 1024 for f in embed.fields)


def test_adapter_satisfies_notifier_port(routing):
    adapter = DiscordNotifier("token", routing)
    assert isinstance(adapter, Notifier)


async def test_send_unconnected_raises_unavailable_not_crash(routing):
    adapter = DiscordNotifier("token", routing)
    with pytest.raises(NotifierUnavailable):
        await adapter.send("media-feed", _message())


async def test_send_unmapped_channel_raises_unavailable(routing):
    routing.channels["media-feed"].discord_channel_id = None
    adapter = DiscordNotifier("token", routing)
    with pytest.raises(NotifierUnavailable, match="no discord_channel_id"):
        await adapter.send("media-feed", _message())
