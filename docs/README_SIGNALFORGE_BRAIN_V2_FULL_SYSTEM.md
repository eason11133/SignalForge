# SignalForge Brain v2 — Full-System Longitudinal Intelligence Upgrade

This is the Brain-first large subsystem upgrade. It intentionally does not modify dashboard/UX files or Production DB schema.

### Adds
- Problem/Transition atoms and persistent lineages
- Existing System and pair-scoped Structural Intersection objects
- scoped C05–C14 coverage so commercial truth cannot leak across adjacent candidates
- explicit transition-subject identity guards against broad transition overmerge
- evidence-backed Opportunity Thesis + death states
- 12-dimensional Gate+Vector structural adjudication
- Zip2-class structural classification
- append-only event ledger and replayable projection
- dirty-set/dependency incremental recompute
- meaningful semantic change tracking
- decision-critical research VOI with attempt feedback
- separate non-blocking Brain runtime
- read-only Brain API
- retrospective time-slice benchmark readiness contract

### Authority cutover
- Radar validated ledger remains sole atomic C01–C14 truth owner.
- Legacy solo-transition heuristics become compatibility context only.
- Brain v2 owns structural opportunity synthesis.
- Shadow U23–U28 / FrameGraph remains zero-authority.

### Operational behavior
Production cycle PASS is committed before the Brain child refresh is launched. A Brain failure is derived-layer failure only and cannot roll back a successful Production cycle.

### Not changed
- UX/dashboard
- C01–C14 thresholds
- Production DB schema
- real market calibration status

### Installer R2 acceptance orchestration
Static/adversarial/scale acceptance and live derived-plane acceptance are separate planes. A live install check uses `run_signalforge_brain_v2_acceptance.py --live-only`; it does not repeat the synthetic/scale suite that just passed.


## G2 persistence/projection closure

The structural admission model is unchanged. This closure removes SQLite read amplification from first-build persistence and portfolio materialization:

- event append batches idempotency lookups and stream-sequence heads instead of issuing per-event SELECTs;
- active projection snapshot is read once per portfolio materialization instead of recursively reopening the state DB;
- refresh diagnostics expose structural build, event diff, event append, projection apply, projection snapshot, and surface timing;
- the original 15-second large-scale end-to-end acceptance remains in force; the regression is not hidden by widening the timeout.

These changes do not alter Radar C01-C14 truth ownership, transition admission semantics, Zip2 gating, Shadow authority, or Market Calibration.

## G3 — Structural Recall, Thesis Evolution & Zip2 Adjudication

G3 is the next intelligence-quality generation on top of the installed G2 structural/persistence
closure. It does not widen G2 admission back toward R2 behavior.

It adds:

- `TransitionHypothesis` for independent corroboration of verified context before persistent authority;
- sparse-anchor protection against cross-problem generic-context overmerge;
- `StructuralBridgeHypothesis` as a research-only path when a promising transition/problem pair lacks
  direct bridge evidence;
- pre-thesis Research VOI, so zero current intersections does not mean zero learning path;
- longitudinal thesis semantic revisions, death and revival;
- explicit Zip2 Gate + Vector reporting with no weighted-average authority;
- derivation-engine/schema-aware no-op logic for safe G2 -> G3 migration;
- read-only hypothesis inspection endpoints.

Radar remains the sole C01-C14 owner, Shadow remains zero-authority, UX and Production DB schema are
unchanged, and Market Calibration remains 0 / UNVALIDATED until external outcomes exist.
