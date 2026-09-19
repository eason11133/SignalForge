# SignalForge Source Expansion Wave 2

## Scope

Wave 2 continues the Internet Observation Layer. It does not add Market Truth authority, Decision scoring, Founder UX Phase 2, or autonomous crawling.

## New adapters

### Bluesky public search

- `BLUESKY_PUBLIC_SEARCH`
- Uses public `app.bsky.feed.searchPosts` reads and bounded `getPostThread` reply expansion.
- No user browser session or user token is required for this adapter.
- Content units: `POST`, `REPLY`.

### X Recent Search

- `X_RECENT_SEARCH`
- Requires `X_BEARER_TOKEN` server-side.
- Uses recent-search only in Wave 2.
- Hard pre-request cost/result budget:
  - `SIGNALFORGE_X_MAX_POST_READS_PER_PROBE` (default 20, clamped 10..100)
  - `SIGNALFORGE_X_POST_READ_UNIT_USD` (default 0.005; pricing assumption, configurable)
  - `SIGNALFORGE_X_MAX_USD_PER_PROBE` (default 0.10)
- Conversation fan-out is deliberately disabled in Wave 2 so one Founder probe cannot create an unbounded paid-read tree.
- Content units: `POST`, `REPLY` when replies appear in the bounded search result.

### Configured public Discourse forums

- `DISCOURSE_PUBLIC`
- Configure only public sites you have intentionally selected:

```text
SIGNALFORGE_DISCOURSE_SITES=https://forum.example.com,https://community.example.org
```

or:

```json
[
  {
    "base_url": "https://forum.example.com",
    "observation_families": ["AGENCY_COMMUNITIES"]
  }
]
```

in `SIGNALFORGE_DISCOURSE_SITES_JSON`.

- Uses the same public-host/SSRF safety boundary as generic feeds.
- Bounded search + bounded topic expansion exposes topic/reply content units.
- No browser login/session reuse.

## Registry-only sources in Wave 2

### Google Places reviews

Visible in the Source Registry but `RESTRICTED` for the current durable evidence path. Google Places content has storage/caching and attribution requirements that do not match SignalForge's durable trace ledger yet. A future ephemeral, attribution-compliant path can unlock it without changing the evidence authority model.

### Yelp reviews

Visible but `RESTRICTED` pending plan/license review. The reviews endpoint is plan-gated and limited, so it is not treated as durable coverage automatically.

### Mastodon search

Registry-visible but no automatic adapter in Wave 2. Full-text status search availability varies by instance/search backend/auth; SignalForge must not interpret a configured Mastodon host as adequate observation coverage merely because the platform has an API.

## Cross-source dedupe / clustering

Wave 2 canonicalizes URLs (removing common tracking parameters), fingerprints content, removes obvious mirrors, and groups near-duplicate traces.

Clusters are explicitly non-authoritative:

```text
independence_status = UNVALIDATED_DO_NOT_COUNT_AS_MARKET_RECURRENCE
```

A Brave result, RSS copy, and social repost of the same underlying content cannot become three independent market observations merely because they came through three adapters.

## Truth boundary

All Wave 2 output remains:

```text
UNVALIDATED_SEARCH_TRACE
```

and must still pass the existing thesis-relevance / problem-role gate before counters.

Source profiles, runtime configuration, cost metadata, dedupe, and clusters write zero C01-C14 Market Truth and create no market recurrence.
