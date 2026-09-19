
# Direct Problem Source Expansion v1

The old source lists are now **seeds**, not the permanent source universe.

The new `problem_sources` scraper uses unresolved Radar C02 cases to discover:

- new GitHub repositories through public Issues;
- new Stack Overflow tags through advanced question search;
- new Reddit subreddits through candidate-driven search.

## API behavior

GitHub automatically uses existing `GITHUB_TOKEN` when available. Without it,
the query batch is intentionally much smaller.

Stack Exchange automatically uses existing `SO_API_KEY` when available and
requests `filter=withbody`, so question bodies are now persisted in
`SOQuestion.raw_metadata.body`.

Reddit uses the Data API only when approved OAuth credentials exist:
`REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USER_AGENT`.
Otherwise it uses a small public RSS discovery batch. On HTTP 429 it stops
Reddit work for that run; it does not attempt to bypass the service limit.

## New tables

`github_issues`
Stores direct issue text.

`source_registry`
Stores seed/discovered sources, ACTIVE/WATCH status, evidence role, yield,
last success and last error.

`source_checkpoints`
Stores rotating candidate cursors so repeated runs continue from where the last
run stopped instead of hammering every external service.

## Source activation

Seed sources start ACTIVE.

Discovered sources start WATCH and become ACTIVE after yielding at least two
direct-problem hits.

This first version deliberately does not auto-reject low-yield sources. We want
more history before introducing irreversible pruning rules.

## Cost

No LLM calls are made by this scraper.
