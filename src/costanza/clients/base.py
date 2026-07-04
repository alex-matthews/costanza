"""Shared GET-only HTTP client wrapper."""

from __future__ import annotations

from typing import Any

import httpx


class ReadOnlyClient:
    """The only HTTP verb this class knows is GET. Keep it that way."""

    def __init__(
        self,
        base_url: str,
        headers: dict[str, str] | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 15.0,
    ):
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers=headers or {},
            transport=transport,
            timeout=timeout,
        )

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        response = self._client.get(path, params=params)
        response.raise_for_status()
        return response.json()

    def close(self) -> None:
        self._client.close()
