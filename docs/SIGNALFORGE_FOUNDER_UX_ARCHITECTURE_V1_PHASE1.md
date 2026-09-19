# SignalForge Founder UX Architecture v1 — Phase 1

## Purpose

Phase 1 creates the canonical backend product projection that the future Founder UI will render. It does **not** redesign React pages yet and does not add a Part 7 or new commercial decision engine.

Founder-facing product identity is now centered on `Opportunity`, not Part 1–6 capabilities.

## Canonical Founder mental model

Every `FounderOpportunityView` exposes the same six control fields:

- `current_call`
- `why`
- `decision_frontier`
- `next_action`
- `stop_condition`
- `owner`

Founder labels are natural Chinese. Internal enums and API/schema field names remain English.

## Stable identities

Phase 1 adds deterministic stable identities for:

- Opportunity
- Founder Hypothesis
- Published Thesis
- Problem Lineage
- Evidence
- Founder Memory Entry
- Decision Artifact
- Market Test
- Market Action
- Outcome
- Calibration Unit
- Future Eason One Work Contract

Stable identity is derived from canonical IDs only. Title fuzzy matching, UI text, DOM state, or current sidebar state are not identity authorities.

## Owner model

Canonical owner enum:

- `SIGNALFORGE`
- `FOUNDER`
- `CHATGPT`
- `EASON_ONE`
- `MARKET_WAIT`

ChatGPT and Eason One are only contract/reservation surfaces in this phase. No new full live runtime is claimed.

## Founder View Models

Phase 1 defines:

- `FounderTodayView`
- `FounderOpportunityListView`
- `FounderOpportunityView`
- `FounderEvidenceInspectorView`
- `FounderCompareView`
- `FounderMarketTestView`
- `FounderOutcomeView`
- `FounderLearningView`
- `FounderDiscussionContext`
- `FounderHandoffPreview`

React must render these canonical semantics. It must not independently decide market track, Founder actionability, buyer identity, Money Trail classification, lineage binding, Decision Frontier, next action, stop condition, promotion eligibility, calibration eligibility, or outcome semantics.

## Lineage review contract

Lineage is first-class and fail-closed:

- `NO_MATCH`
- `POSSIBLE_MATCH_REVIEW`
- `CANONICAL_MATCH`

`POSSIBLE_MATCH_REVIEW` always means `NO_TRUTH_INHERITANCE`. Founder can later confirm same lineage, keep separate, or compare evidence, but Phase 1 does not invent a second lineage writer.

A Founder hypothesis with no safe Published match keeps buyer, existing spend, paid dissatisfaction, and reachability `UNKNOWN` even if unrelated Published evidence exists elsewhere in SignalForge.

## Truth boundary

Founder View Models are read-only product projections.

- Market Truth writes: `0`
- C01–C14 writes: `0`
- Calibration writes: `0`
- Lineage writes: `0`
- Founder/synthetic recurrence authority: unchanged

## Phase boundary

This package intentionally does not implement the new App Shell or React Today / Opportunities pages. The next implementation phase should only begin after Phase 1 identity, ViewModel, owner, and lineage contracts are accepted.
