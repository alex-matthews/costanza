"""Radarr webhook payloads -> canonical events.

Keys prefer the payload's downloadId: the grab and its import share it, the
/history API records it too, so webhook-vs-reconcile duplicates collapse.
"""

from __future__ import annotations

from ..config import WatchCompletionConfig
from ..ids import sha16
from ..schemas import CanonicalEvent, MediaRef
from .common import to_int, unknown_event


def _media(payload: dict) -> MediaRef | None:
    movie = payload.get("movie") or {}
    if not movie:
        return None
    return MediaRef(
        tmdb_id=to_int(movie.get("tmdbId")),
        imdb_id=movie.get("imdbId") or None,
        title=movie.get("title"),
        year=to_int(movie.get("year")),
        kind="movie",
    )


def _media_key(payload: dict) -> str:
    movie = payload.get("movie") or {}
    return str(to_int(movie.get("tmdbId")) or movie.get("id") or sha16(movie))


def _quality_attrs(payload: dict) -> dict:
    attrs: dict = {}
    release = payload.get("release") or {}
    movie_file = payload.get("movieFile") or {}
    quality = movie_file.get("quality") or release.get("quality")
    if quality:
        attrs["quality"] = quality
    size = movie_file.get("size") or release.get("size")
    if size:
        attrs["size"] = size
    if release.get("indexer"):
        attrs["indexer"] = release["indexer"]
    if group := (movie_file.get("releaseGroup") or release.get("releaseGroup")):
        attrs["release_group"] = group
    return attrs


def normalize_radarr(
    source: str, payload: dict, watch: WatchCompletionConfig
) -> list[CanonicalEvent]:
    event_type = payload.get("eventType")
    media = _media(payload)
    mkey = _media_key(payload)

    if event_type == "Grab":
        download_id = payload.get("downloadId") or sha16(payload.get("release") or payload)
        return [
            CanonicalEvent(
                source=source,
                source_event_key=f"{source}:media.grabbed:{mkey}:{download_id}",
                type="media.grabbed",
                media=media,
                attrs=_quality_attrs(payload),
            )
        ]

    if event_type == "Download":
        upgrade = bool(payload.get("isUpgrade"))
        canonical = "media.upgraded" if upgrade else "media.imported"
        movie_file = payload.get("movieFile") or {}
        discriminator = payload.get("downloadId") or sha16(
            movie_file.get("relativePath") or movie_file
        )
        return [
            CanonicalEvent(
                source=source,
                source_event_key=f"{source}:{canonical}:{mkey}:{discriminator}",
                type=canonical,
                media=media,
                attrs=_quality_attrs(payload),
            )
        ]

    if event_type == "MovieFileDelete":
        movie_file = payload.get("movieFile") or {}
        discriminator = movie_file.get("id") or sha16(movie_file)
        return [
            CanonicalEvent(
                source=source,
                source_event_key=f"{source}:media.deleted:file:{mkey}:{discriminator}",
                type="media.deleted",
                media=media,
                attrs={"scope": "file", "reason": payload.get("deleteReason")},
            )
        ]

    if event_type == "MovieDelete":
        return [
            CanonicalEvent(
                source=source,
                source_event_key=f"{source}:media.deleted:movie:{mkey}",
                type="media.deleted",
                media=media,
                attrs={"scope": "movie", "deleted_files": bool(payload.get("deletedFiles"))},
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
