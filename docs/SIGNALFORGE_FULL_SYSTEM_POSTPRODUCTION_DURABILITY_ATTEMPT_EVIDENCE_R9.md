# SignalForge R9 — Full-System Post-Production Durability + Attempt-Evidence Closure

## Why R9 exists

R8 live acceptance reached the post-production Brain refresh, then the runtime failed with:

`NameError: name 'Mapping' is not defined`

The failure was not a Radar truth failure. It was caused by the R8 warm-cache readiness projection inside `signalforge_runtime.py`. The helper used `Mapping` at runtime but the module imported only `Any`. Because the telemetry helper executed on the canonical completion path without a non-authoritative boundary, an observability-only defect turned an otherwise advanced cycle into runtime FAIL.

This exposed a broader shared root cause: post-production derived/telemetry surfaces were not consistently separated from production completion authority, and failed attempts did not retain enough of the already-computed cycle to verify strategy routing, cache warmth, and performance.

## Whole-system diagnosis

| Area | R8 live state | R9 action | Truth authority |
|---|---|---|---|
| Runtime process isolation | PASS before failure; worker/API separation remained healthy | preserved | none on market truth |
| Production research | progressed through C02/C03/C05/C06-C07/C08-C14/final decision | unchanged | existing Radar authority only |
| Brain derived refresh | reached live phase before failure | preserved; attempt evidence retained | derived only |
| Strategic routing | R8 code path existed but completion was interrupted before durable publication | durable attempt projection + future live summary | scheduling only |
| Warm-cache telemetry | runtime NameError killed cycle | direct import fix + best-effort non-blocking wrapper | observability only |
| Failed-attempt diagnostics | error was durable, but phase/profile/Brain/routing/cache structures were largely absent | common attempt projection on PASS and FAIL | diagnostics only |
| Founder/UI validation workflow | required large PowerShell output to reconstruct live acceptance | compact `/api/signalforge/live-acceptance` engineering summary | no product/market authority |
| Market Calibration | 0 / UNVALIDATED | unchanged | real outcome only |

## Changes

### 1. Runtime symbol closure

`signalforge_runtime.py` explicitly imports `Mapping` from `typing` because R8 uses it in runtime `isinstance` checks. R9 acceptance executes the pure runtime helper using only symbols actually declared by the real module, so this class of runtime-only missing-import defect is now covered rather than hidden by `py_compile`.

### 2. Observability cannot kill production

Warm-cache readiness is explicitly performance telemetry. R9 keeps the strict `_warm_cache_readiness()` helper for deterministic tests, but the production path calls `_safe_warm_cache_readiness()`.

If telemetry projection fails, it returns:

- `DEGRADED_OBSERVABILITY_NON_BLOCKING`
- the exact error
- `production_impact = NONE`
- no C01-C14 or market-truth authority

This does not hide production failures. Founder publication, forward-policy snapshot, Radar research, and other authoritative product steps can still fail normally. Only the telemetry projection is prevented from becoming production authority.

### 3. PASS and FAIL attempts preserve the same diagnostic core

R9 introduces one attempt projection containing:

- `phase_seconds`
- `phase_value`
- `cycle_profile`
- production admission/workload
- execution governor
- operating queue
- Brain refresh
- post-Brain routing
- strategic routing coherence
- warm-cache readiness
- final reality mode

The projection is written to `last_attempt_cycle` on both PASS and FAIL. `last_cycle` remains last-success truth and is not overwritten by a failed attempt.

### 4. Successful cycle persistence is complete

R8 computed strategic routing coherence and warm-cache readiness but did not persist both fields into the durable `last_cycle` object. R9 stores them explicitly so System Audit and later acceptance can inspect the actual successful cycle rather than an empty placeholder.

### 5. System-wide audit separates last success and last attempt

System Audit now exposes separate attempt-level fields for:

- Brain refresh
- post-Brain routing
- strategic routing coherence
- warm-cache readiness
- phase seconds

No failed-attempt diagnostic is promoted into last-success or market truth.

### 6. Compact live acceptance API

`GET /api/signalforge/live-acceptance` returns a compact engineering-only summary:

- runtime/attempt PASS state
- worker stopped state
- Brain refresh PASS state
- strategic routing coherence state
- phase seconds
- post-Brain routing
- warm-cache readiness
- published operating counts
- Founder/Market action queue

`engineering_live_gate=PASS` is explicitly **not** Product Acceptance and is not Market Accuracy. It only means the listed engineering execution conditions were observed together in one finished attempt.

## Frozen truth boundaries

R9 does not modify the frozen truth functions:

- `signalforge_production_admission.py::assess_candidate_admission`
- `signalforge_production_admission.py::assess_pre_enrichment_discovery`
- `problem_recurrence_multi.py::_semantic_structural_detail`
- `problem_recurrence_multi.py::_ensure_support_evidence`
- `radar_ledger.py::initial_links`
- `radar_ledger.py::evaluate`

No threshold is lowered. No UNKNOWN becomes PASS. No engineering gate writes market calibration.

## Engineering acceptance

Assistant environment:

- R9 no-DB: 30/30 PASS
- R8 regression: 37/37 PASS
- R7 regression: 37/37 PASS
- R6 regression: 37/37 PASS
- R5 regression: 73/73 PASS
- R4 regression: 31/31 PASS
- R3 regression: 28/28 PASS
- R2 regression: 50/50 PASS
- R1 regression: 49/49 PASS
- frozen truth function hashes unchanged
- changed Python files compile

Brain v2 static acceptance cannot run in the assistant environment because `asyncpg` is unavailable. Dashboard production build is also not asserted by the assistant environment. Both remain mandatory installer gates on the user machine and cause rollback on failure.

## Live acceptance still required

After R9 install, one real cycle must confirm:

1. runtime PASS and last attempt PASS;
2. post-production telemetry cannot kill the cycle;
3. Brain refresh PASS;
4. post-Brain advisory uses the same-refresh snapshot or a clearly diagnosed fallback;
5. strategic routing coherence PASS;
6. the existing Founder Discovery action can propagate into the operating route surface;
7. cache warmth is reported truthfully; a cache miss is valid and must not be relabeled as a speedup;
8. Market Calibration remains 0 / UNVALIDATED until qualified outcomes exist.
