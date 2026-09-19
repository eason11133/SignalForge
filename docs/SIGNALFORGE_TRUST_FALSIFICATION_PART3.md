# SignalForge Part 3 — Trust / Falsification

## Product task

Founder should be able to inspect an active Money Trail and answer four questions without trusting a mystery score:

1. **Try to Kill It** — what evidence would make this direction wrong?
2. **Evidence Replay** — why does SignalForge currently believe each Published claim?
3. **Search Coverage / Failure Visibility** — which falsification searches succeeded, failed, or were rate-limited?
4. **Kill / Advance / Park** — which disposition is currently triggered by Published truth, and what conditions govern each branch?

## Hard truth boundary

Fresh falsification results are **UNVALIDATED_COUNTEREVIDENCE_CANDIDATE** only.

They never:

- mutate C01–C14,
- publish evidence,
- change a Radar claim,
- trigger KILL / ADVANCE / PARK by themselves,
- increase Market Calibration.

Disposition is derived from **Published truth only**.

## Try to Kill

The bounded zero-AI search deliberately targets three counter-hypothesis families:

- current solution already good enough / native support,
- no budget / low value / rare problem,
- switching / trust burden / failed market attempts.

Returned traces are deduplicated and then screened for deterministic counterevidence cues. A matching trace is still only a candidate for validation.

If all configured searches fail, the result is `SEARCH_FAILED_NO_MARKET_CONCLUSION`.

If successful searches return no candidate, the result means only:

> No counterevidence was found in the successful configured searches.

It does **not** mean no counterevidence exists.

## Evidence Replay

Evidence Replay reads validated Published ledger links only. For each claim it surfaces:

- Published state,
- supporting links,
- contradicting links,
- insufficient links,
- independent source-family count,
- source title / URL / excerpt / provenance fields.

It explicitly labels its coverage as `LEDGER_REPLAY_ONLY`; replaying the ledger is not proof that the source universe was exhaustively searched.

## Disposition

- **ADVANCE** — Published pain + buyer + unresolved gap are supported/partial, existing spend is STRONG/PARTIAL, and Revenue Wedge reaches TRY_NOW.
- **KILL** — a critical Published claim (pain, buyer, gap, buildability) is REFUTED, or Revenue Wedge is KILL.
- **PARK** — meaningful Published research exists, but no spend / paid dissatisfaction / buyer / gap basis emerges; generic deeper research is not the default.
- **CONTINUE** — none of the above is currently triggered.

Fresh falsification traces may point to the next thing to validate, but cannot directly change the disposition.

## Scope

Part 3 does not add:

- a new sidebar module,
- a new market-truth dimension,
- a new scoring engine,
- an LLM dependency,
- a new Market Action or Outcome system.

It uses the existing Money Trail surface and existing Published evidence architecture.

## Market calibration

`0 / UNVALIDATED` remains legal and unchanged until real market outcomes exist.
