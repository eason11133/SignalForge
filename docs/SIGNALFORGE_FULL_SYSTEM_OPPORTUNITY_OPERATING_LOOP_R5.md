# SignalForge R5 — Full-System Opportunity Operating Loop

Release intent: **system-wide major upgrade**, not a bug patch and not a market-accuracy claim.

Baseline: confirmed installed R4 (`signalforge-live-telemetry-dispatch-truth-closure-r4`).

R5 objective: turn the R1–R4 intelligence stack into one bounded operating loop that can decide **what the machine should research, what the Founder should do, what should wait/park, how real-market actions are pre-registered, and how results flow back without bypassing truth gates**.

## Truth boundary

Engineering completion, Founder Product Acceptance, and Market Truth remain separate.

- R5 may improve routing, execution readiness, runtime cost, UI operability, and calibration plumbing.
- R5 does **not** convert UNKNOWN/PARTIAL/INSUFFICIENT into SUPPORTED merely because an action is scheduled or completed.
- Thesis-level Founder actions have zero direct C01–C14 write authority.
- Atomic human-market evidence remains owned by the existing pre-registered `validation_registry` + `market_ground_truth` path.
- A completed thesis action cannot be retroactively converted into atomic claim evidence by registering a claim experiment after the outcome is known.
- One failed market experiment remains INSUFFICIENT; it is not automatic REFUTE.
- Structural/Zip2 calibration is never inferred from fast buyer tests.
- Live Market Calibration may validly remain **0 / UNVALIDATED** until real outcomes exist.

## Full-system audit

Percentages below are the pre-existing engineering-readiness baselines used by `system_wide_audit.py`; R5 intentionally does not auto-inflate them. “R5 advance” describes concrete implementation progress that must be confirmed by a live R5 cycle or real market outcomes where applicable.

