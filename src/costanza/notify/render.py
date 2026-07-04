"""Pure renderers: canonical events / digest data -> RenderedMessage.

No I/O, no clock, no channel specifics — snapshot-tested. The Discord
adapter maps RenderedMessage onto embeds; other adapters may map it onto
plain text.
"""

from __future__ import annotations

from ..ids import sha16
from ..schemas import CanonicalEvent, RenderedMessage

# Muted, functional palette (Discord-style ints).
_COLORS = {
    "request.created": 0x3498DB,
    "request.approved": 0x2ECC71,
    "request.declined": 0xE74C3C,
    "request.available": 0x9B59B6,
    "media.grabbed": 0x95A5A6,
    "media.imported": 0x1ABC9C,
    "media.upgraded": 0x1ABC9C,
    "media.deleted": 0xE67E22,
    "playback.started": 0x95A5A6,
    "playback.stopped": 0x95A5A6,
    "watch.completed": 0xF1C40F,
    "health.issue": 0xE74C3C,
    "source.unknown": 0x7F8C8D,
    "reconcile.gap": 0x7F8C8D,
}

_TITLES = {
    "request.created": "New request",
    "request.approved": "Request approved",
    "request.declined": "Request declined",
    "request.available": "Now available",
    "media.grabbed": "Grabbed",
    "media.imported": "Added to library",
    "media.upgraded": "Quality upgraded",
    "media.deleted": "Removed from library",
    "playback.started": "Playback started",
    "playback.stopped": "Playback stopped",
    "watch.completed": "Watched",
    "health.issue": "Health issue",
    "source.unknown": "Unrecognized event",
    "reconcile.gap": "Reconcile gap",
}


def media_label(event: CanonicalEvent) -> str:
    media = event.media
    if media is None or not media.title:
        return "(no media)"
    label = media.title
    if media.year:
        label = f"{label} ({media.year})"
    detail = media.detail or {}
    season, episode = detail.get("season"), detail.get("episode")
    if season is not None and episode is not None:
        label = f"{label} S{season:02d}E{episode:02d}"
    elif season is not None:
        label = f"{label} Season {season}"
    return label


def rendered_hash(message: RenderedMessage) -> str:
    return sha16(message.model_dump(mode="json"))


def render_event(event: CanonicalEvent) -> RenderedMessage:
    title = f"{_TITLES.get(event.type, event.type)}: {media_label(event)}"
    fields: list[tuple[str, str]] = []
    description = ""

    who = event.user.display if event.user and event.user.display else None
    attrs = event.attrs

    match event.type:
        case "request.created" | "request.approved" | "request.declined":
            if who:
                description = f"Requested by {who}"
            if attrs.get("requested_seasons"):
                fields.append(("Seasons", str(attrs["requested_seasons"])))
            if attrs.get("auto_approved"):
                fields.append(("Approval", "automatic"))
        case "request.available":
            if attrs.get("partial"):
                title = f"Partially available: {media_label(event)}"
            if who:
                description = f"Requested by {who}"
        case "media.grabbed" | "media.imported" | "media.upgraded":
            if attrs.get("quality"):
                fields.append(("Quality", str(attrs["quality"])))
        case "media.deleted":
            if attrs.get("scope"):
                fields.append(("Scope", str(attrs["scope"])))
            if attrs.get("reason"):
                fields.append(("Reason", str(attrs["reason"])))
        case "watch.completed":
            if who:
                description = f"Watched by {who}"
        case "playback.started" | "playback.stopped":
            if who:
                description = who
            if attrs.get("player"):
                fields.append(("Player", str(attrs["player"])))
        case "health.issue":
            state = "restored" if attrs.get("resolved") else (attrs.get("level") or "issue")
            title = f"Health {state}: {event.source}"
            description = str(attrs.get("message") or "")
            if attrs.get("kind") == "request_failed":
                title = f"Request failed: {media_label(event)}"
        case "reconcile.gap":
            title = f"Reconcile gap: {event.source}"
            description = (
                f"Missed webhooks detected for {event.source}; transient events "
                "in this window may be lost"
            )
            if attrs.get("recovered"):
                fields.append(("Recovered events", str(attrs["recovered"])))
            if attrs.get("transient_kinds"):
                fields.append(("Not reconstructable", ", ".join(attrs["transient_kinds"])))
        case "source.unknown":
            title = f"Unrecognized {event.source} event"
            description = f"payload kind: {attrs.get('payload_kind')}"

    if event.origin == "reconcile" and event.type != "reconcile.gap":
        fields.append(("Origin", "reconcile (synthesized after the fact)"))

    return RenderedMessage(
        kind="embed",
        title=title,
        description=description,
        fields=fields,
        color=_COLORS.get(event.type),
        footer=f"source: {event.source}",
    )


def render_digest(data: dict) -> RenderedMessage:
    """Weekly household digest from a stats dict (see jobs/digest.py)."""
    fields: list[tuple[str, str]] = []

    arrivals = data.get("new_arrivals") or []
    if arrivals:
        lines = [f"- {a['label']}" for a in arrivals[:15]]
        if len(arrivals) > 15:
            lines.append(f"…and {len(arrivals) - 15} more")
        fields.append(("New arrivals", "\n".join(lines)))

    requests = data.get("requests") or {}
    if requests:
        fields.append(
            (
                "Requests",
                f"opened {requests.get('opened', 0)} / available "
                f"{requests.get('available', 0)} / declined {requests.get('declined', 0)}",
            )
        )
        stale = requests.get("stale") or []
        if stale:
            fields.append(
                ("Still waiting", "\n".join(f"- {s}" for s in stale[:10]))
            )

    watches = data.get("watches") or {}
    top = watches.get("top") or []
    if top:
        fields.append(
            ("Most watched", "\n".join(f"- {t['label']} ({t['count']})" for t in top[:10]))
        )
    per_user = watches.get("per_user") or []
    if per_user:
        fields.append(
            ("Watch counts", "\n".join(f"- {u['display']}: {u['count']}" for u in per_user))
        )

    ops = data.get("ops") or {}
    ops_lines = []
    if ops.get("gaps"):
        ops_lines.append(f"reconcile gaps: {ops['gaps']}")
    if ops.get("dead_notifications"):
        ops_lines.append(f"dead notifications: {ops['dead_notifications']}")
    if ops.get("dead_outbox"):
        ops_lines.append(f"dead ingest items: {ops['dead_outbox']}")
    if ops.get("unknown_events"):
        ops_lines.append(f"unrecognized events: {ops['unknown_events']}")
    unmapped = ops.get("unmapped_identities") or []
    if unmapped:
        ops_lines.append("unmapped identities: " + ", ".join(unmapped[:10]))
    if ops_lines:
        fields.append(("Ops", "\n".join(ops_lines)))

    if not fields:
        description = "A quiet week: nothing new arrived and nothing was watched."
    else:
        description = ""

    return RenderedMessage(
        kind="digest",
        title=f"Weekly media digest — {data.get('period_start', '?')} to "
        f"{data.get('period_end', '?')}",
        description=description,
        fields=fields,
        color=0x34495E,
        footer="costanza weekly digest",
    )
