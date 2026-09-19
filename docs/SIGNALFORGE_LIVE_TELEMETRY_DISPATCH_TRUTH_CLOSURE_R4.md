# SignalForge Live Telemetry + Dispatch Truth Closure R4

Baseline: confirmed installed **R3** (`signalforge-runtime-process-isolation-live-acceptance-closure-r3`).

## Why R4 exists

The first real R3 process-isolated production cycle fully completed and proved the core isolation fix works. During C02, C03, C06/C07, C05, parallel reality, and the final decision phase, `/api/signalforge/status` remained responsive in roughly tens of milliseconds instead of timing out with the heavy production workload. The cycle finished `PASS`, the runtime lease released, the worker exited, and `last_success_at` advanced with no runtime error.

That same live run exposed four production/runtime defects that are independent of market truth:

1. **Persisted dispatch receipt race** — the dispatch receipt remained `DISPATCHED` even while the worker owned the canonical runtime lease, and remained `DISPATCHED` after the worker had finished.
2. **Non-canonical progress shape** — phases emitted useful keys such as `cases_completed/cases_total` or only `targets`, while the Founder monitor expected `current/total`, rendering an empty `progress=/`.
3. **Long quiet substeps** — C05, C06/C07, and final-decision work could remain in a real active phase for long periods without a semantic progress heartbeat, making process liveness and semantic progress indistinguishable.
4. **R2 bounded-workload integration leak / misleading telemetry** — final live admission reported `173` rows and `163` machine-research-eligible rows. C02/C03 did use the bounded active selector, but C05/C06/C07 prefetch and C08-C14 parallel-reality selection could still draw from the full machine-eligible universe. The summary field `active_machine_research=163` also looked like the actual execution set even though the intended execution cap is 24. This is a scheduling/runtime defect, not market truth.

R4 closes these dispatch, telemetry, and bounded-execution gaps. It does **not** change C01-C14 evidence standards, semantic same-problem thresholds, SUPPORT writers, Founder/Brain truth authority, strategic-track gates, or market calibration.

## R4 changes

### 1. Effective dispatch state

`processors/signalforge_runtime.py` now preserves the persisted receipt as `persisted_status` but derives an effective `status=WORKER_RUNNING` when the same live worker PID owns the canonical runtime lease or active runtime progress.

The worker receives an explicit `dispatch_id`, and `WORKER_STARTED` is re-asserted after the canonical lease is acquired. A completed/dead worker can therefore no longer present as if dispatch never progressed.

### 2. Separate process heartbeat from semantic progress

`processors/signalforge_runtime_progress.py` now uses a separate watchdog heartbeat file.

- watchdog heartbeat means only: **the isolated worker process remains alive enough to tick**;
- progress events mean: **the current phase reported a new semantic execution checkpoint**.

New fields include:

- `heartbeat_source`
- `heartbeat_age_seconds`
- `progress_age_seconds`
- `heartbeat_state`
- `progress_state`

A state of `PROCESS_ALIVE_NO_RECENT_PROGRESS` is intentionally not a failure and cannot be interpreted as market/research success.

### 3. Canonical current/total progress projection

Heterogeneous phase fields are projected into a non-authoritative UI shape:

- `current`
- `total`
- `unit`
- `percent`

Examples:

- `cases_completed/cases_total` -> `current/total`, unit `cases`
- phase-level `targets` -> `0/targets` until actual completion evidence exists

R4 never invents completed work.

### 4. Inner C05/C06/C07 progress checkpoints

Telemetry-only heartbeats were added around:

- C05 target load, buyer corpus, structured sources, retrieval, per-case verification, AI adjudication, completion;
- C06/C07 target load, solution corpus, retrieval, per-case verification, AI pair adjudication, completion.

Evidence stance, AI gates, budgets, source-family thresholds, same-problem validation, materialization, and claim refresh rules are unchanged.

### 5. One bounded execution universe for every expensive lane

The live R3 result showed that `machine_research_eligible` was still too broad to serve directly as an execution set. R4 therefore makes the canonical `_active_workload_rows()` set the shared input universe for every expensive lane:

- C02 recurrence
- C03 materiality
- focused gate research
- C05 buyer prefetch
- C06 current-solution prefetch
- C07 unresolved-gap prefetch
- C08-C14 parallel reality

No expensive prefetch/parallel lane may bypass the 24-case bound merely because a row is machine-eligible.

The final cycle payload now distinguishes:

- `machine_research_eligible_total` — all rows allowed in principle to receive machine research later;
- `bounded_active_workload` — the actual current execution universe;
- `bounded_active_workload_limit` — the configured cap;
- `bounded_active_case_ids` — the selected execution set;
- `execution_workload` — per-phase selected counts.

The legacy `active_machine_research` field remains for compatibility but is explicitly tagged as `ELIGIBLE_TOTAL_NOT_EXECUTION_SET`.

### 6. Founder UI

The runtime banner and System page distinguish:

- effective dispatch vs persisted dispatch receipt;
- worker heartbeat vs semantic progress;
- bounded `current/total` progress when available.

## Live R3/R2 findings that are now closed by R4

Observed live R3 final state:

- runtime: `PASS`
- runtime lease: released
- worker: exited
- `last_success_at`: advanced
- runtime error: none
- API remained responsive during the heavy cycle

Observed R2 admission/funnel state on that cycle:

- total rows: `173`
- machine-research-eligible total: `163`
- recurrence-eligible: `29`
- monitor context: `8`
- deferred ephemeral: `2`
- `WAIT_FOR_NEW_SOURCE_COVERAGE`: `124`
- `CHANGE_SOURCE_MARKET_ACTION_OR_PARK`: `17`
- `DECISION_CRITICAL_RESEARCH`: `31`

The key correction is that `163` is **not** the current expensive execution set. R4 exposes the actual bounded execution set separately and prevents C05/C06/C07/C08-C14 side lanes from escaping it.

The live cycle also showed `round_final_decision` as the largest remaining phase (~288 s). R4 records and surfaces this accurately but does not weaken or shortcut the decision/truth path merely to reduce that number. It remains a future performance target for evidence-preserving optimization.

## Acceptance performed in build environment

- R4 no-DB acceptance: **31/31 PASS**
- R3 process-isolation regression: **28/28 PASS**
- R2 funnel regression: **50/50 PASS**
- R1 full-system rebase regression: **49/49 PASS**
- critical R2/R1 truth/admission function hashes: unchanged
- modified Python modules: compile PASS

The package-builder environment lacks the local project `asyncpg` dependency and dashboard `node_modules`, so it does **not** claim Brain static or Dashboard production-build acceptance from this sandbox. The installer runs both as mandatory hard gates in the user's real project venv/repo and rolls back on failure.

## Live truth boundary

R3 process isolation is now **live accepted** by the completed real cycle.

R2's intended bounded workload was only **partially live accepted**: C02/C03 were bounded, but side-lane prefetch/parallel selection leaked beyond the same active universe. R4 closes that integration defect. R4 itself remains pending live acceptance until installed and exercised in a later cycle.

## Market calibration

Unchanged:

`0 / UNVALIDATED`

Engineering completion, runtime liveness, bounded scheduling, and telemetry correctness have zero authority to promote market calibration.
