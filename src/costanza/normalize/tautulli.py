"""Tautulli webhook payloads -> canonical events.

Tautulli's webhook agent posts a user-defined JSON template; the template
Costanza expects is documented in fixtures/tautulli/NOTES.md (event,
media_type, rating_key, session_key, plex_username, user_id,
progress_percent, ...).

Watch-completion rule (OQ-3): consume the `watched` trigger when the
routing config says it is configured; otherwise derive watch.completed
from playback_stop at progress >= threshold. Both paths share one
source_event_key shape (user + rating_key), so if the household enables
the watched trigger later, duplicates collapse instead of double-counting.
"""

from __future__ import annotations

from ..config import WatchCompletionConfig
from ..ids import sha16
from ..schemas import CanonicalEvent, MediaRef, UserRef
from .common import to_int, unknown_event


def _media(payload: dict) -> MediaRef | None:
    media_type = payload.get("media_type")
    tmdb = to_int(payload.get("tmdbId") or payload.get("tmdb_id"))
    tvdb = to_int(payload.get("tvdbId") or payload.get("tvdb_id"))
    if media_type == "episode":
        detail = {
            "season": to_int(payload.get("season_num")),
            "episode": to_int(payload.get("episode_num")),
        }
        return MediaRef(
            tmdb_id=tmdb,
            tvdb_id=tvdb,
            title=payload.get("show_name") or payload.get("title"),
            year=to_int(payload.get("year")),
            kind="episode",
            detail=detail,
        )
    if media_type == "movie":
        return MediaRef(
            tmdb_id=tmdb,
            tvdb_id=tvdb,
            title=payload.get("title"),
            year=to_int(payload.get("year")),
            kind="movie",
        )
    return None


def _user(payload: dict) -> UserRef | None:
    tautulli_id = payload.get("user_id")
    plex_name = payload.get("plex_username") or payload.get("username")
    if tautulli_id is not None and str(tautulli_id) != "":
        return UserRef(
            provider="tautulli",
            external_id=str(tautulli_id),
            display=str(plex_name) if plex_name else None,
        )
    if plex_name:
        return UserRef(provider="plex", external_id=str(plex_name), display=str(plex_name))
    return None


def _user_key(payload: dict) -> str:
    return str(payload.get("user_id") or payload.get("plex_username") or "unknown")


def _watch_key(source: str, payload: dict) -> str:
    rating_key = payload.get("rating_key") or sha16(payload)
    return f"{source}:watch.completed:{_user_key(payload)}:{rating_key}"


def _base_attrs(payload: dict) -> dict:
    attrs: dict = {}
    if payload.get("player"):
        attrs["player"] = payload["player"]
    if payload.get("episode_name"):
        attrs["episode_title"] = payload["episode_name"]
    if payload.get("video_resolution"):
        attrs["video_resolution"] = payload["video_resolution"]
    return attrs


def normalize_tautulli(
    source: str, payload: dict, watch: WatchCompletionConfig
) -> list[CanonicalEvent]:
    event = payload.get("event")
    media = _media(payload)
    user = _user(payload)
    rating_key = payload.get("rating_key") or sha16(payload)
    session_key = payload.get("session_key") or "nosession"

    if event == "playback_start":
        return [
            CanonicalEvent(
                source=source,
                source_event_key=(
                    f"{source}:playback.started:{_user_key(payload)}:{session_key}:{rating_key}"
                ),
                type="playback.started",
                media=media,
                user=user,
                attrs=_base_attrs(payload),
            )
        ]

    if event == "playback_stop":
        progress = to_int(payload.get("progress_percent"))
        attrs = _base_attrs(payload)
        if progress is not None:
            attrs["progress_percent"] = progress
        events = [
            CanonicalEvent(
                source=source,
                source_event_key=(
                    f"{source}:playback.stopped:{_user_key(payload)}:{session_key}:{rating_key}"
                ),
                type="playback.stopped",
                media=media,
                user=user,
                attrs=attrs,
            )
        ]
        if (
            not watch.tautulli_watched_trigger
            and progress is not None
            and progress >= watch.progress_threshold
        ):
            events.append(
                CanonicalEvent(
                    source=source,
                    source_event_key=_watch_key(source, payload),
                    type="watch.completed",
                    media=media,
                    user=user,
                    attrs={
                        **_base_attrs(payload),
                        "derived_from": "playback.stopped",
                        "progress_percent": progress,
                    },
                )
            )
        return events

    if event == "watched":
        return [
            CanonicalEvent(
                source=source,
                source_event_key=_watch_key(source, payload),
                type="watch.completed",
                media=media,
                user=user,
                attrs=_base_attrs(payload),
            )
        ]

    return [unknown_event(source, payload, event)]
