"""Tautulli read-only client: history (reconcile/backfill) + users (identity_sync)."""

from __future__ import annotations

from datetime import datetime

import httpx

from .base import ReadOnlyClient


class TautulliClient:
    def __init__(
        self, base_url: str, api_key: str, transport: httpx.BaseTransport | None = None
    ):
        self._http = ReadOnlyClient(base_url, transport=transport)
        self._api_key = api_key

    def _cmd(self, cmd: str, **params) -> dict:
        data = self._http.get("/api/v2", {"apikey": self._api_key, "cmd": cmd, **params})
        return (data.get("response") or {}).get("data") or {}

    def get_history(self, after: datetime | None = None, length: int = 500) -> list[dict]:
        params: dict = {"length": length, "order_column": "date", "order_dir": "desc"}
        if after is not None:
            params["after"] = after.date().isoformat()
        data = self._cmd("get_history", **params)
        return data.get("data") or []

    def get_users(self) -> list[dict]:
        data = self._cmd("get_users")
        return data if isinstance(data, list) else []

    def close(self) -> None:
        self._http.close()
