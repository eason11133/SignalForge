# SignalForge R6 — Full-System Live Efficiency + Strategic Freshness

## Why R6 exists

The first real R5 cycle completed successfully, but its live telemetry exposed three cross-system defects that a no-DB/static gate could not prove away:

1. **Cold corpus change still collapsed back to a full-world final decision.** The R5 cycle had only 24 bounded active cases, yet any fresh raw source/discovery change set `raw_reality_refresh_required`, which made `_incremental_decision_scope()` return `None`. `run_opportunity_reality()` then rematerialized fuzzy market context for every historical case. This is the primary reason `round_final_decision` increased to ~413.5s instead of shrinking.
2. **Execution-set semantics were still ambiguous at the Founder surface.** Live telemetry showed 165 machine-eligible rows, 24 bounded execution rows, but the operating queue displayed 26 `MachineResearch` rows. Eligibility, selected execution, and bounded-capacity backlog were not represented as three different things.
3. **The Founder operating loop was strategically stale by construction.** Production completed, the Founder daily snapshot was published, and only then Brain v2 was launched non-blocking. New discovery/truth from the cycle could therefore change Brain strategy after the published operating queue had already been frozen. A thesis newly routed to `MARKET_ACTION` or `FOUNDER_DISCOVERY` could remain invisible until a later cycle.

R6 fixes these shared root causes together instead of patching a single timer or UI field.

## Live evidence that triggered the upgrade

R5 live cycle:

- Trigger: HTTP 202 in ~158ms.
- Runtime completed PASS with no error.
- Total rows: 175.
- Machine eligible: 165.
- Bounded active execution: 24 / 24.
- Recurrence eligible: 25.
- Founder operating queue: 26 MachineResearch, 0 MarketAction, 0 FounderDiscovery, 131 Waiting, 17 Parked, 1 Monitor.
- New candidates: 3; new Radar cases: 2; one candidate deferred before Radar.
- Phase wall-clock: source_refresh ~75.1s; C02 ~69.9s; C03 ~17.8s; C06/C07 ~122.6s; C05 ~115.6s; C08-C14 ~6.0s; round_final_decision ~413.5s; total ~936.5s.

R6 does **not** interpret this cold ENGINE_UPGRADE cycle as market failure or market accuracy evidence. It uses the telemetry only to diagnose execution architecture.

## R6 system-wide changes

### 1. Raw reality materialization is now explicitly scoped

`run_opportunity_reality(case_ids=...)` now supports a strict case scope.

- `None` = historical full refresh.
- `[]` = legal explicit no-op.
- `[ids...]` = only those cases are rematerialized against the current market corpus.

This changes refresh work, not evidence thresholds. Unscoped cases keep their durable published state.

### 2. Fresh corpus no longer means full-world invalidation

R5 treated any fresh source/candidate corpus as a reason to return `None` from `_incremental_decision_scope()`. R6 removes that global invalidation.

A cold corpus/discovery cycle now rematerializes only the bounded active + newly-created case scope. If a waiting case is legitimately reopened by fresh evidence routing, it enters that bounded universe and is refreshed then.

### 3. Scoped materialization + full read-only projection

A scoped `materialize` decision now:

1. rematerializes only the explicit decision scope;
2. writes only evidence/claim updates produced by that scoped materializer;
3. rebuilds the complete Founder attention view from persisted truth;
4. preserves every unscoped RadarCase disposition without reducer mutation.

This preserves a coherent full Founder surface without paying full-world fuzzy retrieval cost.

### 4. Unscoped legacy structural compatibility work is skipped

Brain v2 is the structural strategy authority. The legacy `assess_solo_transition()` compatibility classifier no longer reruns for every untouched historical case during a scoped final decision.

Unscoped rows receive an explicit `PERSISTED_UNSCOPED_COMPATIBILITY` marker with zero decision authority.

### 5. Final-decision telemetry is now subphase-aware

R6 persists final-decision `subphase_ms` and emits live progress for:

- reality projection/materialization;
- Company Reality reduction;
- Commercial Reality reduction;
- Floor60 reduction;
- scoped decision projection;
- progression projection.

