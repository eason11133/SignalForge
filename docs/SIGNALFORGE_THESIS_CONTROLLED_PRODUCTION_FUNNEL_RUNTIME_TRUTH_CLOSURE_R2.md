# SignalForge Thesis-Controlled Production Funnel & Runtime Truth Closure R2

## Release intent

R2 closes a live-production mismatch exposed after R1 installation and DB restoration:

- R1 moved Founder authority toward Opportunity Thesis / Strategic Track / Founder Addressability.
- Production compute still behaved too much like a Candidate backlog machine.
- The 2026-09-04 live cycle showed 168 Radar cases, 166 WATCH, only 2 INVESTIGATE, 4,900 direct-problem documents, 0 newly validated same-problem SUPPORT in the observed pass, and long silent phases that looked hung despite active CPU.
- Several newly formed candidates were transient model/driver/hardware troubleshooting issues rather than strong opportunity-intelligence objects.

R2 therefore changes **compute admission and runtime observability**, not market-truth thresholds.

## Non-negotiable authority boundaries

1. C01-C14 remain canonical atomic market truth.
2. Production admission controls compute/workload only; it cannot write claim truth or promote an opportunity.
3. Brain v2 research relevance is advisory. Founder hard-blocked / right-to-win REFUTED theses remain intelligence but do not automatically consume production research budget.
4. Semantic similarity still cannot create evidence.
5. AI still cannot create/source missing evidence.
6. No support threshold is weakened.
7. Zero active research is legal.
8. Market Calibration remains `0 / UNVALIDATED` until real market outcomes exist.
9. U29 remains unopened.

## Full-system audit and R2 treatment

| Area | R1/live state | Concrete problem | Shared/root cause | Borrow vs Build | R2 change | Acceptance proof |
|---|---|---|---|---|---|---|
| Crawler / Sources | Multiple source groups; live `jobs`, `problem_sources`, `source_network` showed timeouts in one cycle | Sequential/long waits can make a cycle appear stuck; zero-new-row probes still caused unnecessary downstream attention historically | Source health and source change were conflated | Borrow circuit-breaker/backoff patterns; build SignalForge-specific group policy | Per-group wall-clock caps, degraded-cache legality, shared scraper dedupe; zero row changes do not force Reality rebuild | R2 source-contract checks |
| Discovery feeder | New ProblemCandidates continued entering while active opportunity yield stayed low | New transient bug/configuration observations can trigger retrieval/verifier work | Qualification happened after expensive enrichment | Build SignalForge-specific pre-enrichment admission | Brand-new obvious transient driver/version/model/hardware issues are deferred before external enrichment unless recurrence/buyer/workaround/structural evidence exists; existing candidates are never hidden by this gate | Pure behavior tests + source contract |
| Candidate formation | Candidate was still implicitly close to workload entry | Candidate could inflate into RadarCase + 14 claims too early | Provenance object and production decision object were coupled | Build | New RadarCase creation is admission-gated; deferred Candidate/Posts remain preserved | `radar_ledger` admission checks |
| Evidence | Strong truth contracts existed | Large corpora were repeatedly searched despite low decision yield | Expensive rejection occurred too late | Borrow IR portfolio/diversity idea; preserve evidence semantics | Recurrence retrieval keeps global best matches but adds source-diversity supplements; evidence thresholds unchanged | Critical function hash freeze + R2 checks |
| C01-C14 | Canonical and conservative | No need to lower gates | Not a truth-quality problem | Preserve | No semantic/support threshold changes | Four critical R1 truth functions SHA-frozen; R1 regression 49/49 |
| Research backlog | 168 cases in observed cycle; 166 WATCH | Candidate backlog could imply broad recurrence/materiality work | Workload lacked hard bounded active set | Borrow bounded work-queue scheduling; build SignalForge admission | Max active machine-research case set = 24; recurrence/materiality accept explicit bounded case IDs | R2 acceptance |
| C02 recurrence | 4,900 docs, only 2 supported after observed pass; large UNKNOWN/INSUFFICIENT pool | Re-running exhausted same method on unchanged corpus wastes compute | Search state did not sufficiently gate execution | Borrow VOI / stop-search logic | `SEARCH_EXHAUSTED` / unchanged corpus does not repeat recurrence; fresh problem corpus can reopen | Pure behavior tests |
| C03 materiality | Could be a long silent deterministic phase | User cannot distinguish working from hung | No subphase heartbeat | Build | C03 emits corpus-index and case-progress heartbeats | R2 acceptance |
| Brain v2 | R1 added strategic/addressability layer | Brain relevance could reactivate workload even when Founder is hard-blocked | Objective market relevance and first-person captureability not separated in workload scheduling | Build on R1 third-person/first-person model | `FOUNDER_HARD_BLOCKED_MONITOR_ONLY`; right-to-win REFUTED cannot activate production workload | R2 acceptance |
| Founder Addressability | First-class R1 derived object | Needed actual workload authority boundary | Addressability existed mainly as Founder-facing decision info | Build | Hard block now gates Brain-to-production research advisory only; market truth remains unchanged | R2 static check |
| Research Controller | VOI existed, but production execution still broad | Too much desk research could continue after no-info states | Research plan and runtime queue were not the same authority | Borrow VOI stopping; build routing | `CHANGE_SOURCE_MARKET_ACTION_OR_PARK`, `WAIT_FOR_NEW_SOURCE_COVERAGE`, bounded recurrence/materiality | Behavior checks |
| Zero-active state | Previously risky because no work could tempt filler behavior | Discovery must continue without manufacturing active cases | Discovery and expensive research were coupled | Build | Zero active is legal; when due, only problem feeder source group is refreshed; buyer/market/timing are not fanned out just to stay busy | R2 acceptance |
| API / Runtime status | `/status` knew RUNNING but not meaningful subphase | Founder had to inspect CPU manually | Server health, DB health, cycle state, progress were too coarse | Borrow heartbeat/progress conventions; build SignalForge implementation | Cross-process progress file exposes phase, heartbeat, elapsed, last completed phase, detail, numerator/denominator metrics | R2 acceptance |
| Founder UI | R1 System page truthful but coarse during a live cycle | Long deterministic phase looked frozen | Runtime telemetry absent | Build | System page polls status every 5s and shows phase/heartbeat/progress/admission/pre-enrichment deferrals; global banner shows phase | TS/TSX syntax + install build gate |
| Market Outcome | No completed validation dataset | Cannot claim product-market accuracy | External result constrained | Preserve truth | No market result fabricated | Explicit `0 / UNVALIDATED` |
| Calibration | R1 split Fast / Structural / Addressability | No real outcome yet | External result constrained | Preserve | Infrastructure unchanged; R2 engineering PASS carries zero calibration authority | R1 regression + release docs |

