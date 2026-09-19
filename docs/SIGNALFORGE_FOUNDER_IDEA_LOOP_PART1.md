# SignalForge Part 1 — Founder Idea Loop

## Product task

A Founder can type a fresh idea such as `AI 常忘記規則` and get, in one surface:

1. a bounded fresh market reality probe with **0 paid AI API calls**;
2. explicit source coverage / failure visibility;
3. Published Money Trail evidence kept separate from new search traces;
4. exactly one decision-changing question;
5. a Today action with advance / kill conditions.

## Fresh probe sources

The Part 1 fast probe uses bounded public API/search surfaces:

- Hacker News Algolia Search API
- Stack Exchange API (Stack Overflow advanced search)
- GitHub issue search
- GitHub repository search

The query fan-out is bounded. `GITHUB_TOKEN` is optional; if absent, public unauthenticated GitHub limits apply. Source failure and rate limiting are returned to the Founder instead of being converted into a false `not found` claim.

## Truth boundary

Fresh results are always tagged:

`UNVALIDATED_SEARCH_TRACE`

They are **not** Radar Evidence, Published Evidence, C01–C14, buyer truth, WTP truth, or market calibration. They may change what SignalForge recommends researching next, but they do not write Market Truth.

The existing Money Trail remains a derived projection over existing Published / validated evidence. Missing evidence remains UNKNOWN. No numeric spend estimate is invented.

## Decision Frontier

Part 1 produces one `decision_frontier.question`, plus:

- `next_mode`
- `today_action`
- `advance_if`
- `kill_if`
- `do_not_research`

If configured search coverage fails, the frontier is about restoring coverage. SignalForge explicitly refuses to infer that no pain / buyer / competitor exists from a failed search.

## Scope deliberately deferred

Not in Part 1:

- Founder Discussion Ledger / Brief / Delta (Part 2)
- Try to Kill / Evidence Replay product UX (Part 3)
- Opportunity Battle / Ask SignalForge (Part 4)
- ChatGPT MCP / App integration (Part 5)

## Acceptance

`run_signalforge_founder_idea_loop_part1_acceptance.py` uses the real Founder-task shape `AI 常忘記規則`, deterministic external-source fixtures, source-failure fixtures, truth-boundary checks, Decision Frontier checks, and Founder UI checks.

Engineering tests are evidence. The product task is the acceptance target.
