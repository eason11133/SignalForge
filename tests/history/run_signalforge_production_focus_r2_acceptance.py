"""SignalForge R2 no-DB acceptance: thesis-controlled production funnel.

This suite proves workload/observability changes without claiming market truth.
It intentionally avoids DB/live-network dependencies so it can fail closed in
release install before any live cycle is allowed to run.
"""
from __future__ import annotations

import ast
import hashlib
import py_compile
from pathlib import Path

from processors.signalforge_production_admission import (
    assess_candidate_admission,
    assess_pre_enrichment_discovery,
    annotate_rows,
    static_acceptance as admission_static_acceptance,
)
from processors.signalforge_runtime_progress import static_acceptance as progress_static_acceptance

ROOT = Path(__file__).resolve().parent

CRITICAL_R1_FUNCTION_HASHES = {
    ("processors/problem_recurrence_multi.py", "_semantic_structural_detail"):
        "96f8e8eaf2332659b727a70722a0aa2dfa658c0f01c0637865b3d6fbd694a2c6",
    ("processors/problem_recurrence_multi.py", "_ensure_support_evidence"):
        "a157dad95f846d8b0a9e64d3a0765e50d45f2fe39393945d591811858918c467",
    ("processors/radar_ledger.py", "initial_links"):
        "4ce699ee3899267e450d3777f01d5587cf6b037ab8b285217bd93aeec74705f9",
    ("processors/radar_ledger.py", "evaluate"):
        "3cd46c70a55dd648d70be6bbd53ed977d71d4c043cf45249a4c2860ebb77ba67",
}


def text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def function_hash(rel: str, name: str) -> str:
    source = text(rel)
    tree = ast.parse(source)
    lines = source.splitlines(True)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            segment = "".join(lines[node.lineno - 1:node.end_lineno])
            return hashlib.sha256(segment.encode("utf-8")).hexdigest()
    raise AssertionError(f"function not found: {rel}:{name}")


