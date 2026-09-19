# SignalForge Source Expansion Wave 4

## Scope

Wave 4 expands the Internet Observation Layer without adding decision/ranking/business-logic scope.

### New durable/public observation surfaces

- `LEMMY_PUBLIC` — explicit public Lemmy instances, `/api/v4/search` plus bounded comment depth.
- `STACK_EXCHANGE_NETWORK` — explicit Stack Exchange `api_site_parameter` allowlist, question/answer/comment depth.
- `ASHBY_PUBLIC_JOBS` — explicit public Ashby job boards, including compensation metadata when the board exposes it.
- `MASTODON_SEARCH` — explicit public Mastodon instances using hashtag timelines plus bounded status context.

## Absence adequacy contract

A source can discover positive evidence without being strong enough to support a zero-result market-absence conclusion.

Each registry source now exposes:

- `discovery_scope`
- `absence_adequacy`

`MASTODON_SEARCH` is deliberately `HASHTAG_TIMELINE_ONLY / PARTIAL` because hashtag timelines are not general full-text market coverage. A positive trace can still pass the normal thesis relevance gate, but a zero result cannot by itself satisfy source fit for `PARK`.

The Founder source-adequacy projection therefore separates:

- `observed_source_families`
- `absence_adequate_source_families`
- `limited_absence_sources`

Only full absence-adequacy families are allowed to make `SOURCE_FIT_SUFFICIENT` for a zero-trace stop decision.

## Security boundary

- public/official read paths only
- explicitly configured instances/sites/boards
- no browser cookies
- no password/VPN credential reuse
- no browser profile/session reuse
- no CAPTCHA/anti-bot bypass
- generic public-instance URLs remain SSRF-guarded
- no Market Ground Truth writer imports

## Truth boundary

Every new observation remains `UNVALIDATED_SEARCH_TRACE`.

Source routing, discovery scope and absence adequacy are routing/observation metadata only and cannot write C01-C14, market recurrence or Market Truth.

## Acceptance

Wave 4 deterministic acceptance covers:

1. registry/runtime contracts for all four sources;
2. Mastodon hashtag + thread context and partial absence adequacy;
3. Lemmy public search + comments;
4. configurable Stack Exchange network Q/A/comments;
5. Ashby public jobs + compensation metadata;
6. positive-trace relevance after partial discovery;
7. zero-result source-fit exclusion for partial sources;
8. dynamic configured source-family routing;
9. cross-source exact mirror dedupe and recurrence fail-closed;
10. security and truth-authority boundaries.
