# SignalForge Brain v2 — Full-System Acceptance Contract

## Static / adversarial

The package must prove:

- same-problem true positives merge;
- same-technology adjacent pains do not merge;
- specific-target conflict blocks a false merge;
- transition driver conflict blocks a false lineage;
- conflicting explicit transition subjects block generic-vocabulary overmerge;
- commercial truth from candidate A cannot leak into a thesis structurally scoped only to candidate B;
- one direct problem↔transition pair source remains PARTIAL, while multi-source direct pair proof is required for SUPPORTED mismatch;
- derived transition context cannot spawn a TransitionLineage;
- W0–W6 does not promote generic hiring or price complaints to strong workaround behavior;
- context-only intersections cannot become structural theses;
- explicit unresolved-gap refutation creates a thesis death state;
- Zip2 candidate requires structural mismatch;
- Zip2 high-conviction cannot self-certify missing dimensions;
- recency has no research or portfolio priority authority;
- Candidate ID churn preserves ProblemLineage identity;
- research attempts lower repeated VOI and remain idempotent;
- append-only UPDATE/DELETE is blocked;
- projection replay is deterministic;
- retired objects/dependencies disappear from projection;
- Production gate source groups remain ahead of Brain advisory;
- Brain cannot invent a source adapter;
- Brain API is read-only and lazily imported;
- legacy solo heuristic has zero Production decision/ranking authority;
- Brain runtime is derived/non-blocking.

## Scale

Synthetic tests exercise hundreds to thousands of candidates and derived transition contexts. Performance is validated structurally: indexing, dirty-set recompute, dependency propagation, and evidence indexing are used instead of global repeated corpus scans.

## Live install acceptance

Before Production files are patched, the installer runs Brain v2 against the real local Production database using SELECT-only truth loading and fingerprints atomic Production truth before/after. It must pass:

- Production truth guard unchanged;
- first Brain refresh bounded;
- identical second refresh fast/no-op;
- no second identical object events;
- transition authority bounded to eligible evidence;
- atomic claim truth owned by Radar;
- Shadow authority zero;
- freshness priority authority false;
- predictive accuracy remains UNVALIDATED unless a real calibration dataset exists.

## Post-cutover acceptance

After patching four Production source files, AST/source acceptance proves:

- read-only Brain router mounted once;
- Production PASS is saved before non-blocking Brain launch;
- no inline Brain refresh blocks Production;
- Research Orchestrator integrates advisory without surrendering blocking-gate priority;
- legacy `gate_existing_decision` and solo-score ranking authority are removed;
- all patched Python parses/compiles;
- import smoke succeeds.

The installer does not automatically run a full Production research cycle. Therefore live Production cutover behavior is exercised on the next normal/manual Production cycle, while the installer itself verifies live Brain truth consumption plus static/AST cutover integrity.

## Market calibration

Engineering acceptance never increases Market Calibration. It remains 0 / UNVALIDATED until real external outcomes are recorded through the existing pre-registered market-result path.

## R2 acceptance-plane separation

The installer runs deterministic static/adversarial/scale acceptance exactly once, then runs a separate `--live-only` SELECT-only derived-plane acceptance. The live phase must not re-run synthetic or scale suites. This preserves the same gates while preventing package orchestration from consuming the live timeout budget on work that already passed. The live phase still requires Production truth fingerprints to remain identical before/after, first Brain refresh <120s, identical second refresh <5s with zero new events, Radar sole atomic truth authority, Shadow zero authority, and no fabricated market calibration.

## G2 live-shaped admission regression

A dedicated corpus-shape fixture now mirrors the failure mode seen in live R2 acceptance:
158 candidates, >1,400 transition-looking observations, mostly generic subjectless timing/C12
context, with only a small number of direct/explicit structural transitions. Acceptance requires:

- generic timing context is not lineage-admitted;
- persistent TransitionLineages stay bounded;
- context-only problem-transition pairs are not materialized;
- context observations are not duplicated into the Brain append-only ledger;
- event volume and first-refresh runtime remain bounded.

This is a semantic admission test, not a relaxed timeout test.


## Persistence/projection performance acceptance

The 1,200-candidate large-scale fixture retains the original <15s end-to-end requirement and additionally requires explicit performance telemetry. Structural build must remain <8s. The refresh reports event diff, append, projection apply, projection snapshot, and total-before-surface timings so a filesystem/projection regression cannot be misdiagnosed as semantic clustering cost.

## G3 structural-recall acceptance

G3 adds positive and adversarial gates for the new staging plane:

- independent specific verified context can form a TransitionHypothesis;
- generic timing context cannot form a persistent transition;
- broad cross-problem context cannot promote without a sparse identity anchor;
- same-ProblemLineage independent context may corroborate a problem-scoped transition;
- repeated evidence from one source family/content unit cannot satisfy independence;
- a StructuralBridgeHypothesis is research-only and cannot self-promote to an intersection;
- pre-thesis bridge research can enter the VOI queue even when no OpportunityThesis exists;
- Radar remains the sole atomic truth owner.

A dedicated >3,000-row verified-context stress fixture mixes thousands of generic timing observations,
problem-scoped true transitions, cross-problem sparse-anchor true transitions, and independence
decoys. It must remain bounded, recover only the intended transition hypotheses, and prevent generic
regulatory/process vocabulary from becoming a fake global transition.

## G3 thesis lifecycle acceptance

Acceptance verifies that the same thesis identity can move through CREATED -> DIED -> REVIVED,
that lifecycle history is retained, and that `revision` tracks semantic change rather than refresh
count. Zip2 acceptance also verifies the Gate+Vector model and rejects weighted-average authority.

## G2 -> G3 derivation migration acceptance

An unchanged Production truth fingerprint must not cause a no-op when the installed Brain engine is
G2. The first G3 refresh must report a derivation-engine upgrade and rebuild derived state. The next
identical refresh must return to fast no-op. Brain-only schema metadata may migrate from compatible G2
to G3; unknown schema versions fail closed. Production DB schema is never migrated by this process.

Installer rollback for G3 includes Brain derived runtime state (event DB, projection DB and JSON
surfaces) in addition to code. A failed live derivation migration therefore restores both G2 code and
the exact pre-upgrade G2 derived state.

## G3 API acceptance

The existing read-only Brain API remains intact and adds two read-only research/diagnostic surfaces:

- `GET /api/signalforge/brain-v2/transition-hypothesis/{hypothesis_id}`
- `GET /api/signalforge/brain-v2/bridge-hypothesis/{hypothesis_id}`

Effective route verification uses a fresh OpenAPI schema rather than flattening `app.routes`.
