# SignalForge Runtime Process Isolation + Live Acceptance Closure R3

Release: `signalforge-runtime-process-isolation-live-acceptance-closure-r3`

Baseline: installed R2 (`signalforge-thesis-controlled-production-funnel-runtime-truth-closure-r2`)

## Why R3 exists

The first attempted R2 live acceptance exposed a control-plane defect before the new R2 funnel could be meaningfully validated:

- `POST /api/signalforge/trigger` did not return inside the 10 second client timeout.
- While the triggered production work was active, `GET /api/signalforge/status` also timed out.
- The PowerShell shell then kept an older `$s` object, making the subsequently printed `PASS / running=False / NO_PROGRESS_RECORDED` values stale client-side data rather than evidence that the new cycle had completed.
- The visible `last_cycle.total_cycle = 649.13s` snapshot was the prior completed cycle, not the newly triggered R2 cycle.

Root cause: the route already used `asyncio.create_task`, but the scheduled coroutine can begin CPU/blocking work before FastAPI has flushed the trigger response. The production cycle also shares the web process event loop, so synchronous CPU/network segments can starve unrelated status/health requests. `create_task` is task concurrency, not workload/process isolation.

## R3 architecture

R3 makes the FastAPI process a control plane only.

```text
Founder / Scheduler / Startup catch-up
        |
        v
launch_signalforge_cycle_nonblocking()
        |
        | subprocess.Popen(sys.executable, worker)
        v
run_signalforge_runtime_worker.py
        |
        v
canonical run_signalforge_if_stale()
        |
        v
existing cross-process lease
        |
        v
R2 production funnel / C01-C14 truth pipeline
```

The worker uses the same project virtual-environment Python and the same repository working directory. It writes a durable worker log and dispatch receipt under `.radar_runtime/`.

## Changes

### 1. Manual API trigger is now process-isolated

`POST /api/signalforge/trigger` calls `launch_signalforge_cycle_nonblocking(force=True, reason="manual_api")` and returns HTTP 202 without executing the production cycle on the web event loop.

### 2. Scheduler is process-isolated

The hourly stale-aware scheduler dispatches a worker rather than directly awaiting the heavy runtime coroutine inside `AsyncIOScheduler`'s web-process loop.

### 3. Startup catch-up is process-isolated

The delayed startup check dispatches a worker after database readiness rather than executing the cycle inside the FastAPI lifespan loop.

### 4. Durable dispatch state

`.radar_runtime/signalforge_runtime_dispatch.json` records:

- dispatch id
- worker pid
- reason
- launch time
- LAUNCHING / DISPATCHED / WORKER_STARTED / WORKER_FINISHED / WORKER_FAIL
- worker liveness and age through `/api/signalforge/status`

Dispatch state has **zero market-truth authority**.

### 5. Durable worker log

`.radar_runtime/signalforge_runtime_worker.log` receives detached worker stdout/stderr so a background failure is inspectable without blocking the API request.

### 6. UI control-plane visibility

The global runtime banner and System page surface dispatch state before the worker acquires the production lease. Founder should be able to distinguish:

- request accepted / dispatching
- worker alive
- canonical production lease running
- phase heartbeat/progress
- finished / failed

## Truth and R2 funnel invariants frozen

R3 does **not** change:

- R2 `assess_candidate_admission`
- R2 `assess_pre_enrichment_discovery`
- same-problem semantic structural gate
- SUPPORT evidence writer
- Radar initial evidence links
- claim evaluator
- C01-C14 thresholds
- Brain strategic classification
- Founder addressability rules
- market-test outcomes
- calibration

Market Calibration remains `0 / UNVALIDATED` until real outcomes exist.

## R3 no-DB acceptance

The R3 acceptance suite checks:

- trigger no longer creates the production task in the FastAPI event loop
- scheduler and startup use process dispatch
- launcher uses `subprocess.Popen` + `sys.executable`
- durable dispatch and worker log exist
- status exposes dispatch + existing R2 progress
- worker re-enters the canonical runtime/lease instead of bypassing truth authority
- mocked dispatch returns under 250 ms without running a production cycle
- R2 admission function hashes are unchanged
- R1 critical evidence/truth function hashes are unchanged
- modified Python files compile
- System/banner expose dispatch state

Package installer additionally runs:

1. R3 no-DB acceptance
2. R2 thesis-controlled funnel acceptance
3. R1 Full-System Rebase regression
4. Brain v2 static acceptance
5. Dashboard production build

Any hard-gate failure rolls source files back.

## Live acceptance required after installation

Engineering acceptance is not enough. R3 is live-product accepted only when a real local PostgreSQL-backed cycle proves all of the following:

1. `POST /api/signalforge/trigger` returns promptly with a dispatch receipt.
2. `GET /healthz` remains responsive while the worker runs.
3. `GET /api/signalforge/status` remains responsive throughout the production cycle.
4. dispatch transitions to a real worker pid and worker liveness is visible.
5. canonical runtime lease becomes RUNNING in the worker process.
6. R2 phase heartbeat/progress becomes visible while the cycle runs.
7. production cycle completes or fails visibly without starving the API process.
8. R2 production-admission metrics can finally be evaluated on the real database.
9. no atomic Production truth is promoted merely because dispatch/runtime engineering passed.

## Market truth status

- Engineering: pending installer hard gates on user R2 checkout
- Live R3 Product Acceptance: PENDING
- Live R2 Funnel Acceptance: PENDING until first process-isolated live cycle completes
- Market Calibration: `0 / UNVALIDATED`
- U29: NOT OPENED