def check_source_contracts() -> dict[str, bool]:
    admission = text("processors/signalforge_production_admission.py")
    ledger = text("processors/radar_ledger.py")
    discovery = text("processors/problem_discovery_refresh.py")
    candidate_engine = text("processors/problem_candidate_engine.py")
    recurrence = text("processors/problem_recurrence_multi.py")
    materiality = text("processors/materiality_research.py")
    orchestrator = text("processors/research_orchestrator.py")
    runtime = text("processors/signalforge_runtime.py")
    brain_engine = text("processors/signalforge_brain_v2_engine.py")
    system = text("dashboard/src/pages/System.tsx")
    hooks = text("dashboard/src/api/hooks.ts")
    banner = text("dashboard/src/signalforgeFounderRuntimeClosure.ts")

    return {
        "ledger_new_cases_are_admission_gated": (
            "admit_new: bool = True" in ledger
            and 'if not admission.get("ledger_admit_new")' in ledger
            and 'admission_states["NEW_CASE_CREATION_DISABLED"]' in ledger
        ),
        "problem_discovery_migrates_only_processed_or_transition_candidates": (
            "processed_candidate_ids" in discovery
            and 'transition.get("active_candidate_ids")' in discovery
            and "candidate_ids=processed_candidate_ids" in discovery
            and "admit_new=True" in discovery
        ),
        "candidate_engine_exposes_processed_ids": "processed_candidate_ids" in candidate_engine,
        "transient_new_observations_are_deferred_before_external_enrichment": (
            "assess_pre_enrichment_discovery" in candidate_engine
            and "pre_enrichment_deferred" in candidate_engine
            and "pre_enrichment_deferred_reasons" in candidate_engine
            and "pre_enrichment_deferred" in discovery
        ),
        "recurrence_accepts_bounded_case_ids": (
            "case_ids: list[int] | None = None" in recurrence
            and "RadarCase.id.in_(wanted_case_ids)" in recurrence
        ),
        "materiality_accepts_bounded_case_ids": (
            "case_ids: list[int] | None = None" in materiality
            and "RadarCase.id.in_(wanted_case_ids)" in materiality
        ),
        "expensive_c02_c03_phases_emit_heartbeats": (
            "c02 deterministic verification" in recurrence
            and "c02 semantic recall matrix ready" in recurrence
            and "c03 deterministic consequence verification" in materiality
            and "c03 materiality corpus indexed" in materiality
        ),
        "active_workload_is_hard_bounded": (
            "MAX_ACTIVE_RESEARCH_CASES" in orchestrator
            and "return active[:MAX_ACTIVE_RESEARCH_CASES]" in orchestrator
        ),
        "zero_active_keeps_discovery_but_skips_expensive_research": (
            "ZERO_ACTIVE_AFTER_DISCOVERY_LEGAL" in orchestrator
            and "zero_active_projection" in orchestrator
            and 'reality_mode="persisted"' in orchestrator
            and '"NO_RESEARCH_TARGETS"' not in orchestrator
        ),
        "zero_active_still_refreshes_due_problem_feeder_only": (
            'if not active_cycle_rows and _due(state, "problem", force_refresh):' in orchestrator
            and 'source_groups.append("problem")' in orchestrator
            and "do not fan out buyer/market/timing" in orchestrator
        ),
        "search_exhausted_recurrence_is_corpus_change_gated": (
            "problem_corpus_changed = bool(problem_records_changed > 0)" in orchestrator
            and "recurrence_eligible" in admission
            and "CHANGE_SOURCE_MARKET_ACTION_OR_PARK" in admission
        ),
        "source_groups_have_wallclock_circuit_breaker": (
            "GROUP_WALLCLOCK_CAP_SECONDS" in orchestrator
            and "GROUP_TIME_BUDGET_EXHAUSTED" in orchestrator
            and "degraded_cache_fallback_legal" in orchestrator
        ),
        "zero_new_source_rows_do_not_force_reality_rebuild": (
            "records_changed" in orchestrator
            and "any_source_changed = source_records_changed > 0" in orchestrator
            and "if any_source_changed:" in orchestrator
        ),
        "recurrence_retrieval_adds_source_diversity_without_threshold_change": (
            "_balanced_ranked_indices" in recurrence
            and "GLOBAL_TOP_PLUS_SOURCE_DIVERSITY_SUPPLEMENT_NO_THRESHOLD_CHANGE" in recurrence
            and "Semantic similarity alone creates evidence: NO" in recurrence
            and "AI can create/source missing evidence:       NO" in recurrence
            and "Thresholds changed:                          NO" in recurrence
        ),
        "runtime_status_exposes_cross_process_progress": (
            '"progress": runtime_progress.get_progress()' in runtime
            and "runtime_progress.begin_cycle" in runtime
            and 'runtime_progress.finish(\n            status="PASS"' in runtime
            and 'runtime_progress.finish(\n            status="FAIL"' in runtime
        ),
        "system_ui_surfaces_phase_heartbeat_and_admission": (
            'k="current phase"' in system
            and 'k="last heartbeat"' in system
            and 'title="Production workload admission"' in system
            and 'k="pre-enrichment transient deferred"' in system
            and "useSignalForgeStatus" in hooks
            and "refetchInterval: 5_000" in hooks
        ),
        "global_runtime_banner_surfaces_phase": (
            "s.progress?.phase" in banner
            and "SignalForge · ${phase}" in banner
        ),
        "founder_hard_block_cannot_activate_brain_workload": (
            "FOUNDER_HARD_BLOCKED_MONITOR_ONLY" in brain_engine
            and '"founder_hard_block_is_workload_only":True' in brain_engine
            and 'right=="REFUTED"' in brain_engine
        ),
        "admission_has_zero_truth_authority": (
            "WORKLOAD_SCHEDULING_ONLY_NO_C01_C14_WRITE_NO_OPPORTUNITY_PROMOTION" in admission
        ),
    }


