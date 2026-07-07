"""Seerr (Overseerr-family) webhook JSON payload -> canonical events.

Payload shape: notification_type, subject, message, media{media_type,
tmdbId, tvdbId, status}, request{request_id, requestedBy_username, ...},
extra[]. Request lifecycle keys are derived from the Seerr request id, so
the reconcile job (which reads the same ids from the request list API)
collapses onto identical source_event_keys.
"""

from __future__ import annotations

from ..config import WatchCompletionConfig
from ..schemas import CanonicalEvent, MediaRef, UserRef
from .common import split_title_year, to_int, unknown_event

_REQUEST_TYPES = {
    "MEDIA_PENDING": "request.created",
    "MEDIA_APPROVED": "request.approved",
    "MEDIA_AUTO_APPROVED": "request.approved",
    "MEDIA_DECLINED": "request.declined",
    "MEDIA_AVAILABLE": "request.available",
}


def _media(payload: dict) -> MediaRef | None:
    media = payload.get("media") or {}
    title, year = split_title_year(payload.get("subject"))
    tmdb = to_int(media.get("tmdbId"))
    tvdb = to_int(media.get("tvdbId"))
    if not (tmdb or tvdb or title):
        return None
    kind = "series" if media.get("media_type") == "tv" else "movie"
    return MediaRef(tmdb_id=tmdb, tvdb_id=tvdb, title=title, year=year, kind=kind)


def _user(payload: dict) -> UserRef | None:
    request = payload.get("request") or {}
    username = request.get("requestedBy_username")
    if not username:
        return None
    return UserRef(provider="seerr", external_id=str(username), display=str(username))


def _seasons(payload: dict) -> str | None:
    for item in payload.get("extra") or []:
        if item.get("name") == "Requested Seasons":
            return str(item.get("value"))
    return None


def normalize_seerr(
    source: str, payload: dict, watch: WatchCompletionConfig
) -> list[CanonicalEvent]:
    notification_type = payload.get("notification_type")
    request_id = (payload.get("request") or {}).get("request_id")

    if notification_type in _REQUEST_TYPES and request_id is not None:
        event_type = _REQUEST_TYPES[notification_type]
        media = payload.get("media") or {}
        attrs: dict = {"request_id": str(request_id)}
        if seasons := _seasons(payload):
            attrs["requested_seasons"] = seasons
        if notification_type == "MEDIA_AUTO_APPROVED":
            attrs["auto_approved"] = True
        key = f"{source}:{event_type}:{request_id}"
        if event_type == "request.available":
            status = media.get("status") or "AVAILABLE"
            attrs["partial"] = status == "PARTIALLY_AVAILABLE"
            key = f"{key}:{status}"
        return [
            CanonicalEvent(
                source=source,
                source_event_key=key,
                type=event_type,
                media=_media(payload),
                user=_user(payload),
                attrs=attrs,
            )
        ]

    if notification_type == "MEDIA_FAILED" and request_id is not None:
        return [
            CanonicalEvent(
                source=source,
                source_event_key=f"{source}:health.issue:request:{request_id}",
                type="health.issue",
                media=_media(payload),
                user=_user(payload),
                attrs={
                    "kind": "request_failed",
                    "request_id": str(request_id),
                    "message": payload.get("message"),
                },
            )
        ]

    attrs = {"test": True} if notification_type == "TEST_NOTIFICATION" else {}
    return [unknown_event(source, payload, notification_type, **attrs)]
