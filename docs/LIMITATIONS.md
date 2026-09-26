# Limitations

SignalForge is research infrastructure, not a market prediction system.

## Coverage

- Public search cannot cover private communities, closed groups, paid databases or unindexed pages.
- Login walls, rate limits, robots policy, geography and API changes create source gaps.
- Search ranking and indexing change over time.

## Relevance

- Relevance classification can produce false positives and false negatives.
- Related material is useful context but cannot automatically become core evidence.
- Semantic similarity does not prove the same underlying problem.

## Deduplication

- URL normalization cannot identify every mirror, repost, screenshot or rewritten copy.
- Over-aggressive dedup can also collapse genuinely independent evidence.

## Actor continuity

- Actor matching only uses public evidence.
- Similar usernames are not sufficient for confident identity merge.
- SignalForge does not resolve private identities.

## Behavior tracking

- Repeated workflow does not prove demand.
- Repeated workaround does not prove willingness to pay.
- Product mentions do not prove preference or brand weakness.
- Window deltas are descriptive, not causal.

## Validation

- relevance != validation
- discussion volume != willingness to pay
- GitHub activity != commercial demand
- product existence != market size
- counterevidence must remain visible

## Failure semantics

- `SEARCH FAILED != NO MARKET SIGNAL`
- `0 results != no demand`
- `source blocked != no evidence exists`

Failure is saved as coverage / transport metadata.

## Local data

The repository excludes runtime research state, private data, credentials, caches and backups.

The development workspace may contain persistent local research data under `.radar_runtime/`, but those files are intentionally excluded from GitHub.

## Legacy code

SignalForge evolved through many experimental generations.

The repository still contains historical audit / regression scripts and some legacy infrastructure. Current product work is centered on:

- `api/`
- `processors/`
- `dashboard/`

PostgreSQL / Redis remain available for legacy paths but are not required for the current local Research Workspace.
