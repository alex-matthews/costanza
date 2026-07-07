"""Costanza: household media event hub (observe + notify, Tiers 0-1)."""

from importlib import metadata

try:
    __version__ = metadata.version("costanza")
except metadata.PackageNotFoundError:  # running from a source tree
    __version__ = "0.0.0.dev0"
