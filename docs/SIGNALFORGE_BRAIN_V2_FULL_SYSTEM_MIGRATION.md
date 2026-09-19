# SignalForge Brain v2 — Full-System Migration Map

| Existing concept | Action | New ownership / meaning |
|---|---|---|
| Observation / EvidenceSpan | KEEP | Canonical evidence foundation |
| Append-only evidence history | KEEP | Longitudinal truth foundation |
| Validated evidence boundary | KEEP | Only validated Radar evidence can become atomic truth |
| ProblemCandidate | MODIFY | Early hypothesis/input container, not opportunity identity |
| Recurrence | MOVE | ProblemLineage property |
| Community grouping | MODIFY | Same-problem atom/lineage clustering with independence controls |
| C01 problem evidence | KEEP / INTERPRET | Phenomenon truth, still Radar-owned |
| C05 buyer | KEEP | Market truth, still Radar-owned |
| C06 current solution | KEEP | Market truth, still Radar-owned |
| C07 unresolved gap | KEEP | Market truth, still Radar-owned |
| C11 economics/WTP evidence | KEEP | Market truth, still Radar-owned |
| Flat C01–C14 presentation | MODIFY | Atomic states stay; Brain maps them into structural dimensions without rewriting them |
| RadarCase | KEEP / NARROW | Production research/validation disposition, not structural opportunity identity |
| Solo score | DOWNGRADE | Compatibility/context only; zero verdict/ranking authority |
| `gate_existing_decision()` structural heuristic | RETIRE FROM AUTHORITY | Brain v2 owns structural opportunity synthesis |
| WATCH / INVESTIGATE / VALIDATE | KEEP / NARROW | Production research/validation disposition, not phenomenon lifecycle |
| Research More / research orchestrator | KEEP / MODIFY | Production evidence acquisition; Brain VOI is advisory only |
| FrameGraph | KEEP SHADOW | Discovery projection only, zero Production authority |
| R0–R4 / Sentinel | KEEP SHADOW | Discovery/semantic quality support |
| Latest/newest-first opportunity concept | REMOVE | Freshness is metadata/update context only |
| Flat Candidate Queue as opportunity model | RETIRE CONCEPTUALLY | Problem/Transition lineages → thesis portfolio |
| ProblemLineage | ADD | Persistent same-problem memory |
| TransitionLineage | ADD | Persistent structural-change memory with explicit-subject conflict boundaries |
| ExistingSystem | ADD | H1 workflow/value/asset baseline |
| Workaround ladder W0–W6 | ADD | Revealed-behavior strength, not WTP proof |
| StructuralIntersection | ADD | Pair-scoped Problem × transition × mismatch eligibility; one direct source stays PARTIAL |
| Asset accessibility / incumbent response | ADD | Capture/commercialization structure |
| OpportunityThesis | ADD | Persistent structural opportunity identity |
| Thesis death states | ADD | Explicit falsification/termination |
| Meaningful Change | ADD | Semantic delta, not recency feed |
| ResearchQuestion | ADD | Decision-critical VOI planning with attempt feedback |

## Authority cutover in this release

`processors/opportunity_decision.py` keeps the old solo-transition assessment only as compatibility context. It can no longer override Radar verdict, next gate, `why_now`, or ordering. Structural opportunity authority is explicitly assigned to the Brain v2 derived portfolio.

No UX is changed in this release. The Founder UX migration is a later subsystem after Brain truth/structure is stable.

## G2 migration note

R2 never completed installation on the target machine and rolled back. G2 therefore migrates
from the same pre-Brain production source contract. No R2 Brain state should be trusted as an
installed authority. If stale experimental Brain runtime files exist from a failed attempt, the
installer backup/rollback contract treats them as upgrade-owned derived state only; Production DB
truth and UX remain untouched.

## G3 migration additions

| G3 concept | Action | Authority / meaning |
|---|---|---|
| Transition context | KEEP / NARROW | Verified context remains non-persistent unless explicit/direct or independently corroborated |
| TransitionHypothesis | ADD | Staging corroboration; may promote only persistent transition identity |
| StructuralBridgeHypothesis | ADD | Research target only; never StructuralIntersection truth |
| Pre-thesis ResearchQuestion | ADD | VOI can acquire missing bridge/transition evidence before a thesis exists |
| OpportunityThesis lifecycle | MODIFY | Stable identity with semantic revisions, death and revival history |
| Zip2 adjudication | MODIFY | Explicit Gate + Vector; no average-score authority |
| Brain no-op fingerprint | MODIFY | Requires truth + derivation engine + schema match |
| G2 Brain schema | MIGRATE COMPATIBLY | Brain-only g2 metadata upgrades to g3 on first G3 derived rebuild |

### G2 -> G3 upgrade boundary

G2 is the currently installed live-accepted production integration baseline. G3 does not repeat the
Production authority cutover. It replaces the Brain derived subsystem while verifying that the four
existing integration markers remain present and unchanged. Production Radar source ownership, DB
schema and UX are not migrated.

The installer backs up the Brain event database, projection database and published Brain JSON
surfaces before the live G3 migration. Failure at any later acceptance stage restores those derived
state bytes together with the replaced Brain code.
