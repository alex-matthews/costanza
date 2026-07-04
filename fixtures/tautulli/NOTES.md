# Tautulli fixture provenance + expected webhook template

Tautulli's webhook agent posts a **user-defined** JSON template. Configure
Tautulli's webhook notification agent with this body template (one agent,
triggers: Playback Start, Playback Stop, Watched):

```json
{
  "event": "{action}",
  "media_type": "{media_type}",
  "title": "{title}",
  "show_name": "{show_name}",
  "episode_name": "{episode_name}",
  "season_num": "{season_num}",
  "episode_num": "{episode_num}",
  "year": "{year}",
  "tmdbId": "{themoviedb_id}",
  "tvdbId": "{thetvdb_id}",
  "rating_key": "{rating_key}",
  "session_key": "{session_key}",
  "plex_username": "{username}",
  "user_id": "{user_id}",
  "player": "{player}",
  "video_resolution": "{video_resolution}",
  "progress_percent": "{progress_percent}"
}
```

`{action}` renders as playback_start / playback_stop / watched. Anything
else (e.g. recently_added) normalizes to `source.unknown` and is kept.

| fixture | provenance |
| --- | --- |
| recently-added-movie.json | seeded from old Costanza repo recordings (redacted) |
| playback-start-movie.json | synthetic: true — built from the template above |
| playback-stop-early.json | synthetic: true |
| playback-stop-derived-watch.json | synthetic: true |
| watched-episode.json | synthetic: true |
| watched-movie.json | synthetic: true |
