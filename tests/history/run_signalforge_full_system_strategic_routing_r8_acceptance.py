"""SignalForge R8 no-DB acceptance: strategic routing coherence + warm-runtime closure.

R8 closes the live R7 contradiction where Brain refreshed successfully and emitted
FOUNDER_DISCOVERY, while the post-Brain Execution Governor saw an unavailable
advisory and kept the same candidate in non-Founder lanes. R8 also makes routing
coherence and cache warmth explicit observability. No check grants C01-C14 or
market-calibration authority.
"""
from __future__ import annotations

import ast
import hashlib
import py_compile
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parent

from processors.signalforge_brain_v2_contracts import normalize_state
from processors.signalforge_execution_governor import (
    route_row,
    strategic_routing_coherence,
)

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


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _load_advisory_builder():
    """Execute only the pure builder from the Brain module (no asyncpg import needed)."""
    source = text("processors/signalforge_brain_v2_engine.py")
    tree = ast.parse(source)
    node = next(
        n for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "build_brain_v2_research_advisory"
    )
    module = ast.Module(body=[node], type_ignores=[])
    ast.fix_missing_locations(module)
    ns: dict[str, Any] = {
        "Any": Any,
        "Mapping": Mapping,
        "clean": _clean,
        "normalize_state": normalize_state,
        "ENGINE_VERSION": "acceptance",
    }
    exec(compile(module, "<r8-advisory-builder>", "exec"), ns)
    return ns["build_brain_v2_research_advisory"]


def _row(cid: int) -> dict[str, Any]:
    return {
        "case_id": cid + 1000,
        "candidate_id": cid,
        "current_gate": "BUYER_REALITY",
        "decision_verdict": "WATCH",
        "market_validation_boundary": "MACHINE_FIRST",
        "production_admission": {"state": "RESEARCH_ACTIVE", "next_route": "DECISION_CRITICAL_RESEARCH"},
        "claims": {"C05": "UNKNOWN"},
        "research_status_by_claim": {},
        "attention_score": 1,
    }


def behavior_checks() -> dict[str, bool]:
    out: dict[str, bool] = {}
    builder = _load_advisory_builder()
    portfolio = {
        "status": "PASS",
        "portfolio": [
            {
                "thesis_id": "t-founder",
                "member_candidate_ids": [259],
                "best_next_action": {"mode": "FOUNDER_DISCOVERY", "action": "IDENTIFY_REACHABLE_BUYER_CHANNEL", "reason": "BUYER_ACCESS_NOT_ESTABLISHED"},
                "founder_addressability": {"hard_blocked": False, "dimensions": {"right_to_win": {"state": "INSUFFICIENT"}}},
            },
            {
                "thesis_id": "t-refuted",
                "member_candidate_ids": [260],
                "best_next_action": {"mode": "MARKET_ACTION", "action": "OUTREACH"},
                "founder_addressability": {"hard_blocked": False, "dimensions": {"right_to_win": {"state": "REFUTED"}}},
            },
        ],
        "research_queue": [
            {"thesis_id": "t-founder", "member_candidate_ids": [259], "voi": 0.8, "source_group": "buyer"},
            {"thesis_id": "t-refuted", "member_candidate_ids": [260], "voi": 0.9, "source_group": "market"},
        ],
    }
    advisory = builder(portfolio, limit=24)
    out["builder_projects_founder_action_without_name_error"] = advisory["candidate_actions"]["259"]["mode"] == "FOUNDER_DISCOVERY"
    out["builder_normalizes_right_to_win"] = advisory["candidate_actions"]["260"]["right_to_win"] == "REFUTED"
    out["founder_action_defers_machine_question_without_becoming_hard_block"] = (
        259 in advisory["deferred_candidate_ids"]
        and advisory["deferred_items"][0]["workload_route"] == "BRAIN_FOUNDER_DISCOVERY_OUTRANKS_MACHINE_RESEARCH"
    )

    founder = route_row(_row(259), brain_advisory=advisory)
    refuted = route_row(_row(260), brain_advisory=advisory)
    out["founder_discovery_outranks_generic_deferred_research"] = founder["route"] == "FOUNDER_DISCOVERY"
    out["right_to_win_refuted_parks_even_if_action_says_market"] = refuted["route"] == "PARK" and "RIGHT_TO_WIN_REFUTED" in refuted["reason_codes"]

    market_adv = {"candidate_actions": {"261": {"mode": "MARKET_ACTION", "action": "OUTREACH", "right_to_win": "SUPPORTED"}}}
    hold_adv = {"candidate_actions": {"262": {"mode": "HOLD", "action": "HOLD", "right_to_win": "PARTIAL"}}}
    out["market_action_outranks_machine"] = route_row(_row(261), brain_advisory=market_adv)["route"] == "MARKET_ACTION"
    out["hold_is_explicitly_parked"] = route_row(_row(262), brain_advisory=hold_adv)["route"] == "PARK"

    routed_rows = []
    for cid, adv in [(259, advisory), (261, market_adv), (262, hold_adv)]:
        row = _row(cid)
        row["execution_route"] = route_row(row, brain_advisory=adv)
        routed_rows.append(row)
    combined = {
        "candidate_actions": {
            **advisory["candidate_actions"],
            **market_adv["candidate_actions"],
            **hold_adv["candidate_actions"],
            "999": {"mode": "FOUNDER_DISCOVERY", "action": "CHANNEL", "right_to_win": "INSUFFICIENT"},
        }
    }
    coherence = strategic_routing_coherence(routed_rows + [{**_row(260), "execution_route": refuted}], brain_advisory=combined)
    out["strategic_coherence_passes_when_routes_match"] = coherence["status"] == "PASS" and coherence["mismatch_count"] == 0
    out["strategic_coherence_reports_thesis_only_without_fabricating_radar_row"] = coherence["thesis_only_or_no_radar_row"] == 1

    bad_rows = [dict(routed_rows[0])]
    bad_rows[0]["execution_route"] = {**bad_rows[0]["execution_route"], "route": "MACHINE_RESEARCH"}
    bad = strategic_routing_coherence(bad_rows, brain_advisory={"candidate_actions": {"259": advisory["candidate_actions"]["259"]}})
    out["strategic_coherence_detects_mismatch"] = bad["status"] == "DEGRADED" and bad["mismatch_count"] == 1
    return out


