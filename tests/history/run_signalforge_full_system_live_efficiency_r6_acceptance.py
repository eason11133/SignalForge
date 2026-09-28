"""SignalForge R6 no-DB acceptance: full-system live efficiency + strategic freshness.

R6 is a system-wide execution-efficiency / strategic-surface coherence upgrade.
It must not promote market truth. The suite verifies that fresh corpus changes
remain bounded, Founder routing is recomputed after the derived Brain refresh,
and the operating queue separates eligible machine backlog from the selected
execution set without weakening R1-R5 evidence gates.
"""
from __future__ import annotations

import ast
import hashlib
import py_compile
from pathlib import Path

ROOT = Path(__file__).resolve().parent

from processors.signalforge_execution_governor import annotate_execution_routes, machine_rows, operating_queue

FROZEN_FUNCTION_HASHES = {
    ("processors/signalforge_production_admission.py", "assess_candidate_admission"):
        "5559c09a6f3f2facb19a1aa9ae1a86077da167f219510d2c59428e9271b739f5",
    ("processors/signalforge_production_admission.py", "assess_pre_enrichment_discovery"):
        "7306054e54276321c413c54b84b9c73aff8c6645d27cf1430edc1716ef47aee6",
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


def behavior_checks() -> dict[str, bool]:
    base_rows = []
    for i in range(1, 27):
        base_rows.append({
            "case_id": i,
            "candidate_id": i,
            "title": f"case-{i}",
            "decision_verdict": "WATCH",
            "current_gate": "BUYER_REALITY",
            "next_claim": "C05",
            "claims": {"C03": "SUPPORTED", "C05": "UNKNOWN"},
            "production_admission": {"state": "RESEARCH_ACTIVE", "next_route": "DECISION_CRITICAL_RESEARCH"},
            "research_status_by_claim": {"C05": "ACTIVE"},
            "attention_score": 100 - i,
        })
    routed, summary = annotate_execution_routes(base_rows, machine_limit=24)
    queue = operating_queue(routed, limit=100)
    selected = machine_rows(routed, limit=24)
    return {
        "governor_selects_exact_bounded_execution_set": len(selected) == 24 and summary.get("bounded_machine_workload") == 24,
        "governor_preserves_capacity_backlog_without_executing_it": queue.get("counts", {}).get("machine_research_backlog") == 2,
        "operating_queue_machine_research_means_selected_not_all_eligible": queue.get("counts", {}).get("machine_research") == 24,
        "operating_queue_exposes_eligible_total": queue.get("counts", {}).get("machine_research_eligible_total") == 26,
        "capacity_backlog_rows_are_not_selected": all(not bool(x.get("machine_execution_selected")) for x in queue.get("machine_research_backlog", [])),
    }


def source_checks() -> dict[str, bool]:
    reality = text("processors/opportunity_reality.py")
    decision = text("processors/opportunity_decision.py")
    orch = text("processors/research_orchestrator.py")
    runtime = text("processors/signalforge_runtime.py")
    governor = text("processors/signalforge_execution_governor.py")
    audit = text("processors/system_wide_audit.py")
    api = text("api/routes/signalforge.py")
    client = text("dashboard/src/api/client.ts")
    radar = text("dashboard/src/pages/OpportunityRadar.tsx")
    system = text("dashboard/src/pages/System.tsx")
    return {
        "raw_reality_materializer_accepts_explicit_case_scope": "async def run_opportunity_reality(case_ids: list[int] | None = None)" in reality,
        "raw_reality_explicit_zero_is_legal_noop": '"mode": "EXPLICIT_ZERO"' in reality and "if scope_explicit and not normalized_case_ids" in reality,
        "scoped_materializer_filters_radar_cases": "stmt = stmt.where(RadarCase.id.in_(normalized_case_ids))" in reality,
        "scoped_materialization_rebuilds_full_readonly_projection": "scoped_materialization = await run_opportunity_reality" in decision and "reality = await read_persisted_opportunity_reality()" in decision,
        "fresh_corpus_no_longer_forces_full_world_decision_scope": "if raw_reality_refresh_required:\n        return None" not in orch and "return sorted(active | new_ids)" in orch,
        "cold_cycle_profile_is_explicit": '"COLD_CORPUS_OR_DISCOVERY_CHANGE"' in orch and '"WARM_PERSISTED_DECISION"' in orch,
        "decision_subphase_telemetry_persisted": '"subphase_ms": updated.get("phase_ms") or {}' in orch and '"phase_value": cycle.get("phase_value") or {}' in runtime,
        "final_decision_runtime_progress_has_current_total": '"current": max(0, int(current))' in decision and '"unit": "cases"' in decision,
        "unscoped_legacy_structural_classifier_is_not_recomputed": '"PERSISTED_UNSCOPED_COMPATIBILITY"' in decision,
        "brain_refresh_precedes_founder_surface": "brain_refresh = await _refresh_brain_for_founder_surface" in runtime and "building canonical Founder daily surface from post-cycle Brain" in runtime,
        "brain_failure_remains_nonblocking_to_production_truth": "DERIVED_BRAIN_FAILURE_HAS_ZERO_PRODUCTION_TRUTH_AUTHORITY" in runtime,
        "post_brain_operating_routes_are_recomputed": "latest_brain_advisory = safe_brain_research_advisory" in runtime and "POST_BRAIN_ROUTING_CHANGES_WORK_ONLY_NO_C01_C14_AUTHORITY" in runtime,
        "runtime_persists_brain_refresh_and_post_routing": '"brain_refresh": brain_refresh' in runtime and '"post_brain_routing": cycle.get("post_brain_routing") or {}' in runtime,
        "governor_marks_selected_and_capacity_deferred": "machine_execution_selected" in governor and "machine_execution_deferred_by_capacity" in governor,
        "operating_queue_has_separate_capacity_backlog": '"machine_research_backlog"' in governor,
        "api_exposes_founder_strategy_with_operating_queue": "'founder_strategy': snapshot.get('founder_strategy') or {}" in api,
        "ui_exposes_selected_vs_capacity_backlog": "Capacity backlog" in radar and "machine_research_backlog" in client and "machine capacity backlog" in system,
        "system_audit_exposes_cycle_profile_and_brain_freshness": '"cycle_profile"' in audit and '"brain_refresh"' in audit and '"post_brain_routing"' in audit,
        "r6_has_zero_new_market_truth_writer": "market_ground_truth" not in runtime and "RadarClaim" not in governor,
    }


def frozen_checks() -> dict[str, bool]:
    return {
        f"unchanged.{Path(rel).name}.{name}": function_hash(rel, name) == expected
        for (rel, name), expected in FROZEN_FUNCTION_HASHES.items()
    }


def compile_checks() -> dict[str, bool]:
    files = [
        "processors/opportunity_reality.py",
        "processors/opportunity_decision.py",
        "processors/research_orchestrator.py",
        "processors/signalforge_execution_governor.py",
        "processors/signalforge_runtime.py",
        "processors/system_wide_audit.py",
        "api/routes/signalforge.py",
    ]
    out: dict[str, bool] = {}
    for rel in files:
        try:
            py_compile.compile(str(ROOT / rel), doraise=True)
            out[f"compile.{rel}"] = True
        except Exception:
            out[f"compile.{rel}"] = False
    return out


def main() -> int:
    checks: dict[str, bool] = {}
    checks.update({f"behavior.{k}": v for k, v in behavior_checks().items()})
    checks.update({f"source.{k}": v for k, v in source_checks().items()})
    checks.update(frozen_checks())
    checks.update(compile_checks())

    print("=" * 124)
    print("SIGNALFORGE R6 — FULL-SYSTEM LIVE EFFICIENCY + STRATEGIC FRESHNESS — NO-DB ACCEPTANCE")
    print("=" * 124)
    passed = 0
    for key, ok in checks.items():
        print(f"{'PASS' if ok else 'FAIL'}  {key}")
        passed += int(bool(ok))
    total = len(checks)
    print("-" * 124)
    print(f"TOTAL={total} PASS={passed} FAIL={total-passed}")
    print("R6 changes execution scope/freshness/observability only. Market Calibration may validly remain 0 / UNVALIDATED.")
    print("=" * 124)
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