| Area | Baseline | Main R4/R5 problem | Root cause | R5 advance | Acceptance |
|---|---:|---|---|---|---|
| Data Sources / Crawlers | existing baseline | technical troubleshooting can consume scarce discovery budget | source rows were treated too uniformly before expensive enrichment | source-role portfolio classifies pain/workaround/buyer/transition/solution/timing vs troubleshooting; sparse opportunity-bearing batches may underfill instead of filling with noise | discovery portfolio static/behavior tests + live cycle telemetry |
| Source Coverage / Health | existing baseline | source refresh and research budget were not fully downstream-decision aware | coverage state and execution state were separate concerns | exhausted/wait states flow into the execution governor; no unchanged-corpus recurrence loop | R2/R5 regression + live queue |
| Problem Discovery | 85 target / prior baseline retained | transient driver/version/dependency issues still competed with structural signals | “processable” did not equal “worth expensive enrichment” | opportunity-bearing enrichment portfolio precedes expensive enrichment; raw observations remain preserved | R5 discovery acceptance |
| C02 Recurrence | 82 | recurring search could still be scheduled from broad eligibility | admission telemetry was mistaken for execution scope | one canonical bounded machine universe; SEARCH_EXHAUSTED waits for corpus/method change | R2/R5 acceptance + live bounded counts |
| C03 Pain Materiality | 79 | expensive reducers needed the same scope authority as C02 | phase-local selectors | all expensive lanes consume the governor’s bounded machine set | source contract + live lane counts |
| Evidence Ledger | 94 | must not be weakened while changing work routing | execution changes risk accidental truth promotion | critical ledger writer/evaluator hashes frozen | R1–R5 frozen-function checks |
| Evidence Integrity / Quality Guard | 96 | Founder activity could be mistaken for truth | action history and evidence authority were previously adjacent concepts | explicit zero-direct-write boundaries; atomic market path remains quality locked | R5 acceptance + R1 regression |
| C05 Buyer Reality | 78 | buyer prefetch previously could escape the bounded active universe | phase-specific prefetch | C05 prefetch shares the same bounded machine universe | R4/R5 acceptance + live cycle |
| C06 Current Solution | 69 | solution research could spend on parked/waiting cases | machine eligibility vs execution set ambiguity | C06/C07 use governor-selected rows only | R4/R5 acceptance |
| C07 Unresolved Gap | 62 | same as C06; late rejection cost | same | bounded shared execution scope + Brain non-research routing outranks machine research | R5 acceptance |
| C08 Differentiation | 68 | parallel-reality lane could fan out beyond bounded work | independent target selector | parallel C08–C14 lane uses bounded active universe | R4/R5 acceptance |
| C09 Execution Reality | 80 | “market good” and “Eason can execute/capture” still needed operational separation | objective opportunity and first-person right-to-win were mixed historically | Brain Founder Addressability remains separate and can route to Founder discovery / stop-or-partner rather than machine research | Brain/R5 integration acceptance |
| C10 Distribution | 67 | distribution truth had a CLI-quality path but no Founder-operable UI/API loop | validation registry not connected to product surface | claim-specific pre-registration + result recording UI/API, using existing market-ground-truth writer | R5 validation workflow acceptance + live experiment later |
| C11 Economics / WTP | 68 | same; price PASS needs stronger quality requirements | CLI-only closure | UI/API requires pre-registration; existing PRICE/PAID_PILOT PASS amount/currency gate preserved | R5 acceptance + real outcome |
| C12 Opportunity Window | 72 | should not receive fake support from action execution | execution metadata could be confused with truth | market action registry has zero atomic write; structural outcome remains separate | R5 truth-boundary tests |
| C13 Competition | 71 | same | same | same | R5 regressions |
| C14 Switching | 68 | switching experiment path not product-operable | CLI-only closure | pre-register C14, record through existing quality-locked market writer, scoped decision recompute | R5 validation workflow acceptance |
| Decision Engine | 87 | R3 live `round_final_decision` was ~287.7s | full-world Company/Commercial/floor reduction and `None`/`[]` scope ambiguity | `None=full`, `[]=explicit zero`; no-source/touched-case cycles use scoped persisted reduction; untouched durable disposition not mutated | explicit-zero tests + live R5 phase timing |
| Research Controller | 91 | research could continue after Brain had a higher-VOI Founder/market action | no single truth→work authority | Execution Governor routes MACHINE_RESEARCH / MARKET_ACTION / FOUNDER_DISCOVERY / WAIT / PARK / MONITOR; Brain non-research action outranks machine research | R5 governor acceptance |
| Scheduler / Research Portfolio | 78 | “163 eligible” looked like “163 executing” and lanes had inconsistent scopes | eligibility and execution telemetry conflated | eligible total separated from bounded execution set; operating queue counts are not display-truncated | R5/R4 acceptance + live telemetry |
| Brain structural intelligence | engineering path retained | Brain advisory could prioritize but not fully own next-work routing | Candidate-centric runtime remained dominant | candidate-level Brain action map feeds governor; structural thesis remains derived strategic authority, not market truth | Brain static gate on user venv + R5 source acceptance |
| Zip2 structural search | outcome-dependent | no current golden overlap / high-conviction structural outcome proved | evidence/outcome scarcity, not merely code | R5 protects structural track from fast-test relabeling and routes fatal unknowns/actions coherently | structural registry + real longitudinal checkpoints |
| Founder Addressability | outcome-dependent | first-person credibility/right-to-win needed actionable next steps | addressability state existed but execution routing was incomplete | Founder discovery, legitimacy/channel actions are first-class routes; quality-approved outcomes calibrate addressability only | market-action quality tests + future outcomes |
| Strategic Track | derived | machine work could ignore thesis-level next action | runtime still Candidate-first | governor respects Brain MARKET_ACTION / FOUNDER_DISCOVERY / HOLD / STOP_OR_PARTNER before machine work | R5 acceptance |
| Founder Daily / UI | 78 | product surface showed intelligence but not a complete operating loop | action/validation objects lived outside Founder workflow | operating lanes, thesis actions, quality-gated action result form, atomic claim experiment preregistration/result form | R5 UI source tests + local production build |
| VALIDATE → Market Test | 78 | thesis action registration alone is not atomic evidence preregistration | two distinct validation authorities were not product-connected | both levels are now explicit: thesis-level action registry for execution/calibration; claim-specific C10/C11/C14 registry for atomic truth | R5 73/73 no-DB + live experiment later |
| Market Result → Evidence → Decision | 65 | CLI existed, UI/API missing; risk of post-hoc conversion | market truth closure not product-operable | existing `market_ground_truth` remains sole writer; workflow closes immutable registry then recomputes only affected case | R5 validation workflow tests + real outcome later |
| Calibration Infrastructure | 72 | recorded PASS/FAIL could be too subjective; Founder discovery could contaminate fast validation | outcome recording and calibration eligibility were conflated | durable outcome-quality gate; split eligible domains; pretest snapshot/sample/actors/evidence refs/category-specific observation requirements | R5 calibration tests |
| Live Market Calibration | **0** | no real outcome cohort yet | external market constraint | readiness advances only; value remains 0 / UNVALIDATED until outcomes | real-world only |
| Predictive Accuracy | UNVALIDATED | no sufficient treatment/control outcome set | external market constraint | no fabricated accuracy metric | real-world only |
| Runtime / process isolation | R3/R4 high readiness | API blocking solved; telemetry improved | heavy work was once event-loop coupled | R5 preserves R3 process isolation and R4 liveness/progress semantics | R3/R4 regressions + post-install live cycle |

## Shared root causes addressed in R5

