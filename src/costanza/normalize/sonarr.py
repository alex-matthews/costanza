"""Sonarr webhook payloads -> canonical events.

One canonical event per payload: a multi-episode grab/import stays one
event (kind season/series) with the episode list in attrs — notification
noise control starts at normalization.
"""

from __future__ import annotations

from ..config import WatchCompletionConfig
from ..ids import sha16
from ..schemas import CanonicalEvent, MediaRef
from .common import to_int, unknown_event


def _episodes(payload: dict) -> list[dict]:
    return payload.get("episodes") or []


def _media(payload: dict) -> MediaRef | None:
    series = payload.get("series") or {}
    if not series:
        return None
    episodes = _episodes(payload)
    detail: dict = {}
    kind = "series"
    seasons = {to_int(e.get("seasonNumber")) for e in episodes}
    if len(episodes) == 1:
        kind = "episode"
        detail = {
            "season": to_int(episodes[0].get("seasonNumber")),
            "episode": to_int(episodes[0].get("episodeNumber")),
        }
    elif episodes and len(seasons) == 1:
        kind = "season"
        detail = {"season": seasons.pop()}
    return MediaRef(
        tmdb_id=to_int(series.get("tmdbId")),
        tvdb_id=to_int(series.get("tvdbId")),
        imdb_id=series.get("imdbId") or None,
        title=series.get("title"),
        year=to_int(series.get("year")),
        kind=kind,
        detail=detail,
    )


def _series_key(payload: dict) -> str:
    series = payload.get("series") or {}
    return str(to_int(series.get("tvdbId")) or series.get("id") or sha16(series))


def _ep_key(payload: dict) -> str:
    parts = [
        f"S{to_int(e.get('seasonNumber')) or 0:02d}E{to_int(e.get('episodeNumber')) or 0:02d}"
        for e in _episodes(payload)
    ]
    return "-".join(parts) or "S00E00"


def _episode_attrs(payload: dict) -> dict:
    episodes = _episodes(payload)
    attrs: dict = {}
    if episodes:
        attrs["episodes"] = [
            {
                "season": to_int(e.get("seasonNumber")),
                "episode": to_int(e.get("episodeNumber")),
                "title": e.get("title"),
            }
            for e in episodes
        ]
    release = payload.get("release") or {}
    episode_file = payload.get("episodeFile") or {}
    if quality := (episode_file.get("quality") or release.get("quality")):
        attrs["quality"] = quality
    if size := (episode_file.get("size") or release.get("size")):
        attrs["size"] = size
    if release.get("indexer"):
        attrs["indexer"] = release["indexer"]
    return attrs


def normalize_sonarr(
    source: str, payload: dict, watch: WatchCompletionConfig
) -> list[CanonicalEvent]:
    event_type = payload.get("eventType")
    media = _media(payload)
    skey = _series_key(payload)

    if event_type == "Grab":
        download_id = payload.get("downloadId") or sha16(payload.get("release") or payload)
        return [
            CanonicalEvent(
                source=source,
                source_event_key=f"{source}:media.grabbed:{skey}:{_ep_key(payload)}:{download_id}",
                type="media.grabbed",
                media=media,
                attrs=_episode_attrs(payload),
            )
        ]

    if event_type == "Download":
        upgrade = bool(payload.get("isUpgrade"))
        canonical = "media.upgraded" if upgrade else "media.imported"
        episode_file = payload.get("episodeFile") or {}
        discriminator = payload.get("downloadId") or sha16(
            episode_file.get("relativePath") or episode_file
        )
        key = f"{source}:{canonical}:{skey}:{_ep_key(payload)}:{discriminator}"
        return [
            CanonicalEvent(
                source=source,
                source_event_key=key,
                type=canonical,
                media=media,
                attrs=_episode_attrs(payload),
            )
        ]

    if event_type == "EpisodeFileDelete":
        episode_file = payload.get("episodeFile") or {}
        discriminator = episode_file.get("id") or sha16(episode_file)
        return [
            CanonicalEvent(
                source=source,
                source_event_key=(
                    f"{source}:media.deleted:file:{skey}:{_ep_key(payload)}:{discriminator}"
                ),
                type="media.deleted",
                media=media,
                attrs={"scope": "file", "reason": payload.get("deleteReason")},
            )
        ]

    if event_type == "SeriesDelete":
        return [
            CanonicalEvent(
                source=source,
                source_event_key=f"{source}:media.deleted:series:{skey}",
                type="media.deleted",
                media=media,
                attrs={"scope": "series", "deleted_files": bool(payload.get("deletedFiles"))},
            )
        ]

    if event_type in ("Health", "HealthIssue", "HealthRestored"):
        resolved = event_type == "HealthRestored"
        check = payload.get("type") or "unknown"
        message = payload.get("message") or ""
        state = "restored" if resolved else "issue"
        return [
            CanonicalEvent(
                source=source,
                source_event_key=f"{source}:health.{state}:{check}:{sha16(message)}",
                type="health.issue",
                attrs={
                    "level": payload.get("level"),
                    "message": message,
                    "check": check,
                    "resolved": resolved,
                },
            )
        ]

    attrs = {"test": True} if event_type == "Test" else {}
    return [unknown_event(source, payload, event_type, **attrs)]
