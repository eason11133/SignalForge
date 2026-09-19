# SignalForge Source Expansion Wave 1

## Scope

This release expands the Internet Observation Layer without changing Market Truth authority, Opportunity scoring, WTP logic, or React business semantics.

Pipeline:

Founder hypothesis -> Source Registry -> source-fit plan -> bounded adapters -> content-unit traces -> thesis relevance -> problem-role classification -> trace counters.

All adapter output remains `UNVALIDATED_SEARCH_TRACE` until the existing evidence / validation authority promotes evidence through its normal gates.

## Source Registry contract

Each source has a canonical registry entry describing access mode, authentication, commercial status, supported content units, observation families, search/comment/reply/history support, and runtime configuration state.

The runtime registry never returns credential values. It only reports whether required credentials/configuration are present.

Access classes include official/public APIs, public feeds, and restricted sources. Restricted sources are registry-visible but are not automatically selected.

## Wave 1 adapters

### Brave Web Search

- Server-side API key: `BRAVE_SEARCH_API_KEY`
- Content unit: `WEB_PAGE`
- Used as broad web discovery, not as universal observation coverage.
- Dynamic observation families depend on the Founder hypothesis. For example, an agency hypothesis can map broad-web results to agency service pages/research-tool review surfaces, but Brave alone does not satisfy the buyer-voice dimension.

### GDELT DOC

- Enable explicitly: `SIGNALFORGE_GDELT_ENABLED=1`
- Content unit: `NEWS_ARTICLE_INDEX`
- Observation family: news / industry / company news.
- Treated as indexed news metadata/traces, not buyer voice.

### YouTube Data API

- Server-side API key: `YOUTUBE_API_KEY`
- Content units: `VIDEO`, `TOP_LEVEL_COMMENT`, `COMMENT_REPLY`
- Video discovery expands into comment threads and replies within bounded limits.

### Threads API

- Server-side access token: `THREADS_ACCESS_TOKEN`
- Content units: `POST`, `REPLY`
- Keyword search expands into replies within bounded limits.

### Greenhouse public jobs

- Configure board tokens: `SIGNALFORGE_GREENHOUSE_BOARDS=board_a,board_b`
- Content unit: `JOB_POST`
- Public job-board GET data is query-filtered into hiring/workflow observations.

### Lever public jobs

- Configure site names: `SIGNALFORGE_LEVER_SITES=site_a,site_b`
- Content unit: `JOB_POST`
- Public postings are query-filtered into hiring/workflow observations.

### RSS / Atom

Simple form:

`SIGNALFORGE_PUBLIC_FEEDS=https://example.com/feed.xml,https://example.org/rss`

Preferred form with explicit observation-family identity:

```json
SIGNALFORGE_PUBLIC_FEEDS_JSON=[
  {
    "url": "https://example.com/feed.xml",
    "observation_families": ["AGENCY_COMMUNITIES", "FOUNDER_COMMUNITIES"]
  }
]
```

RSS/Atom fetching is SSRF-hardened: no embedded credentials, localhost, private/link-local/non-global IP targets, or unsafe redirect chains. Fetches use bounded timeouts and response-size limits.

## Restricted registry entries

Wave 1 keeps Product Hunt, Reddit, and TikTok Research visible in the Source Registry but not auto-selected. Their current commercial/access constraints require a separate product/legal decision before enabling them in a commercial SignalForge workflow.

## Source-fit adequacy

`SOURCE_FIT_SUFFICIENT` depends on actual configured/executed observation families, not on a platform name or broad source profile.

Example for `AGENCY_SERVICES`:

- Buyer-voice dimension: founder/agency communities or agency reviews.
- Commercial-workflow dimension: agency service pages, consulting job posts, product-discovery/strategy pages, or research-tool reviews.

Therefore:

- Brave only -> `SOURCE_FIT_INSUFFICIENT` (buyer voice missing).
- Brave + a valid buyer-voice source such as Threads/YouTube/community feed -> can become `SOURCE_FIT_SUFFICIENT` if all other bounded coverage conditions are met.

A successful broad-web transport call does not, by itself, authorize a market-absence conclusion.

## Security boundary

Wave 1 does not use or request:

- personal browser cookies
- passwords
- browser session reuse
- school/company VPN credentials
- local browser profiles
- CAPTCHA bypass
- anti-bot bypass
- arbitrary authenticated-browser scraping

Secrets are expected only in server-side environment/secret storage. No registry/API response returns secret material.

## Live acceptance boundary

The adapters have deterministic contract tests with bounded mocked network responses. That proves request construction, parsing, content-unit handling, routing, truth boundaries, and safety guards in engineering acceptance.

It does **not** prove that the user's live API credentials, account permissions, quotas, or external services are currently usable. Live source status remains per-source `PENDING_CREDENTIAL`, `PENDING_CONFIGURATION`, `READY`, `RESTRICTED`, or transport-specific live state until exercised in the user's environment.

## Diagnostic Source Probe API security

`POST /sources/probe` can consume paid upstream API quota. It is therefore disabled unless the server has `SIGNALFORGE_SOURCE_PROBE_TOKEN` configured, and callers must provide that exact value in the `X-SignalForge-Source-Token` header. The endpoint never accepts or returns upstream Brave/YouTube/Threads credentials.

`GET /sources/registry` remains read-only and returns runtime states / credential-presence booleans only, never secret values.
