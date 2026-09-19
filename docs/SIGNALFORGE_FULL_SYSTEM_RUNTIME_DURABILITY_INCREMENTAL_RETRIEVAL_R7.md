# SignalForge R7 — Full-System Runtime Durability + Exact Incremental Retrieval

## Release intent

R7 is a live-evidence-driven full-system upgrade from the confirmed R6 baseline. It is not a market-truth upgrade and it does not change the C01–C14 evidence gates, admission gates, Brain atomic-truth boundary, or Market Calibration.

The first R6 live cycle reached the final decision progression projection, then failed only when the runtime progress layer attempted to replace `.radar_runtime/signalforge_heartbeat.json.tmp` on Windows. The observed exception was `PermissionError: [WinError 5]` in `signalforge_runtime_progress._write_json -> Path.replace`. This exposed a cross-cutting architectural defect: observability, which has explicitly zero truth authority, was still capable of failing the production cycle.

The same live cycle also showed that the R6 scoped final-decision reduction was working: company/commercial/floor/progression advanced across a bounded 21-case scope in roughly the final minute instead of repeating the R5 413-second full-world final decision. The remaining expensive regions were C02 recurrence retrieval, C05 buyer retrieval, and C06/C07 solution retrieval. R7 therefore closes both the durability defect and the repeated exact-derived retrieval cost in one system-wide round.

## Full-system audit for this round

| Area | R6 live state | Root cause / risk | R7 change | Acceptance |
|---|---|---|---|---|
| Runtime state durability | Production reached finalize but cycle ended FAIL | shared fixed temp path + Windows file-sharing race | unique per-writer temp names + bounded atomic replace retry | concurrent writer behavior test |
| Progress / heartbeat | watchdog and semantic update both wrote same heartbeat temp | observability was accidentally production-fatal | public progress/heartbeat writes are best-effort and error-recording | synthetic PermissionError cannot escape |
| Dispatch receipt | parent/child share durable dispatch file | child observability receipt could still throw | worker receipt update becomes best-effort; initial parent dispatch remains control-plane surface | source/compile regression |
| Success vs attempt truth | failed R6 left `last_cycle` pointing at old successful R5 cycle | last-success and latest-attempt semantics were conflated for diagnosis | `last_attempt_*` and `last_attempt_cycle` added while `last_cycle` remains last-success | status/UI/audit checks |
| C02 recurrence | 22 bounded cases still spent minutes on identical TF-IDF/LSA work | deterministic matrices recomputed when corpus/query set was unchanged | exact matrix cache keyed by every query representation + every direct-problem document text | original algorithms/thresholds frozen; cache is derived only |
| C05 buyer | 6 bounded cases stayed in retrieval for minutes | repeated identical `_match_rows` vectorization | shared exact retrieval cache | cache hit reconstructs current doc metadata; no claim truth cached |
| C06/C07 solution | 5 bounded cases stayed in retrieval for minutes | repeated identical `_match_rows` vectorization | same shared exact retrieval cache | role/threshold/top-k/query/docs are in key |
| Research controller telemetry | expensive phases had wall-clock but no cache explanation | Founder could not tell cold vs warm derived compute | per-phase cache delta + cycle cache diagnostics | R7 acceptance source checks |
| Founder/System UI | success timestamp hid a newer failed attempt | operator could mistake stale successful cycle for latest cycle | display recent attempt status/error separately from last success; display observability health | TS source + local production build hard gate |
| System audit | audit emphasized last successful cycle only | failure evidence could be hidden | audit includes last attempt and telemetry degradation | compile/source acceptance |
| Market action / calibration | still externally outcome constrained | no real market outcomes yet | no fake advancement | remains `0 / UNVALIDATED` |

## Runtime durability architecture

R7 introduces `processors/signalforge_atomic_io.py` as the common durable file primitive for runtime JSON state. Atomic writes now use a unique sibling temp file containing PID, thread ID and UUID. `os.replace` has bounded jittered retry for transient Windows sharing failures. Temp files are cleaned even after failure.

The progress subsystem records telemetry write errors in `.radar_runtime/signalforge_telemetry_errors.jsonl`. A telemetry failure changes `observability_health` to `DEGRADED`; it does **not** promote or refute any claim and it does **not** turn an otherwise valid research cycle into a production failure.

Runtime state and dispatch state also use the shared atomic writer. Worker-side dispatch receipt updates are best-effort because they are observability receipts, not the runtime lease or truth authority.

## Last successful cycle vs last attempted cycle

R7 preserves the semantics:

- `last_success_at` / `last_cycle`: most recent successful production cycle.
- `last_attempt_*` / `last_attempt_cycle`: most recent attempted cycle, including failure diagnostics.

A failed attempt does not overwrite last-success truth. It becomes visible as a separate operational fact.

## Exact derived retrieval reuse

### C02

R7 caches only the exact numeric retrieval matrices produced by the existing C02 lexical + semantic algorithm. The key includes:

- all bounded case abstract representations;
- all exemplar representations;
- all field-query representations;
- all direct-problem document texts;
- cache schema/version.

On cache miss the original TF-IDF, char n-gram, SVD and thresholds execute verbatim. On cache hit the exact matrices are reused. The frozen `_semantic_structural_detail` and `_ensure_support_evidence` functions remain byte-identical.

### C05 / C06 / C07 shared retrieval

`opportunity_reality._match_rows` now has an exact derived retrieval cache. Its key includes role, threshold, top-k, candidate identity/text/anchors, document ordering, document IDs and document texts. The cache stores only doc indices and retrieval metadata, then reconstructs each row from the current in-memory source document. It does not cache `RadarClaim`, `RadarEvidence`, verdicts, evidence links, market actions or Brain objects.

Cache files are bounded/pruned and cache write failures are non-authoritative.

## Truth boundaries unchanged

R7 does not change:

- `signalforge_production_admission.assess_candidate_admission`
- `signalforge_production_admission.assess_pre_enrichment_discovery`
- `problem_recurrence_multi._semantic_structural_detail`
- `problem_recurrence_multi._ensure_support_evidence`
- `radar_ledger.initial_links`
- `radar_ledger.evaluate`

No telemetry/cache module imports the market-ground-truth writer. No cache result can create SUPPORT. Market Calibration remains outcome-owned.

## Engineering acceptance

Assistant environment:

- R7: 37 / 37 PASS
- R6 regression: 37 / 37 PASS
- R5 regression: 73 / 73 PASS
- R4 regression: 31 / 31 PASS
- R3 regression: 28 / 28 PASS
- R2 regression: 50 / 50 PASS
- R1 regression: 49 / 49 PASS
- changed Python compile: PASS
- frozen truth/admission function hashes: PASS

Brain v2 static acceptance cannot run in the assistant sandbox because that environment lacks `asyncpg`. Dashboard production build likewise depends on the user's actual project `node_modules`. The installer therefore keeps both as mandatory local hard gates and rolls back if either fails.

## Live acceptance after installation

R7 live acceptance is not claimed by packaging. A real post-install cycle must prove:

1. no Windows heartbeat/progress PermissionError;
2. the cycle can pass finalization and persist a new `last_success_at`;
3. `last_attempt_status` reflects the new attempt independently;
4. final decision remains scoped rather than full-world;
5. first unchanged warm follow-up cycle can show C02/C05/C06 retrieval cache hits;
6. cache hits do not change C01–C14 states merely because of caching;
7. Market Calibration remains unchanged unless real market outcomes exist.
