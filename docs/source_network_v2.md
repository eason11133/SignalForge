# Adaptive Multi-site Source Network v2

## Goal

Turn the fixed scraper list into an extensible Source Adapter Network.

The existing `problem_sources` collector remains responsible for:

- GitHub Issues
- Stack Overflow
- Reddit

V2 adds three independent adapter families:

1. **Stack Exchange Network**
   - Discovers network sites through `/sites`.
   - Seeds several technical sites as initial probes.
   - Other network sites remain discoverable in Source Registry.

2. **GitLab Issues**
   - With `GITLAB_TOKEN`: authenticated global issue search.
   - Without a token: public project discovery + public project issue search.

3. **Feed / Discourse Network**
   - Extracts outbound domains already appearing in problem evidence.
   - Probes public declared RSS/Atom feeds and a few standard feed paths.
   - Recognizes Discourse public feeds such as `latest.rss?order=created` and `posts.rss`.
   - Honors robots.txt and stops on rate limits.

## New normalized data table

`external_problem_items`

All new adapters normalize into one schema instead of adding a table per website.
This is the plug-in boundary for future adapters.

## New coverage table

`radar_source_coverage`

Tracks per Radar Case and source:

- attempts
- successful attempts
- zero-result attempts
- records seen
- direct-problem hits
- last status / error / query

This separates **"we searched and found nothing"** from **"we never searched"**.

## Evidence safety

Search is recall-oriented. Evidence promotion remains precision-oriented.

Only these V2 external source types enter C02 recurrence:

- `stackexchange`
- `gitlab_issue`
- `discourse_feed`

`generic_feed` is collected for discovery/context but is NOT accepted as direct
C02 recurrence evidence by default.

## AI

No LLM is used by the adapters, source activation, coverage tracking, or
recurrence integration.

## Optional credentials

```dotenv
SO_API_KEY=...
GITLAB_TOKEN=...
SOURCE_NETWORK_SEED_DOMAINS=community.example.com,forum.example.org
```

GitHub/Reddit credentials remain handled by `problem_sources`.