This prevents a 400-second phase from appearing as a single opaque `0/24` block.

### 6. Cold vs warm cycle classification

Every cycle now records a `cycle_profile`:

- `COLD_CORPUS_OR_DISCOVERY_CHANGE`, or
- `WARM_PERSISTED_DECISION`.

It also records source groups attempted/refreshed, discovery status/reason, and decision materialization scope. Future performance comparisons can therefore compare like with like instead of comparing a cold source-refresh cycle against a warm persisted cycle.

### 7. Machine eligibility, selected execution, and backlog are separated

The Execution Governor now marks each machine-routable row with:

- `machine_execution_eligible`
- `machine_execution_selected`
- `machine_execution_deferred_by_capacity`

Founder operating queue semantics become:

- `machine_research` = selected in the current bounded execution window;
- `machine_research_backlog` = eligible but deferred by bounded capacity;
- `machine_research_eligible_total` = selected + backlog.

Synthetic acceptance proves 26 eligible with a 24 cap produces exactly 24 selected + 2 capacity backlog.

### 8. Brain refresh happens before Founder publication

After production research finishes, R6 performs a bounded synchronous **derived** Brain refresh before building the Founder daily surface.

Truth boundary remains unchanged:

- Brain does not own C01-C14.
- Brain refresh failure cannot roll back production truth.
- A timeout/failure is recorded as derived staleness, and a detached fallback refresh may be launched after Production PASS.

### 9. Founder routing is recomputed against the post-cycle Brain

After the Brain refresh, R6 re-runs only the execution-routing layer over the final decision rows using the newest Brain advisory. It does not re-evaluate Radar claims.

This closes the R5 timing bug where a thesis could become `MARKET_ACTION` or `FOUNDER_DISCOVERY` after the daily operating queue had already been published.

### 10. Founder/System UI and audit surfaces are coherent with the new semantics

UI now distinguishes:

- selected Machine research;
- Capacity backlog;
- Market action;
- Founder discovery;
- Waiting;
- Park / monitor.

The operating-loop API also returns the published Founder strategy/Brain freshness. System audit includes cycle profile, Brain refresh status, and post-Brain routing diagnostics.

## What R6 deliberately does not claim

R6 does not claim that SignalForge has found a good business opportunity.

R6 does not promote Market Calibration.

R6 does not turn `0 MarketAction` into a positive signal. It only ensures that after the next real cycle, a zero is a fresh post-Brain routing result rather than a stale publication artifact.

R6 does not weaken C01-C14, same-problem, buyer, solution-gap, or Radar decision gates. The six critical frozen functions remain byte-for-byte hash-locked.

## Engineering acceptance

Assistant environment:

- R6 no-DB acceptance: 37 / 37 PASS.
- R5 regression: 73 / 73 PASS.
- R4 regression: 31 / 31 PASS.
- R3 regression: 28 / 28 PASS.
- R2 regression: 50 / 50 PASS.
- R1 regression: 49 / 49 PASS.
- Critical truth/admission function hashes unchanged.
- Modified Python files compile.

Brain v2 static acceptance cannot be honestly executed in the assistant sandbox because `asyncpg` is absent. Dashboard production build cannot be honestly executed here because the assistant snapshot does not contain `dashboard/package.json`/node_modules. Both remain mandatory installer hard gates on the user's real R5 repository.

## Live Product Acceptance still required

After successful R6 installation, one real post-install cycle should verify:

1. trigger remains fast and API remains responsive;
2. a cold corpus/discovery cycle keeps raw-reality materialization scoped;
3. `round_final_decision` subphase telemetry identifies remaining wall-clock cost;
4. `Machine research` equals selected bounded execution, with overflow shown separately;
5. Brain refresh timestamp is post-cycle and Founder operating queue uses the refreshed Brain;
6. any `MARKET_ACTION` / `FOUNDER_DISCOVERY` route is surfaced immediately;
7. Market Calibration remains outcome-dependent and may remain `0 / UNVALIDATED`.
