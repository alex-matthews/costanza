"""Shared GET-only HTTP client wrapper."""

from __future__ import annotations

from typing import Any

import httpx


class ClientError(Exception):
    """Sanitized client failure.

    httpx exceptions embed the full request URL — for Tautulli that means
    `?apikey=...` — and job code logs `str(exc)` into logs and reconcile
    summaries. Every failure is therefore re-raised as this type, built
    only from the path and status/error class, never the URL or params.
    The cause chain is deliberately severed (`from None`) so tracebacks
    cannot resurface the secret either.
    """


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
        try:
            response = self._client.get(path, params=params)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ClientError(f"GET {path} -> HTTP {exc.response.status_code}") from None
        except httpx.HTTPError as exc:
            raise ClientError(f"GET {path} failed: {type(exc).__name__}") from None
        try:
            return response.json()
        except ValueError:
            raise ClientError(f"GET {path} returned non-JSON body") from None

    def close(self) -> None:
        self._client.close()
