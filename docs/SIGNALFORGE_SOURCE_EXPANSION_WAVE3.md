# SignalForge Source Expansion Wave 3

Release target: `signalforge-source-expansion-wave3-cumulative-r1-20260906`

## Scope

Wave 3 deepens already-supported observation surfaces. It does not add a new decision model, Market Truth authority, scoring system, UI phase, autonomous crawler, or commercial prediction layer.

The goal is to capture deeper public conversation units without allowing child comments/replies, mirrors, or source fan-out to inflate market recurrence.

## Added depth

### Hacker News

- Search result story remains the parent observation.
- Matched stories can expand through the public Algolia item endpoint.
- Child comments are emitted as `COMMENT` traces.
- Story and descendants share one `independence_group_key`.
- Child-depth failures are fail-visible as partial depth coverage and do not convert a successful parent search into a false transport failure.
- Expansion is globally bounded per source run.

### Stack Exchange / Stack Overflow

A matched question can expand to:

- `QUESTION`
- `ANSWER`
- question `COMMENT`
- answer `COMMENT`

All observations belonging to the same question thread share one independence group. Child-depth request failure is treated as partial depth coverage rather than as absence or parent-search failure.

### GitHub Issues

Matched public issues can expand to public issue comments. Issue plus comments share one thread independence group. Comment reads are bounded.

### GitHub Discussions

A new read-only GraphQL adapter supports explicitly configured public repositories.

Required configuration:

```text
GITHUB_TOKEN=...
SIGNALFORGE_GITHUB_DISCUSSION_REPOS=owner/repo,owner2/repo2
```

The adapter emits:

- `DISCUSSION`
- `DISCUSSION_COMMENT`
- `DISCUSSION_REPLY`

It does not discover arbitrary repositories, perform GraphQL mutations, reuse browser sessions, or infer private repository access. Runtime readiness requires both a server-side token and an explicit repository allowlist.

### YouTube reply completion

`commentThreads.list` does not necessarily contain all replies. Wave 3 therefore completes missing reply depth through `comments.list(parentId=...)` when the inline reply set is incomplete.

Boundaries:

```text
SIGNALFORGE_YOUTUBE_MAX_REPLY_READS_PER_VIDEO=60
SIGNALFORGE_YOUTUBE_MAX_REPLY_PAGES_PER_THREAD=2
```

The implementation also enforces hard upper bounds and deduplicates replies already present inline.

## Relevance boundary

Depth does not grant semantic relevance.

Every child observation still follows:

```text
search hit / child content
→ thesis relevance
→ problem-role classification
→ trace counters
```

`IRRELEVANT` or insufficiently compatible child observations can remain inspectable but cannot increment substantive problem, firsthand-pain, workaround, existing-solution, paid-signal, spend, or paid-dissatisfaction counters.

## Recurrence and independence boundary

Wave 3 introduces explicit thread-level `independence_group_key` metadata.

Examples:

```text
HN story + all comments
→ one HN story independence group

Stack question + answers + comments
→ one Stack question independence group

GitHub issue + issue comments
→ one GitHub issue independence group

GitHub discussion + comments + replies
→ one GitHub discussion independence group

YouTube top-level comment + replies
→ one YouTube comment-thread independence group
```

Cross-source exact textual mirrors are deduplicated when safe to do so. Near-duplicate clusters remain explicitly unvalidated.

Every source-expansion trace retains:

```text
recurrence_authority = NONE_UNTIL_EXPLICIT_SOURCE_INDEPENDENCE_VALIDATION
```

Clusters retain:

```text
UNVALIDATED_DO_NOT_COUNT_AS_MARKET_RECURRENCE
```

Therefore more comments, replies, URLs, mirrors, or adapters do not by themselves become independent market recurrence.

## Truth authority

Wave 3 performs zero direct Market Truth writes.

Source observations remain:

```text
UNVALIDATED_SEARCH_TRACE
```

Wave 3 cannot directly write or promote C01–C14, WTP, Published Thesis truth, buyer truth, paid dissatisfaction, recurrence, or calibration.

## Security boundary

Wave 3 continues to prohibit:

- browser cookies or browser-profile reuse
- Founder passwords
- school/VPN credentials
- CAPTCHA or anti-bot bypass
- arbitrary logged-in scraping
- public exposure of API credentials

GitHub Discussions credentials remain server-side only. The adapter is read-only and does not expose the token in trace metadata or API output.

## Acceptance

Pre-package engineering acceptance:

- Source Expansion Wave 3: 30/30 PASS
- Source Expansion Wave 2: 24/24 PASS
- Source Expansion Wave 1: 27/27 PASS
- Live Intelligence Semantic Closure: 16/16 PASS
- Source-Fit / Playbook Closure: 28/28 PASS
- Live Founder Workflow Closure: 33/33 PASS
- Founder UX Phase 1 Contract: 7/7 PASS
- Founder UX Phase 1: 45/45 PASS
- Part 1: 28/28 PASS
- Money Trail: 27/27 PASS
- Part 3: 37/37 PASS
- Part 4 Founder Closure: 22/22 PASS
- Part 4 regression: PASS
- Part 5 ChatGPT Integration: 36/36 PASS
- Part 5 multiprocess durability: 11/11 PASS
- Part 6 semantic closure: 12/12 PASS
- Part 6 regression: 40/40 PASS
- Part 6 multiprocess durability: 10/10 PASS
- Python compile: PASS

Live upstream HTTP acceptance is a separate state. In the packaging environment it remained `LIVE_ACCEPTANCE_PENDING` because external DNS/transport was unavailable. A network/rate-limit condition must not be reported as PASS; a genuine request-contract rejection such as HTTP 400/422 remains a hard failure when live acceptance can execute.
