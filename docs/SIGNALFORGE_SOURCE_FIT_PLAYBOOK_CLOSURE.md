# SignalForge Live Closure — Source Fit + Playbook Gate

## Scope

This is a narrow Founder-live closure. It adds no Part, no React business logic, no crawler, no new scoring model and no new Market Truth authority.

It fixes only:

1. source-set adequacy / Source-Fit routing,
2. Founder-hypothesis PARK semantics,
3. Founder Playbook prerequisite gating.

## Source adequacy contract

The Founder probe now separates three facts:

- `TRANSPORT_COMPLETE`
- `SOURCE_SET_COMPLETE`
- `SOURCE_FIT_SUFFICIENT`

A transport-successful developer-heavy source set is not automatically adequate for every buyer/problem class.

Initial source profiles:

- `DEVELOPER_TOOLING`
- `AGENCY_SERVICES`
- `ECOMMERCE_OPERATOR`
- fail-closed domain-specific / unclassified fallback

`AGENCY_SERVICES` may recommend source families such as agency service pages, reviews, founder communities, consulting job posts, product discovery / strategy pages and research-tool reviews even when those adapters are not yet live.

Source profiles are routing metadata only. They create zero C01-C14 / Market Truth writes.

## Founder-hypothesis disposition

`PARK` is allowed only when:

- transport is complete,
- configured source set is complete,
- source fit is sufficient for the buyer/problem class,
- bounded probe returns zero substantive traces for the relevant stop condition.

If the source set is complete but source fit is insufficient:

- disposition = `WAIT_FOR_SOURCE_FIT`
- next mode = `SOURCE_FIT_RESEARCH`
- zero traces cannot be interpreted as market absence
- no pricing / MVP / unrelated Published-truth research is allowed from that zero result.

## Source-profile query grammar

The source registry keeps profile-specific query grammar. `AGENCY_SERVICES` includes opportunity / market validation, product discovery / strategy, consulting-engagement, pricing and paid-dissatisfaction vocabulary. Any fresh results remain `UNVALIDATED_SEARCH_TRACE`.

No new external source adapter is claimed live by this closure.

## Founder Playbook prerequisite gate

A template existing is never enough to emit an execution object.

Founder Playbook states:

- `READY`
- `BLOCKED`
- `NOT_APPLICABLE`

Minimum prerequisites before `READY`:

- evidence-backed buyer segment is not UNKNOWN,
- buyer reachability is not UNKNOWN,
- disposition is not PARK and not `WAIT_FOR_SOURCE_FIT`,
- Decision Frontier exists,
- Source-Fit is sufficient for the active problem class.

If buyer or reachability is UNKNOWN, output is fail-closed: `target_count = null`, empty channels/questions and no opening/payment message.

A parked Founder hypothesis has `NOT_APPLICABLE` until explicitly reopened.

## Truth boundary

- Fresh source-fit research = `UNVALIDATED_SEARCH_TRACE` only.
- Source profile / source-fit state = routing metadata only.
- Founder Playbook = execution guidance only.
- No source-fit rule creates buyer identity, WTP, recurrence or C01-C14 truth.
- No source-fit rule mutates a Published thesis disposition.
