# Radar Product Contract v2 — Attention + Reality First

## North Star

Every daily session should answer:

> What deserves the founder's attention now, why, what is still unknown, and what should happen next?

The product is not rewarded for producing many opportunities.
It is rewarded for safely eliminating bad or premature opportunities.

## Hard rules

1. **LLM may interpret evidence, but must not substitute for missing evidence.**
2. Market activity is not the same as direct problem corroboration.
3. Missing competitors are not proof of a supply gap.
4. A working demo is not proof of customer satisfaction.
5. Founder enthusiasm must not increase Market Evidence.
6. Long build time requires evidence that the opportunity window is longer than the build-to-satisfaction time.
7. A real problem can still be a bad opportunity for the current company.
8. Unknown must remain UNKNOWN. Do not fill UI with invented certainty.
9. Default to calibrated abstention rather than optimistic recommendation.
10. Preserve failed algorithms, false positives, and rejected candidates as research evidence.

## Founder-facing information hierarchy

### Home

Show at most three attention items first.

Each item answers only:
- What is the problem?
- Why is it still on the radar?
- What is the biggest uncertainty / danger?
- What should be investigated next?

Do not lead with:
- raw database counts
- model confidence bars
- retrieval counts
- verifier percentages
- source badges
- fingerprint fields
- raw evidence excerpts

Those are audit/debug information.

### Candidate detail

First screen:
1. current judgement
2. why it remains
3. biggest unknown
4. next step

Second layer:
- Solution Landscape
- unresolved gap
- Company Reality
- Build Reality
- Distribution Reality
- Race / Opportunity Window
- Pre-mortem
- Kill Criteria

Technical evidence is collapsed by default.

## Future Opportunity Triage pipeline

DISCOVER
→ VERIFY PROBLEM
→ SOLUTION LANDSCAPE
→ UNRESOLVED GAP
→ COMPANY REALITY
→ BUILD REALITY
→ DISTRIBUTION REALITY
→ COMPETITIVE FUTURE
→ RACE / DURABILITY
→ PRE-MORTEM
→ KILL CRITERIA
→ ATTENTION RANKING
→ DECIDE

Possible decision states:
- IGNORE
- PARK
- WATCH
- INVESTIGATE
- VALIDATE
- BUILD

Filtering is not deletion. PARK/WATCH items can reopen when feasibility, technology, demand, or competition changes.

## Company Reality

The system must use a persistent capability profile instead of asking an LLM to improvise founder/company skill for every opportunity.

Capability classes:
- CAN_DO
- CAN_ACQUIRE
- HARD_BLOCKER
- UNKNOWN

A high-value market with a HARD_BLOCKER may still be `NOT NOW`.

## Build Reality

Estimate separately:
- prototype time/cost
- validation MVP time/cost
- customer-usable V1 time/cost
- customer-satisfying product time/cost

The last one matters most for race analysis.

All estimates need evidence and confidence.
If evidence is missing, show UNKNOWN.

## Race / Opportunity Window

Compare:
- time to customer satisfaction
- likely unresolved opportunity window

Investigate:
- platform-native feature risk
- incumbent response
- startup / open-source competition velocity
- technical progress that may erase the pain
- evolution into a new adjacent pain

If likely build-to-satisfaction time is longer than the remaining opportunity window, strongly downgrade or reject.

## Pre-mortem

Before recommending VALIDATE/BUILD, ask:
- Why does this fail?
- Why do users not pay?
- Why do they refuse to switch?
- Why does an incumbent win?
- Why does the problem disappear?
- Why is customer acquisition uneconomic?
- What hidden operational burden appears?

Look for evidence for each failure mode.

## Kill criteria

Define stop conditions before large investment.

Examples:
- cannot find repeated direct problem evidence
- target users will not take interviews
- existing solutions satisfy the job well enough
- no credible distribution path
- customer-satisfying scope exceeds acceptable cost/window
- platform or incumbent likely resolves the gap first

"Never give up" is not a valid product rule.

## Action layer — later

Once an opportunity passes the relevant gates, the system may generate an execution packet for:
- discuss with AI
- validate
- design product
- create landing page
- build MVP

Do not unlock BUILD just because an idea sounds interesting.
