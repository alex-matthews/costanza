# ADR-0010: TMDB as a read-only metadata dependency

**Status:** accepted

## Context

Proposal cards are the Lobby's face: poster, runtime, overview, trailer,
genres — facts the event stream cannot provide and should not (the
canonical schema records what *happened*, not what things *are*). The
substrate deliberately avoided metadata dependencies; the council cannot:
a card that is just a title string does not start conversations. Seerr
proxies TMDB, but coupling card rendering to Seerr's availability and API
shape would put a second system in the hot path for something that is
fundamentally third-party data.

## Decision

Add **TMDB** as a first-class, read-only metadata dependency
([council/metadata.md](../council/metadata.md)):

- `clients/tmdb.py` on the sanitized GET-only client base (same
  constraint scan, same error hygiene; v4 header auth preferred so the
  key never rides the URL).
- SQLite-backed cache with TTLs, pruned by the existing job; proposal
  cards render from a **snapshot frozen at proposal time**, so cards are
  stable and TMDB outages cannot touch existing cards.
- Image URLs only — Costanza never proxies or stores image bytes; Discord
  fetches posters itself.
- Degradation is mandatory: no key / TMDB down → text-only cards with
  backfill later. The council loop never blocks on metadata.
- Scope includes (v1.x) the **upcoming/discover calendar** as the Premiere
  Lobby's candidate source and `vote_count`/`vote_average` as the default
  review-maturity signal for deferred proposals — same client, cache,
  limits, and read-only constraint; richer review sources are a separate
  decision (OQ-15), never a silent addition.
- TMDB text is third-party data, never instructions: the ADR-0005
  injection posture applies wherever snapshots later meet an LLM prompt.

## Consequences

- A new external secret (`TMDB_API_KEY`) and a new egress dependency —
  the first non-cluster call the service makes. Household-scale volume
  plus cache-first keeps it beneath every rate limit that matters.
- One more table and prune target; trivial.
- Attribution: TMDB's terms require a visible "data from TMDB" credit —
  it goes in the card footer.

## Alternatives rejected

- **Via Seerr's TMDB proxy:** couples the Lobby to Seerr uptime and an
  API surface Seerr does not stabilize for consumers; also breaks the
  "sources are webhook-in only" cleanliness for no gain.
- **No metadata (text cards):** was the substrate's answer; product-fatal
  for the Lobby. A poster is half the conversation.
- **Scrape Plex artwork:** Plex direct integration is a standing non-goal
  (system-boundaries.md); artwork exists only for already-acquired media,
  and proposals are mostly about media not yet acquired.
