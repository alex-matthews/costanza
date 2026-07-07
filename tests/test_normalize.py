"""Golden fixture tests per normalizer per source (the highest-value suite).

Each fixtures/<source>/<name>.json payload has a <name>.expected.json
sidecar: {"watch": {...optional override...}, "events": [...]}. Events are
compared with volatile fields (id, timestamps) excluded. Regenerate after
an intentional contract change with:

    uv run python tests/test_normalize.py --regen
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from costanza.config import WatchCompletionConfig
from costanza.normalize import NORMALIZERS, normalize
from costanza.schemas import EVENT_TYPES

FIXTURES = Path(__file__).parent.parent / "fixtures"
SOURCES = ("seerr", "radarr", "sonarr", "tautulli")

_EXCLUDE = {"id", "occurred_at", "received_at"}


def _cases() -> list[tuple[str, Path]]:
    cases = []
    for source in SOURCES:
        for payload_path in sorted((FIXTURES / source).glob("*.json")):
            if payload_path.name.endswith(".expected.json"):
                continue
            cases.append((source, payload_path))
    return cases


def _run(source: str, payload_path: Path) -> tuple[dict, list[dict]]:
    expected_path = payload_path.with_suffix(".expected.json")
    expected = json.loads(expected_path.read_text()) if expected_path.exists() else {}
    watch = WatchCompletionConfig.model_validate(expected.get("watch") or {})
    payload = json.loads(payload_path.read_text())
    events = normalize(source, source, payload, watch)
    dumped = [
        e.model_dump(mode="json", exclude=_EXCLUDE, exclude_none=True) for e in events
    ]
    return expected, dumped


@pytest.mark.parametrize(
    ("source", "payload_path"), _cases(), ids=lambda v: v.name if isinstance(v, Path) else v
)
def test_golden(source: str, payload_path: Path):
    expected, dumped = _run(source, payload_path)
    assert expected, f"missing golden: {payload_path.with_suffix('.expected.json')}"
    assert dumped == expected["events"]


@pytest.mark.parametrize(
    ("source", "payload_path"), _cases(), ids=lambda v: v.name if isinstance(v, Path) else v
)
def test_invariants(source: str, payload_path: Path):
    """Structural rules every normalizer output must satisfy."""
    _, dumped = _run(source, payload_path)
    assert dumped, "normalizers never drop payloads (source.unknown at minimum)"
    for event in dumped:
        assert event["type"] in EVENT_TYPES
        assert event["source"] == source
        assert event["source_event_key"].startswith(f"{source}:")
        assert event["origin"] == "webhook"


def test_normalize_is_deterministic():
    """Same payload -> same source_event_key (tee/retry dedupe guarantee)."""
    for source, payload_path in _cases():
        payload = json.loads(payload_path.read_text())
        keys_a = [e.source_event_key for e in normalize(source, source, payload)]
        keys_b = [e.source_event_key for e in normalize(source, source, payload)]
        assert keys_a == keys_b


def test_unknown_source_kind_rejected():
    with pytest.raises(ValueError):
        normalize("bazarr", "bazarr", {})


def test_every_normalizer_has_fixtures():
    for kind in NORMALIZERS:
        assert any(source == kind for source, _ in _cases())


def _regen() -> None:
    for source, payload_path in _cases():
        expected_path = payload_path.with_suffix(".expected.json")
        existing = json.loads(expected_path.read_text()) if expected_path.exists() else {}
        watch_override = existing.get("watch")
        watch = WatchCompletionConfig.model_validate(watch_override or {})
        payload = json.loads(payload_path.read_text())
        events = normalize(source, source, payload, watch)
        out: dict = {}
        if watch_override:
            out["watch"] = watch_override
        out["events"] = [
            e.model_dump(mode="json", exclude=_EXCLUDE, exclude_none=True) for e in events
        ]
        expected_path.write_text(json.dumps(out, indent=2) + "\n")
        print(f"wrote {expected_path}")


if __name__ == "__main__":
    import sys

    if "--regen" in sys.argv:
        _regen()