## R2 architecture

```text
External signals / stored Posts
        |
        v
Problem fingerprint / transition discovery
        |
        +--> NEW obvious transient one-off?
        |       |
        |       +--> yes, no recurrence/buyer/workaround/structural signal
        |       |       -> DEFER_PRE_ENRICHMENT_TRANSIENT
        |       |          (keep raw provenance; no external enrichment)
        |       |
        |       +--> no -> bounded external enrichment
        v
ProblemCandidate
        |
        v
Production Admission (compute authority only)
        |
        +--> DEFER_EPHEMERAL / MONITOR_CONTEXT
        |        -> no new RadarCase workload
        |
        +--> RESEARCH_ACTIVE / THESIS_ACTIVE
                 -> RadarCase / existing truth pipeline
                         |
                         v
                bounded active set <= 24
                         |
             +-----------+------------+
             |                        |
             v                        v
       C02 recurrence            C03 materiality
       bounded IDs               bounded IDs
       heartbeats                heartbeats
             |
             v
       Decision-critical later research
             |
             v
       Founder Thesis / Strategic Track
             |
             v
       Market action / outcome / calibration
```

## Source / retrieval policy

R2 does **not** solve low yield by increasing AI calls or lowering thresholds. It instead:

- gates obvious transient new observations before external enrichment;
- bounds expensive C02/C03 work to active cases;
- stops unchanged-corpus repetition after exhausted recurrence search;
- keeps a cheap problem-source feeder alive when active research is zero;
- adds source-diversity supplementation to recurrence retrieval while preserving the original strict evidence gate;
- treats a source probe with zero persisted row changes as source-health evidence, not a reason to rebuild the whole Reality surface.

## Runtime progress contract

`processors/signalforge_runtime_progress.py` is observability-only. It stores:

- cycle id / PID
- cycle start
- phase / phase start
- last heartbeat
- last completed phase
- detail
- progress metrics
- accumulated diagnostic metrics
- final PASS/FAIL

The runtime status endpoint reads this telemetry cross-process. It has **zero** C01-C14 or market-outcome authority.

## Release acceptance at package-build time

- R2 no-DB acceptance: **50/50 PASS**
- R1 Full-System Rebase regression: **49/49 PASS**
- Critical R1 truth-gate function hashes: **unchanged**
- Changed Python source compilation: **PASS**
- Changed TS/TSX syntax transpilation: **PASS**
- Market calibration: **0 / UNVALIDATED**

The install-time hard gates additionally require the real project venv and full dashboard tree:

1. `python run_signalforge_production_focus_r2_acceptance.py`
2. `python run_signalforge_full_system_rebase_acceptance.py`
3. `python run_signalforge_brain_v2_acceptance.py --static-only`
4. `npm run build` in `dashboard/`

No installer gate triggers a live Radar cycle or market action.

## Live acceptance still required after install

R2 is not Product Accepted merely because the installer passes. After installation and backend restart, live acceptance must prove:

- runtime progress actually advances during long phases;
- active research is bounded in the current DB;
- transient new candidates are deferred before enrichment when the live corpus produces them;
- no existing truth/cases are deleted;
- R1 strategic portfolio remains intact;
- production cycle completes without threshold weakening;
- calibration remains unvalidated until external outcomes exist.
