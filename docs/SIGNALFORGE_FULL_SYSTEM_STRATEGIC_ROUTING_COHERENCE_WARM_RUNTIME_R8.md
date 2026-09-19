# SignalForge R8 — Full-System Strategic Routing Coherence + Warm Runtime Closure

Release target: **R7 → R8 cumulative update**

## Why R8 exists

The first real R7 cycle proved the runtime durability and scoped-decision work, but it also exposed a cross-surface strategic inconsistency that cannot be treated as a cosmetic UI bug.

### Live R7 facts

- Runtime attempt: **PASS**.
- Total cycle: **480.023s**, down from the R5 live 936.5s reference.
- `round_final_decision`: **17.852s**, down from the R5 live 413.547s reference.
- R7 exact retrieval caches were cold on the first cycle: C02 miss; shared C05/C06/C07 cache hits 0, misses 3, writes 3.
- Brain refresh: **PASS**, with one Opportunity Thesis.
- Brain strategy explicitly recommended `FOUNDER_DISCOVERY / IDENTIFY_REACHABLE_BUYER_CHANNEL` for candidate 259 because `BUYER_ACCESS` remained unknown.
- The separately built Founder/market-action queue also saw exactly that one Founder Discovery action.
- However `post_brain_routing` reported `BRAIN_ADVISORY_UNAVAILABLE_NON_BLOCKING`, candidate action count zero, and the Execution Governor left candidate 259 in `WAIT_FOR_NEW_EVIDENCE`.

That is a coherence failure: the strategy layer knew the correct next human action, but the canonical execution router did not receive it.

## Full-system diagnosis

| Area | R7 live state | Root cause / issue | R8 change | Truth authority |
|---|---|---|---|---|
| Runtime durability | PASS | R6 heartbeat collision no longer killed the cycle | Preserve R7 durability; expose top-level observability health | None |
| Final decision | PASS / major speedup | No current defect from live run | Preserve scoped incremental reduction | Existing decision rules only |
| Discovery | FRESH_SKIP | No new source corpus in this cycle | No threshold change | Radar evidence only |
| C02/C05/C06/C07 retrieval | First-cycle caches cold | No warm hit yet, so no measured warm speedup may be claimed | Explicit warm-cache readiness telemetry | Derived performance only |
| Brain refresh | PASS | Portfolio itself was healthy | Preserve Brain truth boundary | Derived structural strategy only |
| Brain → Governor advisory | FAIL | `get_brain_v2_research_advisory()` called `normalize_state()` without importing it, raising `NameError`; safe wrapper converted it to unavailable advisory | Import dependency explicitly and split pure snapshot advisory builder from disk read | Scheduling only |
| Same-cycle strategic freshness | Incoherent | Runtime refreshed Brain then re-read an advisory through a second helper/path | Route from the exact Brain refresh result; persisted helper becomes fallback only | Scheduling only |
| Governor non-research precedence | Latent defect | Every `deferred_item` was treated as PARK before explicit Founder/Market modes; a legitimate deferred machine question could suppress the human action that caused the deferral | Explicit hard-block/refuted/HOLD/STOP precedence; MARKET_ACTION and FOUNDER_DISCOVERY outrank generic deferred research | Scheduling only |
| Right-to-win safety | Partial | `right_to_win=REFUTED` relied too much on deferred research membership | Explicit REFUTED → PARK regardless of machine queue membership | Founder work routing only |
| Cross-surface coherence | Missing invariant | Brain action queue, Governor, Founder UI could disagree silently | New strategic routing coherence report with expected vs actual route | Observability only |
| Founder UI / System UI | Could show contradiction without alarm | No coherence status | Surface routing coherence and cache warmth | None |
| Market Action Registry | 0 outcomes | No real market action completed yet | Unchanged | Market outcomes only |
| Market Calibration | **0 / UNVALIDATED** | No real outcomes | Unchanged; never promoted by R8 | Market outcomes only |

## R8 architecture changes

### 1. Pure same-snapshot Brain advisory

