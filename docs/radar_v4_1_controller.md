# Radar V4.1 — Research Controller + AI Policy

## Purpose

V4.0 stores what the system knows and does not know.

V4.1 decides:

> Which unknown should be researched next, and what is the cheapest valid way to reduce it?

V4.1 still executes **zero LLM calls**.

## Core policy

`Algorithm first → Cache second → Narrow AI fallback third → Deep AI last`

The controller never plans later-gate research while an earlier blocking gate is unresolved.

Example:

If `C02 problem_recurs` is unresolved, the system should not spend time researching:
- landing pages,
- final pricing,
- product architecture,
- customer-satisfaction build estimates.

Those questions have low decision value until Problem Reality is stronger.

## Research priority

The initial deterministic approximation is:

`Decision Impact × Reducibility × Answerability × Urgency × Coverage Gap / Soft Cost`

This is not a permanent scientific formula.
It is an explicit, inspectable baseline that can later be calibrated empirically.

## First method is always non-AI

Examples:

- C02 -> `local_problem_recurrence_search`
- C05 -> `market_buyer_signal_search`
- C06 -> `solution_complaint_search`
- C09 -> `company_profile_match`
- C12 -> `temporal_window_analysis`

An AI fallback may be attached to the plan, but it is **not authorized**.

Example:

`local_problem_recurrence_search`
may later fall back to
`same_problem_verify`

only if deterministic retrieval/rules end in `AMBIGUOUS / INSUFFICIENT / UNRESOLVED`.

## AI Task Registry

Only registered narrow tasks may ever be called.

The registry explicitly defines:
- purpose,
- allowed conditions,
- forbidden behavior,
- output fields,
- model tier,
- token ceiling.

There is no approved task named:
- `analyze_business_opportunity`
- `decide_if_we_should_build`
- `give_market_score`

Those jobs belong to the evidence and gate system, not the model.

## AI Budget

Per-case daily cycle caps are conservative:

- IGNORE: NT$0
- PARK: NT$0
- WATCH: NT$0.05
- INVESTIGATE: NT$0.30
- VALIDATE: NT$1.00
- BUILD: NT$1.00

Budget cap is not a spending target.

## V4.2 next

V4.2 should execute the first free research method:
`local_problem_recurrence_search`.

It will search existing HN/Reddit/StackOverflow/community data for direct recurring
problem evidence, use deterministic filters first, and only mark an item
`AMBIGUOUS` when a narrow `same_problem_verify` AI fallback may add real decision value.
