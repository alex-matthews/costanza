# Sonarr fixture provenance

All fixtures here are `synthetic: true` — built from the official Sonarr
webhook connection schema (Grab / Download / EpisodeFileDelete /
SeriesDelete / Health / Test). The old repo's Sonarr samples used a
non-Sonarr shape (`EpisodeImported`) and were not carried over. Replace
with real captures during rollout step 1 (shadow ingest).