`build_brain_v2_research_advisory(portfolio, limit)` is now a pure projection. The persisted `get_brain_v2_research_advisory()` delegates to it, while runtime can build the advisory directly from the exact portfolio object returned by the just-completed Brain refresh.

This closes read-after-write ambiguity and removes a second stale/failing path from the critical Founder publication sequence.

### 2. Routing precedence is explicit

Work-routing precedence is now:

1. Founder hard block / `right_to_win=REFUTED` / `HOLD` / `STOP_OR_PARTNER` → `PARK`
2. Brain `MARKET_ACTION` → `MARKET_ACTION`
3. Brain `FOUNDER_DISCOVERY` → `FOUNDER_DISCOVERY`
4. Prepared Radar market-validation boundary → `MARKET_ACTION`
5. Machine-resolvable decision-critical gates → bounded `MACHINE_RESEARCH`
6. Exhausted/wait/monitor routes as before

A deferred research question is no longer automatically equivalent to a hard block.

### 3. Strategic routing coherence invariant

R8 checks candidate-level Brain actions that have an existing Radar row:

- `MARKET_ACTION` must route to `MARKET_ACTION`.
- `FOUNDER_DISCOVERY` must route to `FOUNDER_DISCOVERY`.
- `HOLD`, `STOP_OR_PARTNER`, hard-blocked, or `right_to_win=REFUTED` must route to `PARK`.

Brain actions without a Radar row are reported as thesis-only/no-Radar-row. R8 **does not fabricate a Candidate or RadarCase** to make the counts match.

### 4. Cache warmth is explicit, not inferred

R8 adds `warm_cache_readiness`:

- `COLD_PRIMED_NO_HITS_YET`
- `WARM_HITS_CONFIRMED`
- `NO_CACHE_ACTIVITY`

This is performance telemetry only. R8 does not claim additional cache speedup until a real subsequent unchanged/warm cycle produces hits.

### 5. Founder/System surfaces

Founder daily snapshot, `/api/signalforge/operating-queue`, system-wide audit, and dashboard now surface strategic routing coherence. The UI can no longer silently show a Brain action and a contradictory execution lane without a coherence state.

## Frozen truth boundary

R8 does **not** modify the frozen production-truth functions:

- `signalforge_production_admission.py::assess_candidate_admission`
- `signalforge_production_admission.py::assess_pre_enrichment_discovery`
- `problem_recurrence_multi.py::_semantic_structural_detail`
- `problem_recurrence_multi.py::_ensure_support_evidence`
- `radar_ledger.py::initial_links`
- `radar_ledger.py::evaluate`

No R8 routing or observability code writes C01–C14. No engineering PASS can change Market Calibration.

## Engineering acceptance

Assistant environment:

- R8: 37/37 PASS
- R7 regression: 37/37 PASS
- R6 regression: 37/37 PASS
- R5 regression: 73/73 PASS
- R4 regression: 31/31 PASS
- R3 regression: 28/28 PASS
- R2 regression: 50/50 PASS
- R1 regression: 49/49 PASS
- Frozen function hashes unchanged.
- Changed Python files compile.

Environment limitations:

- Brain v2 static acceptance cannot run in the assistant sandbox because `asyncpg` is absent.
- Dashboard production build cannot run in the assistant sandbox because `dashboard/node_modules` is absent.
- The R8 installer therefore runs both as mandatory local hard gates and rolls back on failure.

## Live Product Acceptance still required

After R8 installation, one real post-install cycle must prove:

1. Runtime PASS and observability PASS/diagnosable.
2. `post_brain_routing.brain_advisory_source = SAME_REFRESH_SNAPSHOT` when Brain refresh succeeds.
3. Brain candidate 259 (or the current equivalent) is routed consistently with its Founder action.
4. `strategic_routing_coherence.status = PASS` and mismatch count 0.
5. Warm-cache state is reported honestly. A second sufficiently unchanged cycle is required before claiming warm-cache performance gain.
6. Market Calibration remains 0 / UNVALIDATED until genuine outcomes exist.
