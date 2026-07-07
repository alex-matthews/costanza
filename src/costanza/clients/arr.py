"""Radarr/Sonarr read-only client: /history for reconciliation."""

from __future__ import annotations

from datetime import datetime

import httpx

from .base import ReadOnlyClient


class ArrClient:
    def __init__(
        self, base_url: str, api_key: str, transport: httpx.BaseTransport | None = None
    ):
        self._http = ReadOnlyClient(base_url, {"X-Api-Key": api_key}, transport)

    def get_history(
        self,
        since: datetime | None = None,
        page_size: int = 100,
        max_pages: int = 20,
    ) -> list[dict]:
        """History records, newest first, stopping at `since` when given."""
        records: list[dict] = []
        for page in range(1, max_pages + 1):
            data = self._http.get(
                "/api/v3/history",
                {
                    "page": page,
                    "pageSize": page_size,
                    "sortKey": "date",
                    "sortDirection": "descending",
                },
            )
            page_records = data.get("records") or []
            for record in page_records:
                if since is not None:
                    date = record.get("date")
                    if date and datetime.fromisoformat(date) < since:
                        return records
                records.append(record)
            if len(page_records) < page_size:
                break
        return records

    def close(self) -> None:
        self._http.close()
