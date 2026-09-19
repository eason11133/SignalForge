# SignalForge Part 6 — Market Execution & Learning — Semantic Closure

## Product job

Part 6 closes the Founder opportunity loop after Part 4 has allowed a market action:

`Decision → Founder Actionability Gate → Market Test → Pre-registration → Buyer Action → Structured Observations → Outcome → Explicit Evidence Promotion → Domain-scoped Calibration → Future Ranking`

It is not a GTM-plan generator, it does not create a second Market Truth system, and it cannot bypass the Part 4 Founder Actionability gate.

## Authority boundary

Part 6 directly writes **zero** C01–C14 claims. Existing atomic Market Truth authority remains:

1. Part 4 exposes a current Founder Action and execution authority;
2. a bounded market test is designed only for an allowed Founder Action;
3. a claim-specific validation experiment is registered before the outcome and bound to the exact Market Action;
4. the market outcome is computed from frozen action-semantic rules and durable observations;
5. the Founder explicitly chooses an eligible Evidence Promotion;
6. promotion delegates to the existing `signalforge_validation_workflow` / `market_ground_truth` quality lock.

A completed Market Action is durable execution history and may become calibration input, but it is not automatically atomic Market Truth.

## 6.1 Market Test Designer and Founder Actionability

Part 6 consumes the **current Part 4 closure projection**, not the stale Brain `best_next_action` as execution authority.

Examples:

- `ACTION_NOW` can authorize a bounded market action.
- `VALIDATE_DISTRIBUTION` / `INVESTIGATE` can authorize only the corresponding Founder-discovery action.
- `PARK`, `PARK_OR_PARTNER`, `WATCH`, or other non-executable Founder states cannot be converted into a paid pilot merely because the old Brain action said `MARKET_ACTION`.

The test design exposes:

- HYPOTHESIS
- TARGET
- TEST
- SUCCESS
- FAILURE
- INCONCLUSIVE
- MAX SAMPLE
- MAX COST
- EXECUTION AUTHORITY

A numeric cost ceiling is never invented. If the Founder does not set one, it remains `NOT_SET`.

## 6.2 Pre-registration semantics

Pre-registration freezes:

- action type;
- action-semantic metric family;
- threshold;
- sample target;
- success/failure/inconclusive rules;
- buyer/outreach pack;
- max cost if supplied;
- decision-time learning features.

Thresholds and sample bounds may be Founder-edited before registration, but the semantic target cannot be changed arbitrarily. For example, a paid-pilot / preorder test must be evaluated on `paid_commitments`; it cannot be redefined as `likes`, generic replies, or compliments.

Only claim-specific validations with an actually prepared executable validation plan are offered for pre-registration. The existence of a claim row alone is insufficient.

## 6.3 Buyer / Outreach Pack

The pack exposes:

- WHO
- WHERE
- WHAT TO ASK
- WHAT NOT TO SAY
- WHAT EVIDENCE TO CAPTURE

It explicitly refuses to treat compliments, likes, stated interest, or “sounds useful” as willingness-to-pay evidence.

## 6.4 Outcome Capture and observation quality

Outcome Capture uses durable per-observation records. Sample size is derived from those records rather than trusted as a typed aggregate.

Each observation ties an actor to an evidence reference. Aggregate counters cannot exceed the durable observation base.

For paid behavior, a clean paid PASS requires, at minimum:

- positive `paid_commitments`;
- payment / paid-pilot semantic behavior;
- amount and currency when required by the registered action;
- durable observation/evidence records.

If MAX COST was preregistered, actual cost and currency are captured and compared with it. Missing required cost evidence, currency mismatch, or a cost breach forces the result out of a clean PASS path and makes it ineligible for calibration as a successful bounded test.

`PASS`, `FAIL`, or `INCONCLUSIVE` is derived from the frozen rule. The Founder does not retrospectively select the result.

## 6.5 Evidence Promotion

Evidence Promotion is a separate explicit Founder action after outcome capture.

An option is eligible only when:

- the Market Action has a binary completed outcome;
- the claim experiment is still `PENDING`;
- it is bound to the exact same `market_action_id`;
- it was created before the action completed;
- its candidate/thesis scope matches the action;
- its claim-specific observed-behavior requirement is satisfied.

Claim semantics are not interchangeable. In particular:

- acquisition evidence can support the registered acquisition claim;
- paid commitment can support the registered WTP claim;
- **switching requires observed switch behavior**; a paid pilot with zero switches cannot promote a switching claim.

`market_ground_truth` is additionally fail-closed so a `PAID_PILOT` event cannot fan out into unrelated registered claims.

## 6.6 Calibration validity

Calibration is scoped by both:

- **validation domain** (for example `FAST_VALIDATION` vs `FOUNDER_ADDRESSABILITY`);
- **action semantic family** (for example paid commitment vs qualified response).

Founder-discovery outcomes are not allowed to become market-success ranking evidence. A channel being easy for the Founder to reach is a Founder-addressability learning signal, not proof that the opportunity is more likely to succeed.

Repeated actions on the same thesis are not independent market samples. Calibration first aggregates to an independent thesis/entity unit; conflicting repeated outcomes are excluded rather than counted as multiple votes.

A feature bucket can become a transparent market-ranking tie-breaker only when each side has enough independent entities and the 95% Wilson intervals genuinely separate. Otherwise the adjustment remains `UNVALIDATED` / non-actionable.

The current policy requires at least four independent entities in the bucket **and** four in the complement. Action semantics are never mixed into one generic PASS/FAIL success target.

`general_predictive_accuracy` remains `UNVALIDATED` until real prospective outcomes justify a separate accuracy claim.

## Durability acceptance

The multiprocess acceptance directly verifies:

- 30 concurrent Market Action registrations → 30 durable rows;
- 24 concurrent distinct validation completions → 24 durable completions;
- 12 concurrent completions of one validation experiment → exactly one winner;
- 12 concurrent completions of one Market Action → exactly one winner.

## Independent semantic closure acceptance

The independent Part 6 closure additionally verifies:

- Part 4 PARK cannot be bypassed by Part 6;
- a paid test cannot be redefined as likes;
- zero paid commitments cannot be a paid calibration-eligible PASS;
- typed sample size cannot exceed durable observations;
- MAX COST breach is enforced;
- only executable claim plans are exposed;
- paid pilot does not imply switching;
- repeated tests on one thesis do not create false independence;
- Founder Discovery cannot alter market ranking;
- different action semantics are calibrated separately;
- Market Truth promotion remains claim-specific.

## Acceptance status vs market status

Engineering / Founder semantic acceptance can PASS without proving a business opportunity.

Part 6 completion does **not** imply:

- market demand is validated;
- willingness to pay exists;
- SignalForge ranking accuracy is known;
- Market Calibration is validated.

Until real eligible market outcomes accumulate, Market Calibration remains `UNVALIDATED` and market-ranking adjustments remain inactive.