def source_checks() -> dict[str, bool]:
    brain = text("processors/signalforge_brain_v2_engine.py")
    governor = text("processors/signalforge_execution_governor.py")
    runtime = text("processors/signalforge_runtime.py")
    founder = text("processors/founder_daily_surface.py")
    audit = text("processors/system_wide_audit.py")
    api = text("api/routes/signalforge.py")
    client = text("dashboard/src/api/client.ts")
    radar = text("dashboard/src/pages/OpportunityRadar.tsx")
    system = text("dashboard/src/pages/System.tsx")
    return {
        "brain_imports_normalize_state_explicitly": "    normalize_state," in brain,
        "brain_has_pure_same_snapshot_advisory_builder": "def build_brain_v2_research_advisory" in brain and "return build_brain_v2_research_advisory(get_brain_v2_portfolio(root), limit=limit)" in brain,
        "runtime_uses_same_refresh_advisory_before_fallback": '"SAME_REFRESH_SNAPSHOT"' in runtime and '"PERSISTED_FALLBACK"' in runtime and 'brain_refresh.get("advisory")' in runtime,
        "runtime_telemetry_exposes_advisory_source_and_error": '"brain_advisory_source"' in runtime and '"brain_advisory_error"' in runtime,
        "governor_explicitly_handles_hold_stop_and_refuted": 'brain_mode in {"HOLD", "STOP_OR_PARTNER"}' in governor and 'brain_right_to_win == "REFUTED"' in governor,
        "governor_market_founder_actions_outrank_generic_deferred": "effective_brain_mode == \"MARKET_ACTION\"" in governor and "effective_brain_mode == \"FOUNDER_DISCOVERY\"" in governor,
        "strategic_coherence_is_observability_only": "def strategic_routing_coherence" in governor and "STRATEGIC_ROUTING_COHERENCE_IS_OBSERVABILITY_ONLY" in governor,
        "runtime_publishes_coherence_in_same_cycle": 'cycle["strategic_routing_coherence"]' in runtime and 'final_decision["strategic_routing_coherence"]' in runtime,
        "founder_surface_exposes_coherence": '"strategic_routing_coherence": decision.get("strategic_routing_coherence")' in founder,
        "api_exposes_coherence": "'strategic_routing_coherence': snapshot.get('strategic_routing_coherence')" in api,
        "system_audit_exposes_coherence_and_cache_warmth": '"strategic_routing_coherence"' in audit and '"warm_cache_readiness"' in audit,
        "ui_surfaces_routing_coherence": "Routing {routingCoherence?.status" in radar and 'Panel title="Strategic routing coherence"' in system,
        "client_types_coherence": "SignalForgeStrategicRoutingCoherence" in client,
        "warm_cache_status_does_not_claim_performance": '"performance_claimed": False' in runtime and '"COLD_PRIMED_NO_HITS_YET"' in runtime and '"WARM_HITS_CONFIRMED"' in runtime,
        "r8_adds_no_direct_market_truth_writer": "market_ground_truth" not in governor and "RadarClaim" not in governor,
    }


def frozen_checks() -> dict[str, bool]:
    return {
        f"unchanged.{Path(rel).name}.{name}": function_hash(rel, name) == expected
        for (rel, name), expected in FROZEN_FUNCTION_HASHES.items()
    }


def compile_checks() -> dict[str, bool]:
    files = [
        "processors/signalforge_brain_v2_engine.py",
        "processors/signalforge_execution_governor.py",
        "processors/signalforge_runtime.py",
        "processors/founder_daily_surface.py",
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
    print("=" * 126)
    print("SIGNALFORGE R8 — FULL-SYSTEM STRATEGIC ROUTING COHERENCE + WARM RUNTIME CLOSURE — NO-DB ACCEPTANCE")
    print("=" * 126)
    passed = 0
    for key, ok in checks.items():
        print(f"{'PASS' if ok else 'FAIL'}  {key}")
        passed += int(bool(ok))
    total = len(checks)
    print("-" * 126)
    print(f"TOTAL={total} PASS={passed} FAIL={total-passed}")
    print("R8 aligns Brain strategy with execution routing and reports cache warmth; C01-C14 and Market Calibration remain evidence/outcome-owned.")
    print("=" * 126)
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
