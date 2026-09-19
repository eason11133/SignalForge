# SignalForge Part 2 — Founder Memory

## Scope

Part 2 adds only the Founder Memory product layer:

- Founder Discussion Ledger
- Discussion Brief
- Since Last Discussion / Discussion Delta
- Decision / Rejected Direction / Reason preservation
- explicit discussion checkpoints

Part 1 remains included cumulatively:

- Probe
- Money Trail
- Decision Frontier
- Today

Deferred to later Parts:

- Part 3: Try to Kill / Evidence Replay / Search Coverage / Kill-Advance-Park product UX
- Part 4: Compare / Opportunity Battle / Ask SignalForge / ranking-change explanation
- Part 5: ChatGPT MCP/App integration

## Authority boundary

Founder Memory is a separate authority domain.

Every memory record is fixed as:

- `AUTHORITY = FOUNDER`
- `MARKET_AUTHORITY = NONE`
- `MARKET_TRUTH_IMPACT = NONE`

Founder Memory never writes:

- C01-C14
- RadarClaim
- Published evidence
- Market calibration
- real-market outcomes

A Founder hypothesis remains a Founder hypothesis until the existing market-truth pipeline independently validates evidence.

## Persistence

`.radar_runtime/signalforge_founder_reasoning.jsonl`

The ledger is logically append-only. Records are chained by SHA-256 predecessor hashes. Corruption/tampering is fail-visible and blocks new writes rather than silently appending over damaged history.

Decision and Rejected Direction entries require a reason.

## Discussion Brief

A Brief shows two separate blocks:

1. `MARKET TRUTH` — read-only current Published Brain claim states for a linked thesis.
2. `FOUNDER REASONING` — hypotheses, assumptions, questions, decisions, rejected directions, constraints and reasons.

If no Published thesis is linked, the Brief says so. It does not fill the market section with Founder belief.

## Discussion Delta

SignalForge never guesses what "last discussion" means.

The Founder explicitly creates a discussion checkpoint. The next Delta compares:

- Founder-memory entries appended after that checkpoint;
- current Published claim state against the read-only market snapshot captured at the checkpoint.

With no checkpoint, the system returns `NO_DISCUSSION_BASELINE` instead of inventing a delta.

## Product acceptance

Part 2 acceptance uses a real Founder-style task:

- record `Freeze DoneProof product development` + reason;
- reject `Generic AI code reviewer` + reason;
- record a hypothesis, constraint and question;
- generate a Brief;
- create an explicit discussion baseline;
- add a new question;
- detect only the new Founder memory plus a simulated Published claim change;
- tamper with the ledger and verify fail-visible / no further writes.

Engineering PASS remains different from Market Calibration. Part 2 does not increase market calibration.
