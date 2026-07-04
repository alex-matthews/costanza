"""Hard-constraint greps from the build prompt, enforced as tests.

These encode the definition-of-done greps so a regression fails CI, not
just a manual audit: discord.py stays behind the adapter, read clients
never grow write verbs, and forbidden dependency families stay out.
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


def test_clients_are_get_only():
    """No write code paths to external systems: clients never POST/PUT/etc."""
    verbs = re.compile(r"\.(post|put|patch|delete)\s*\(|\brequest\(\s*['\"]"
                       r"(POST|PUT|PATCH|DELETE)", re.IGNORECASE)
    clients_dir = SRC / "clients"
    offenders = []
    for path in _py_files(clients_dir) if clients_dir.exists() else []:
        if verbs.search(path.read_text()):
            offenders.append(str(path))
    assert offenders == []


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
