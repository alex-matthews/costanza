"""Hourly reconcile: poll read APIs, diff against the store, synthesize
missed events (`origin=reconcile`) — but ONLY where the guarantees matrix
in architecture.md says the source retains the truth:

| source        | reconstructable                    | flag-only (gap marker)         |
| seerr         | request lifecycle                  | —                              |
| radarr/sonarr | grab/import/upgrade/delete history | health issues, failed grabs    |
| tautulli      | watch.completed                    | playback.started/stopped       |

When a source recovered missed events and has flag-only kinds, one
`reconcile.gap` marker event is stored for the window instead of
pretending completeness.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from ..config import RoutingConfig
from ..correlate import Correlator
from ..logging import get_logger
from ..normalize.common import to_int
from ..schemas import CanonicalEvent, MediaRef, UserRef, utcnow
from ..store import Store

log = get_logger(__name__)

DEFAULT_LOOKBACK = timedelta(hours=24)

# Flag-only event kinds per source kind (the right column of the matrix).
TRANSIENT_KINDS = {
    "radarr": ["health.issue", "failed downloads"],
    "sonarr": ["health.issue", "failed downloads"],
    "tautulli": ["playback.started", "playback.stopped"],
}

# Seerr enums (Overseerr-family API).
_SEERR_REQUEST_DECLINED = 3
_SEERR_REQUEST_APPROVED = 2
_SEERR_MEDIA_PARTIAL = 4
_SEERR_MEDIA_AVAILABLE = 5

# Arr history eventType -> canonical type. Anything else (failed grabs,
# ignored, renamed, health) is flag-only per the matrix: never synthesized.
_ARR_HISTORY_TYPES = {
    "grabbed": "media.grabbed",
    "downloadFolderImported": "media.imported",
    "movieFileDeleted": "media.deleted",
    "episodeFileDeleted": "media.deleted",
}


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def run_reconcile(
    store: Store,
    correlator: Correlator,
    routing: RoutingConfig,
    clients: dict[str, object],
    now: datetime | None = None,
) -> dict[str, dict]:
    """Reconcile every configured source that has a client. Returns a summary."""
    now = now or utcnow()
    summary: dict[str, dict] = {}
    for source in routing.sources:
        client = clients.get(source.name)
        if client is None or not source.enabled:
            continue
        cursor = store.get_cursor(f"reconcile:{source.name}") or {}
        window_start = _parse_dt(cursor.get("last_run")) or (now - DEFAULT_LOOKBACK)
        try:
            if source.kind == "seerr":
                recovered = _reconcile_seerr(store, correlator, source.name, client, now)
            elif source.kind in ("radarr", "sonarr"):
                recovered = _reconcile_arr(
                    store, correlator, source.name, client, window_start, now
                )
            elif source.kind == "tautulli":
                recovered = _reconcile_tautulli(
                    store, correlator, source.name, client, window_start, now
                )
            else:
                continue
        except Exception as exc:  # noqa: BLE001 — one broken source must not stop the rest
            log.error("reconcile failed", source=source.name, error=str(exc))
            summary[source.name] = {"error": str(exc)}
            continue

        gap_marked = False
        if recovered and source.kind in TRANSIENT_KINDS:
            gap_marked = _mark_gap(
                correlator, source.name, source.kind, window_start, recovered, now
            )
        store.set_cursor(f"reconcile:{source.name}", {"last_run": now.isoformat()}, now)
        summary[source.name] = {"recovered": recovered, "gap_marked": gap_marked}
        if recovered:
            log.info("reconcile recovered events", source=source.name, recovered=recovered)
    return summary


def _mark_gap(
    correlator: Correlator,
    source_name: str,
    source_kind: str,
    window_start: datetime,
    recovered: int,
    now: datetime,
) -> bool:
    marker = CanonicalEvent(
        source=source_name,
        source_event_key=f"{source_name}:reconcile.gap:{window_start.isoformat()}",
        origin="reconcile",
        type="reconcile.gap",
        occurred_at=now,
        received_at=now,
        attrs={
            "window_start": window_start.isoformat(),
            "recovered": recovered,
            "transient_kinds": TRANSIENT_KINDS[source_kind],
        },
    )
    return correlator.apply(marker)


# -- seerr: request lifecycle is fully reconstructable --------------------------


def _seerr_expected(source: str, request: dict) -> list[CanonicalEvent]:
    request_id = request.get("id")
    media = request.get("media") or {}
    requested_by = (request.get("requestedBy") or {}).get("username")
    created_at = _parse_dt(request.get("createdAt"))
    updated_at = _parse_dt(request.get("updatedAt")) or created_at

    media_ref = MediaRef(
        tmdb_id=to_int(media.get("tmdbId")),
        tvdb_id=to_int(media.get("tvdbId")),
        kind="series" if media.get("mediaType") == "tv" else "movie",
    )
    user_ref = (
        UserRef(provider="seerr", external_id=str(requested_by), display=str(requested_by))
        if requested_by
        else None
    )

    def event(type_: str, key: str, occurred: datetime | None, **attrs) -> CanonicalEvent:
        return CanonicalEvent(
            source=source,
            source_event_key=key,
            origin="reconcile",
            type=type_,
            occurred_at=occurred,
            media=media_ref.model_copy(deep=True),
            user=user_ref.model_copy(deep=True) if user_ref else None,
            attrs={"request_id": str(request_id), **attrs},
        )

    expected = [
        event("request.created", f"{source}:request.created:{request_id}", created_at)
    ]
    status = request.get("status")
    if status == _SEERR_REQUEST_APPROVED:
        expected.append(
            event("request.approved", f"{source}:request.approved:{request_id}", updated_at)
        )
    elif status == _SEERR_REQUEST_DECLINED:
        expected.append(
            event("request.declined", f"{source}:request.declined:{request_id}", updated_at)
        )
    media_status = media.get("status")
    if media_status in (_SEERR_MEDIA_PARTIAL, _SEERR_MEDIA_AVAILABLE):
        label = "AVAILABLE" if media_status == _SEERR_MEDIA_AVAILABLE else "PARTIALLY_AVAILABLE"
        expected.append(
            event(
                "request.available",
                f"{source}:request.available:{request_id}:{label}",
                updated_at,
                partial=media_status == _SEERR_MEDIA_PARTIAL,
            )
        )
    return expected


def _reconcile_seerr(
    store: Store, correlator: Correlator, source: str, client, now: datetime
) -> int:
    recovered = 0
    for request in client.get_requests():
        for event in _seerr_expected(source, request):
            if store.event_key_exists(event.source_event_key):
                continue
            event.received_at = now
            if correlator.apply(event):
                recovered += 1
    return recovered


# -- radarr/sonarr: history is mostly reconstructable ----------------------------


def _arr_record_event(source: str, record: dict) -> CanonicalEvent | None:
    canonical = _ARR_HISTORY_TYPES.get(record.get("eventType") or "")
    date = _parse_dt(record.get("date"))
    download_id = record.get("downloadId")

    movie = record.get("movie") or {}
    series = record.get("series") or {}
    episode = record.get("episode") or {}

    if movie:
        media_key = str(to_int(movie.get("tmdbId")) or record.get("movieId"))
        media_ref = MediaRef(
            tmdb_id=to_int(movie.get("tmdbId")),
            imdb_id=movie.get("imdbId") or None,
            title=movie.get("title"),
            year=to_int(movie.get("year")),
            kind="movie",
        )
        ep_segment = None
    elif series:
        media_key = str(to_int(series.get("tvdbId")) or record.get("seriesId"))
        season = to_int(episode.get("seasonNumber"))
        number = to_int(episode.get("episodeNumber"))
        ep_segment = f"S{season or 0:02d}E{number or 0:02d}"
        media_ref = MediaRef(
            tmdb_id=to_int(series.get("tmdbId")),
            tvdb_id=to_int(series.get("tvdbId")),
            title=series.get("title"),
            year=to_int(series.get("year")),
            kind="episode" if number is not None else "series",
            detail={"season": season, "episode": number} if number is not None else {},
        )
    else:
        return None

    if canonical is None:
        return None
    if canonical == "media.imported" and record.get("data", {}).get("isUpgrade") in (
        True,
        "true",
        "True",
    ):
        canonical = "media.upgraded"

    parts = [source, canonical, media_key]
    if canonical == "media.deleted":
        parts.insert(2, "file")
    if ep_segment:
        parts.append(ep_segment)
    parts.append(download_id or f"history-{record.get('id')}")
    attrs: dict = {}
    if canonical == "media.deleted":
        attrs["scope"] = "file"
    if quality := ((record.get("quality") or {}).get("quality") or {}).get("name"):
        attrs["quality"] = quality
    return CanonicalEvent(
        source=source,
        source_event_key=":".join(parts),
        origin="reconcile",
        type=canonical,
        occurred_at=date,
        media=media_ref,
        attrs=attrs,
    )


def _reconcile_arr(
    store: Store,
    correlator: Correlator,
    source: str,
    client,
    window_start: datetime,
    now: datetime,
) -> int:
    recovered = 0
    for record in client.get_history(since=window_start):
        event = _arr_record_event(source, record)
        if event is None:
            continue  # flag-only kinds (health, failures) are never synthesized
        if store.event_key_exists(event.source_event_key):
            continue
        # Fuzzy dedupe: the webhook twin may group episodes differently or
        # carry the same downloadId under another key shape.
        download_id = record.get("downloadId")
        if download_id:
            media_key = event.source_event_key.split(":")[2]
            if store.event_key_like(f"{source}:{event.type}:{media_key}:%{download_id}"):
                continue
        if event.type == "media.deleted" and event.media is not None:
            # Deletes carry no shared id between webhook and history; guard
            # on same-type-same-media within a day instead of double-storing.
            media_id = store.find_or_create_media(event.media)
            event.media.media_id = media_id
            occurred = event.occurred_at or now
            if store.has_event_near("media.deleted", media_id, occurred):
                continue
        event.received_at = now
        if correlator.apply(event):
            recovered += 1
    return recovered


# -- tautulli: watch.completed is reconstructable; playback is flag-only ---------


def _reconcile_tautulli(
    store: Store,
    correlator: Correlator,
    source: str,
    client,
    window_start: datetime,
    now: datetime,
) -> int:
    recovered = 0
    for row in client.get_history(after=window_start):
        if row.get("watched_status") not in (1, "1"):
            continue  # partial plays and playback rows are not durable truth
        user_key = str(row.get("user_id") or row.get("user") or "unknown")
        rating_key = row.get("rating_key")
        key = f"{source}:watch.completed:{user_key}:{rating_key}"
        if store.event_key_exists(key):
            continue
        is_episode = row.get("media_type") == "episode"
        detail = {}
        if is_episode:
            detail = {
                "season": to_int(row.get("parent_media_index")),
                "episode": to_int(row.get("media_index")),
            }
        stopped = row.get("stopped") or row.get("date")
        occurred = (
            datetime.fromtimestamp(int(stopped), tz=window_start.tzinfo)
            if stopped
            else None
        )
        event = CanonicalEvent(
            source=source,
            source_event_key=key,
            origin="reconcile",
            type="watch.completed",
            occurred_at=occurred,
            received_at=now,
            media=MediaRef(
                title=row.get("grandparent_title") if is_episode else row.get("title"),
                year=to_int(row.get("year")),
                kind="episode" if is_episode else "movie",
                detail=detail,
            ),
            user=UserRef(
                provider="tautulli",
                external_id=str(row.get("user_id")) if row.get("user_id") else None,
                display=row.get("user"),
            )
            if row.get("user_id") or row.get("user")
            else None,
            attrs={"backfilled": True},
        )
        if correlator.apply(event):
            recovered += 1
    return recovered
