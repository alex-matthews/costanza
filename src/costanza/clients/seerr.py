"""Seerr read-only client: request list (reconcile) + user list (identity_sync)."""

from __future__ import annotations

import httpx

from .base import ReadOnlyClient


class SeerrClient:
    def __init__(
        self, base_url: str, api_key: str, transport: httpx.BaseTransport | None = None
    ):
        self._http = ReadOnlyClient(base_url, {"X-Api-Key": api_key}, transport)

    def get_requests(self, page_size: int = 100, max_pages: int = 50) -> list[dict]:
        """All requests (paged); reconcile diffs these against the store."""
        results: list[dict] = []
        skip = 0
        for _ in range(max_pages):
            data = self._http.get("/api/v1/request", {"take": page_size, "skip": skip})
            page = data.get("results") or []
            results.extend(page)
            if len(page) < page_size:
                break
            skip += page_size
        return results

    def get_users(self, page_size: int = 100, max_pages: int = 20) -> list[dict]:
        results: list[dict] = []
        skip = 0
        for _ in range(max_pages):
            data = self._http.get("/api/v1/user", {"take": page_size, "skip": skip})
            page = data.get("results") or []
            results.extend(page)
            if len(page) < page_size:
                break
            skip += page_size
        return results

    def close(self) -> None:
        self._http.close()