### 1. Eligibility was not execution authority
R2/R4 could describe bounded work, but multiple layers still had their own local selection semantics. R5 introduces one `signalforge_execution_governor` that translates current truth + Brain next action + exhaustion state into one explicit route. Only `MACHINE_RESEARCH` enters expensive machine execution, and that set is hard bounded.

### 2. Candidate backlog still leaked into a thesis-first product
Brain v2 owned structural strategy, but Candidate/runtime work could keep researching after a thesis-level action had higher value. R5 carries Brain candidate actions into the governor so MARKET_ACTION, FOUNDER_DISCOVERY, HOLD, and STOP_OR_PARTNER outrank legacy machine research.

### 3. Discovery spent scarce enrichment budget on the wrong class of signal
Raw technical troubleshooting is useful context but is not equivalent to a durable opportunity signal. R5 keeps every raw observation, classifies source role for scheduling only, and caps troubleshooting when opportunity-bearing signals exist. A sparse good batch is allowed to remain sparse.

### 4. Real-market execution had two concepts but no complete product loop
A thesis-level Founder action answers “what should Eason do next?”; a claim-specific validation experiment answers “what pre-registered real observation is allowed to update C10/C11/C14?”. They are intentionally separate. R5 exposes both in UI/API without inventing a new truth writer and explicitly blocks retroactive post-outcome preregistration.

### 5. Outcome history was not identical to calibration evidence
R5 separates “recorded action outcome” from “calibration-eligible observation”. Binary thesis-action outcomes require the frozen pre-test snapshot, full pre-registered sample, identified actors, durable evidence references, and category-specific observed behavior/findings. Founder discovery can calibrate Founder Addressability but cannot masquerade as fast-market validation.

### 6. `None` and `[]` had dangerous scope ambiguity
A zero-work cycle could accidentally fan out to full-world reducers because Python truthiness treated an explicit empty list like no scope. R5 standardizes `None = full universe`, `[] = explicit zero`, and scopes no-source/touched-case decision work without mutating untouched durable dispositions.

## Founder operating loop after R5

1. External observations are preserved.
2. Discovery portfolio allocates expensive enrichment toward opportunity-bearing source roles.
3. Atomic evidence continues through unchanged truth gates.
4. Brain derives structural thesis + Founder Addressability + best next action.
5. Execution Governor assigns one route per case.
6. Only bounded MACHINE_RESEARCH enters expensive research lanes.
7. MARKET_ACTION / FOUNDER_DISCOVERY are pre-registered with immutable thesis snapshots.
8. If atomic C10/C11/C14 market truth is required, a separate claim-specific experiment must be pre-registered **before** the result.
9. Claim result is recorded only through `market_ground_truth`; PASS quality rules remain; FAIL remains INSUFFICIENT.
10. Only the affected case is recomputed after atomic result ingestion.
11. Calibration consumes only domain-eligible outcomes; structural calibration remains longitudinal and separate.

## Acceptance status in assistant environment

At package build time:

- R5 full-system no-DB acceptance: **73 / 73 PASS**.
- R4 telemetry regression: **31 / 31 PASS**.
- R3 process-isolation regression: **28 / 28 PASS**.
- R2 production-focus regression: **50 / 50 PASS**.
- R1 Full-System Rebase regression: **49 / 49 PASS**.
- Critical production-admission / recurrence / ledger truth functions remain hash-frozen.
- Modified Python compilation passes.
- Assistant sandbox does not contain the project dashboard package/node_modules and lacks the project `asyncpg` environment, so it does **not** claim Brain static or Dashboard production build PASS here. The R5 installer runs both on the user's actual project venv as mandatory hard gates and rolls back if either fails.

## Post-install live acceptance required

One real R5 cycle must confirm:

- API remains responsive under worker load (R3 invariant).
- effective dispatch / watchdog / semantic progress remain truthful (R4 invariant).
- `machine_research_eligible_total` is distinct from actual bounded execution.
- all expensive C02/C03/C05/C06/C07/C08–C14 lanes use the same bounded active universe.
- no-work / unchanged-corpus cases do not trigger full-world reducer work.
- final decision phase materially benefits from scoped reduction relative to the R3 287.7s live baseline, without changing untouched truth/disposition.
- Founder operating queue and claim-validation surfaces load from the new snapshot/API.

A real market experiment is **not** required to accept the R5 engineering release. It is required before Live Market Calibration can move above 0 / UNVALIDATED.

## Explicit non-claims

R5 does not claim:

- that a Zip2-class opportunity has been found;
- that Founder Addressability is validated;
- that fast-validation predictions are accurate;
- that structural opportunity predictions are accurate;
- that Market Calibration is above zero;
- that a completed Founder action is atomic market truth;
- that engineering green tests constitute Product or Market Acceptance.
