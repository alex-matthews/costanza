# Radarr fixture provenance

All fixtures here are `synthetic: true` — built from the official Radarr
webhook connection schema (Grab / Download / MovieFileDelete / MovieDelete /
HealthIssue / HealthRestored / Test / MovieAdded). The old repo's Radarr
samples used a non-Radarr shape (`MovieImported`) and were not carried over.
Replace these with real captures during rollout step 1 (shadow ingest).
