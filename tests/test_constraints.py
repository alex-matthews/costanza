"""Hard-constraint greps from the build prompt, enforced as tests.

These encode the definition-of-done greps so a regression fails CI, not
just a manual audit: discord.py stays behind the adapter, no outbound
write verb exists anywhere in src (explicit allowlist below), and
forbidden dependency families stay out.
"""

import re
from pathlib import Path

SRC = Path(__file__).parent.parent / "src" / "costanza"
TESTS = Path(__file__).parent
PYPROJECT = Path(__file__).parent.parent / "pyproject.toml"

_DISCORD_IMPORT = re.compile(r"^\s*(import discord\b|from discord\b)", re.MULTILINE)


def _py_files(root: Path):
    return sorted(root.rglob("*.py"))


def test_no_discord_import_outside_adapter():
    offenders = []
    for path in _py_files(SRC) + _py_files(TESTS):
        if "adapters/discord" in str(path):
            continue
        if _DISCORD_IMPORT.search(path.read_text()):
            offenders.append(str(path))
    assert offenders == []


# The no-external-writes property is claimed for the whole binary, so the
# scan covers the whole src tree, not just clients/. Explicit allowlist:
#
#   replay.py — self-targeting dev tool: POSTs recorded fixtures at a
#               scratch instance of *this* service on localhost. It is the
#               e2e smoke harness, not an external write path.
#
# Nothing else may be exempted. Inbound FastAPI route *declarations*
# (`@router.post(...)`) declare endpoints this service serves; they are
# not outbound writes and are skipped per-line.
_WRITE_VERB_ALLOWLIST = {"replay.py"}
_INBOUND_ROUTE_DECL = re.compile(r"^\s*@(router|app)\.(post|put|patch|delete)\b")


def test_no_external_write_verbs_anywhere_in_src():
    """No write code paths to any external system exist in the binary."""
    verbs = re.compile(r"\.(post|put|patch|delete)\s*\(|\brequest\(\s*['\"]"
                       r"(POST|PUT|PATCH|DELETE)", re.IGNORECASE)
    offenders = []
    for path in _py_files(SRC):
        if path.name in _WRITE_VERB_ALLOWLIST:
            continue
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            if _INBOUND_ROUTE_DECL.match(line):
                continue
            if verbs.search(line):
                offenders.append(f"{path}:{lineno}: {line.strip()}")
    assert offenders == []


def test_write_verb_allowlist_is_tight():
    """The allowlist must not accumulate silently."""
    assert _WRITE_VERB_ALLOWLIST == {"replay.py"}
    assert (SRC / "replay.py").exists()


def test_no_forbidden_dependencies():
    text = PYPROJECT.read_text().lower()
    for forbidden in ("litellm", "openai", "anthropic", "redis", "psycopg",
                      "postgres", "asyncpg", "sqlalchemy"):
        assert forbidden not in text, f"forbidden dependency family: {forbidden}"


def test_no_llm_or_prompt_code():
    pattern = re.compile(r"litellm|prompt_template|chat.?completion", re.IGNORECASE)
    offenders = [str(p) for p in _py_files(SRC) if pattern.search(p.read_text())]
    assert offenders == []


def test_nothing_knows_chaski_exists():
    """ADR-0004: inbound contract is source-native; no tee awareness in code."""
    offenders = [
        str(p) for p in _py_files(SRC) if re.search(r"chaski", p.read_text(), re.IGNORECASE)
    ]
    assert offenders == []