def pure_behavior_checks() -> dict[str, bool]:
    weak_transient_even_if_direct = {
        "id": 701,
        "title": "Developer cannot use Foo 3.7 after driver upgrade; downgrading fixes it",
        "problem_statement": "version-specific driver regression",
        "actor": "developer",
        "task": "run Foo",
        "failure_mode": "driver regression",
        "consequence": "tool fails",
        "community_evidence_count": 2,
        "community_user_count": 2,
        "corroboration_score": 72,
        "stage": "corroborated",
        "relation_support": {
            "problem_specificity_score": 88,
            "direct_problem_corroboration": 2,
        },
    }
    transient = assess_candidate_admission(weak_transient_even_if_direct)

    new_transient_discussion = {
        "_incremental_new": True,
        "title": "Consumer facing AMD GPU driver regression fixed by downgrade",
        "fingerprint": {
            "canonical_problem": "AMD GPU software regression after driver version upgrade",
            "failure_mode": "driver regression",
            "consequence": "graphics software fails",
            "buyer_context": "unknown",
            "workaround": "unknown",
        },
        "posts": [{"author": "user1", "title": "driver bug"}],
    }
    pre_transient = assess_pre_enrichment_discovery(new_transient_discussion)
    known_transient_discussion = dict(new_transient_discussion)
    known_transient_discussion["_incremental_new"] = False
    pre_known = assess_pre_enrichment_discovery(known_transient_discussion)
    recurrent_transient_discussion = dict(new_transient_discussion)
    recurrent_transient_discussion["posts"] = [
        {"author": "user1"}, {"author": "user2"}
    ]
    pre_recurrent = assess_pre_enrichment_discovery(recurrent_transient_discussion)

    one_good_observation = {
        "id": 702,
        "title": "Manual intake coordination delays customer payment",
        "problem_statement": "manual workflow creates payment delay",
        "actor": "operations team",
        "task": "inventory intake",
        "failure_mode": "manual coordination bottleneck",
        "consequence": "customer payment delayed",
        "community_evidence_count": 1,
        "community_user_count": 1,
        "stage": "candidate",
        "relation_support": {
            "problem_specificity_score": 82,
            "direct_problem_corroboration": 1,
        },
    }
    one = assess_candidate_admission(one_good_observation)
    brain = assess_candidate_admission(one_good_observation, brain_candidate_ids=[702])

    exhausted = dict(one_good_observation)
    exhausted["community_user_count"] = 2
    ex = assess_candidate_admission(
        exhausted,
        claim_states={"C02": "INSUFFICIENT"},
        c02_research_status="SEARCH_EXHAUSTED",
        corpus_changed=False,
    )
    re = assess_candidate_admission(
        exhausted,
        claim_states={"C02": "INSUFFICIENT"},
        c02_research_status="SEARCH_EXHAUSTED",
        corpus_changed=True,
    )
    _, zero_summary = annotate_rows([], brain_candidate_ids=[])

    return {
        "transient_bug_is_not_admitted_even_when_direct": (
            transient["state"] == "DEFER_EPHEMERAL"
            and transient["ledger_admit_new"] is False
        ),
        "new_transient_bug_is_deferred_before_external_enrichment": (
            pre_transient["state"] == "DEFER_PRE_ENRICHMENT_TRANSIENT"
            and pre_transient["admit_external_enrichment"] is False
        ),
        "existing_candidate_update_is_not_hidden_by_pre_enrichment_gate": (
            pre_known["admit_external_enrichment"] is True
        ),
        "multi_actor_recurrence_reopens_transient_pre_enrichment": (
            pre_recurrent["admit_external_enrichment"] is True
            and pre_recurrent["recurrence_signal"] is True
        ),
        "single_good_observation_can_be_research_worthy_without_case_explosion": (
            one["machine_research_eligible"] is True
            and one["ledger_admit_new"] is False
        ),
        "brain_membership_changes_workload_not_market_truth": (
            brain["state"] == "THESIS_ACTIVE"
            and brain["ledger_admit_new"] is True
            and "NO_C01_C14_WRITE" in brain["truth_boundary"]
        ),
        "search_exhausted_waits_without_new_corpus": (
            ex["recurrence_eligible"] is False
            and ex["next_route"] == "CHANGE_SOURCE_MARKET_ACTION_OR_PARK"
        ),
        "new_problem_corpus_can_reopen_search_exhausted": re["recurrence_eligible"] is True,
        "zero_active_is_legal": (
            zero_summary["active_machine_research"] == 0
            and zero_summary["zero_active_is_legal"] is True
        ),
    }


def gate_integrity_checks() -> dict[str, bool]:
    out = {}
    for (rel, fn), expected in CRITICAL_R1_FUNCTION_HASHES.items():
        out[f"unchanged_gate.{Path(rel).name}.{fn}"] = function_hash(rel, fn) == expected
    return out


def compile_checks() -> dict[str, bool]:
    files = [
        "processors/signalforge_production_admission.py",
        "processors/signalforge_runtime_progress.py",
        "processors/radar_ledger.py",
        "processors/problem_candidate_engine.py",
        "processors/problem_discovery_refresh.py",
        "processors/problem_recurrence_multi.py",
        "processors/materiality_research.py",
        "processors/research_orchestrator.py",
        "processors/signalforge_runtime.py",
        "processors/signalforge_brain_v2_engine.py",
        "processors/signalforge_brain_v2_integration.py",
    ]
    out = {}
    for rel in files:
        try:
            py_compile.compile(str(ROOT / rel), doraise=True)
            out[f"compile.{rel}"] = True
        except Exception:
            out[f"compile.{rel}"] = False
    return out


def main() -> int:
    checks: dict[str, bool] = {}
    for k, v in admission_static_acceptance().items():
        checks[f"admission.{k}"] = bool(v)
    for k, v in progress_static_acceptance().items():
        checks[f"progress.{k}"] = bool(v)
    checks.update({f"behavior.{k}": v for k, v in pure_behavior_checks().items()})
    checks.update({f"source.{k}": v for k, v in check_source_contracts().items()})
    checks.update(gate_integrity_checks())
    checks.update(compile_checks())

    print("=" * 118)
    print("SIGNALFORGE R2 — THESIS-CONTROLLED PRODUCTION FUNNEL + RUNTIME TRUTH — NO-DB ACCEPTANCE")
    print("=" * 118)
    passed = 0
    for name, ok in checks.items():
        print(f"{'PASS' if ok else 'FAIL':4s}  {name}")
        passed += int(ok)
    print("-" * 118)
    print(f"TOTAL={len(checks)} PASS={passed} FAIL={len(checks)-passed}")
    print("Market calibration is intentionally unchanged: engineering/workload acceptance has zero market-outcome authority.")
    print("=" * 118)
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
