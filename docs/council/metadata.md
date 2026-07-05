# TMDB metadata client + cache

Proposal cards need what the event stream cannot provide: poster, runtime,
overview, trailer link, genres. That is a new read-only external
dependency ([ADR-0010](../adr/0010-tmdb-metadata-dependency.md)) — the
first one added since the substrate froze its integration surface, so it
gets the same discipline as the existing clients.

## Client

- `clients/tmdb.py`, built on the existing sanitized `ReadOnlyClient`
  base: GET-only (grep-enforced like every other client), sanitized
  errors (TMDB v3 auth passes the key as a query param — exactly the
  Tautulli leak shape, so the sanitized exception path is mandatory, or
  v4 header auth is used and the risk disappears; prefer v4).
- Endpoints (v1 needs only these):
  - `GET /3/search/multi` — the `/propose` command's title search;
  - `GET /3/movie/{id}` and `GET /3/tv/{id}` (with
    `append_to_response=videos` for the trailer key);
  - image *URLs* assembled from the static config base — Costanza never
    proxies or stores image bytes; Discord fetches poster URLs itself.
- Config: `TMDB_API_KEY` via the existing ExternalSecret contract;
  absent key = metadata features degrade (below), never a crash.

## Cache

```
tmdb_cache(kind ENUM(movie, tv, search),
           key TEXT,               -- tmdb id or normalized query
           payload_json,
           fetched_at,
           UNIQUE(kind, key))
```

- Same SQLite store, ordinary migration; pruned by the existing daily
  prune job (details TTL ~7 days; search results ~1 day).
- Cache-first always: a proposal card renders from
  `proposals.tmdb_snapshot_json` (frozen at proposal time), so cards
  never change under the household's feet and TMDB outages cannot touch
  existing cards.

## Rate limits and failure modes

- TMDB's public ceiling (~50 req/s) is orders of magnitude above
  household scale; a conservative client-side limiter (a few req/s,
  reusing the notify limiter pattern) plus cache-first makes the
  practical rate near zero.
- TMDB down or key missing: `/propose` still works — the card degrades
  to title/year text with a "metadata pending" note, and a repair sweep
  backfills snapshots when TMDB returns. Metadata is garnish; the council
  loop never blocks on it.
- No TMDB data enters the canonical event schema; it lives only in
  council snapshots and the cache. Third-party text (overviews) is data,
  never instructions — the ADR-0005 injection posture applies wherever
  snapshots later meet an LLM prompt.
