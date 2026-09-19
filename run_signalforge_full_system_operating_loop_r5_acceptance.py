"""SignalForge R5 no-DB acceptance: full-system opportunity operating loop.

R5 is a system-wide execution/validation upgrade, not a market-truth promotion.
It verifies that discovery, machine research, Brain strategy, Founder actions,
calibration readiness, UI workflow and incremental reducers remain connected
without weakening R1-R4 truth gates.
"""
from __future__ import annotations

import ast
import hashlib
import py_compile
from pathlib import Path

ROOT = Path(__file__).resolve().parent

from processors.signalforge_execution_governor import static_acceptance as governor_acceptance
from processors.signalforge_discovery_portfolio import static_acceptance as discovery_acceptance
from processors.signalforge_market_action_registry import (
    market_action_outcome_quality,
    static_acceptance as market_action_acceptance,
)
from processors.signalforge_calibration_domains import static_acceptance as calibration_acceptance
from processors.signalforge_validation_workflow import static_acceptance as validation_workflow_acceptance

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


def module_contracts() -> dict[str, bool]:
    out: dict[str, bool] = {}
    for prefix, fn in (
        ("governor", governor_acceptance),
        ("discovery", discovery_acceptance),
        ("market_action", market_action_acceptance),
        ("calibration", calibration_acceptance),
        ("validation_workflow", validation_workflow_acceptance),
    ):
        try:
            for k, v in fn().items():
                out[f"{prefix}.{k}"] = bool(v)
        except Exception:
            out[f"{prefix}.static_acceptance_executes"] = False
    return out


def source_contracts() -> dict[str, bool]:
    orch = text("processors/research_orchestrator.py")
    decision = text("processors/opportunity_decision.py")
    company = text("processors/company_reality.py")
    commercial = text("processors/commercial_reality.py")
    floor60 = text("processors/floor60_reality.py")
    brain = text("processors/signalforge_brain_v2_engine.py")
    discovery = text("processors/problem_candidate_engine.py")
    api = text("api/routes/signalforge.py")
    radar = text("dashboard/src/pages/OpportunityRadar.tsx")
    system = text("dashboard/src/pages/System.tsx")
    market_registry = text("processors/signalforge_market_action_registry.py")
    calibration = text("processors/signalforge_calibration_domains.py")
    validation_workflow = text("processors/signalforge_validation_workflow.py")
    founder_daily = text("processors/founder_daily_surface.py")

    return {
        "execution_governor_is_canonical_machine_universe": (
            "annotate_execution_routes" in orch
            and "governed = machine_rows(rows, limit=MAX_ACTIVE_RESEARCH_CASES)" in orch
            and 'out["execution_governor"] = governor' in orch
            and 'out["operating_queue"] = operating_queue(rows, limit=100)' in orch
        ),
        "brain_nonresearch_action_outranks_machine_queue": (
            'non_research_modes={"MARKET_ACTION","FOUNDER_DISCOVERY","HOLD","STOP_OR_PARTNER"}' in brain
            and "candidate_actions" in brain
            and "BRAIN_" in brain
        ),
        "discovery_portfolio_precedes_expensive_enrichment": (
            "select_enrichment_portfolio" in discovery
            and '"discovery_portfolio"' in discovery
        ),
        "all_expensive_lanes_share_bounded_active_rows": (
            "post_discovery_active_rows = _active_workload_rows" in orch
            and "buyer_prefetch = _claim_prefetch_rows(\n            post_discovery_active_rows," in orch
            and "for row in post_discovery_active_rows" in orch
            and "parallel_targets = _parallel_reality_targets(current" in orch
        ),
        "explicit_empty_scope_never_means_full_universe": (
            "scope_explicit = case_ids is not None" in decision
            and "case_ids=scope_ids if scope_explicit else None" in decision
            and '"EXPLICIT_ZERO"' in decision
            and "if case_ids is not None:" in company
            and "if case_ids is not None:" in commercial
            and "if case_ids is not None:" in floor60
            and "scope_is_explicit = decision_scope is not None" in orch
        ),
        "zero_active_uses_canonical_persisted_zero_scope": (
            'reality_mode="persisted"' in orch
            and "case_ids=[]" in orch
            and '"ZERO_ACTIVE_AFTER_DISCOVERY_LEGAL"' in orch
        ),
        "market_actions_are_api_operable": (
            "@router.get('/operating-queue')" in api
            and "@router.get('/market-actions')" in api
            and "@router.post('/market-actions/register')" in api
            and "@router.post('/market-actions/{action_id}/complete')" in api
        ),
        "founder_ui_surfaces_operating_lanes_and_action_execution": (
            "Founder operating loop" in radar
            and "Machine research" in radar
            and "Market action" in radar
            and "Founder discovery" in radar
            and "MarketActionExecutionCard" in radar
            and "useCompleteSignalForgeMarketAction" in radar
            and 'title="Production workload admission"' in system
        ),
        "recorded_pass_fail_is_not_automatically_calibration_truth": (
            "market_action_outcome_quality" in market_registry
            and "OBSERVED_SAMPLE_BELOW_PREREGISTERED_TARGET" in market_registry
            and "NO_DURABLE_OBSERVATION_REFERENCE" in market_registry
            and "eligible_domains" in market_registry
            and '"FAST_VALIDATION" in eligible_domains' in calibration
        ),
        "founder_discovery_cannot_validate_fast_market_behavior": (
            'elif category == "FOUNDER_DISCOVERY"' in market_registry
            and 'eligible_domains.append("FOUNDER_ADDRESSABILITY")' in market_registry
            and '"FAST_VALIDATION" in eligible_domains and track in {"FAST_VALIDATION", "BOTH"}' in calibration
        ),
        "market_action_completion_still_has_no_direct_atomic_write": (
            "THESIS_ACTION_OUTCOME_NEVER_BYPASSES_CLAIM_SPECIFIC_PREREGISTRATION" in market_registry
            and "ready_for_direct_atomic_write\": False" in market_registry
        ),
        "completed_thesis_action_cannot_be_retroactively_promoted_to_atomic_truth": (
            "PREREGISTERED_BEFORE_THIS_OUTCOME" in market_registry
            and '"ready_for_direct_atomic_write": False' in market_registry
        ),
        "claim_validation_api_uses_quality_locked_existing_path": (
            "@router.get('/validation-experiments')" in api
            and "@router.post('/validation-experiments/register')" in api
            and "@router.post('/validation-experiments/{experiment_id}/record-result')" in api
            and "record_claim_validation_outcome" in api
            and "record_market_result(" in validation_workflow
        ),
        "founder_ui_can_preregister_and_record_atomic_market_experiments": (
            "Atomic market truth experiments" in radar
            and "ClaimValidationReadyCard" in radar
            and "ClaimValidationExecutionCard" in radar
            and "useRegisterSignalForgeValidationExperiment" in radar
            and "useRecordSignalForgeValidationResult" in radar
            and "claim_validation_ready" in founder_daily
        ),
    }


def behavior_contracts() -> dict[str, bool]:
    empty = market_action_outcome_quality({
        "status": "COMPLETED", "result": "PASS", "category": "MARKET_ACTION",
        "action_type": "OUTREACH", "sample_target": 5,
        "pretest_snapshot": {"thesis_id": "t1"}, "observations": {},
    })
    good_market = market_action_outcome_quality({
        "status": "COMPLETED", "result": "PASS", "category": "MARKET_ACTION",
        "action_type": "OUTREACH", "sample_target": 2,
        "pretest_snapshot": {"thesis_id": "t1"},
        "observations": {
            "observed_sample_size": 2,
            "actor_labels": ["Buyer A", "Buyer B"],
            "evidence_refs": ["note:1", "note:2"],
            "observed_behavior": "two qualified replies",
        },
    })
    good_founder = market_action_outcome_quality({
        "status": "COMPLETED", "result": "PASS", "category": "FOUNDER_DISCOVERY",
        "action_type": "DOMAIN_EXPERT_OR_PRACTITIONER_INTERVIEW", "sample_target": 1,
        "pretest_snapshot": {"thesis_id": "t1"},
        "observations": {
            "observed_sample_size": 1,
            "actor_labels": ["Expert A"],
            "evidence_refs": ["interview:1"],
            "decision_relevant_findings": "trust burden clarified",
        },
    })
    return {
        "empty_subjective_pass_is_rejected_for_calibration": not empty.get("eligible"),
        "qualified_market_observation_can_enter_fast_and_addressability_calibration": set(good_market.get("eligible_domains") or []) == {"FAST_VALIDATION", "FOUNDER_ADDRESSABILITY"},
        "qualified_founder_discovery_enters_addressability_only": set(good_founder.get("eligible_domains") or []) == {"FOUNDER_ADDRESSABILITY"},
    }


def frozen_gate_checks() -> dict[str, bool]:
    return {
        f"unchanged.{Path(rel).name}.{name}": function_hash(rel, name) == expected
        for (rel, name), expected in FROZEN_FUNCTION_HASHES.items()
    }


def compile_checks() -> dict[str, bool]:
    files = [
        "processors/signalforge_execution_governor.py",
        "processors/signalforge_discovery_portfolio.py",
        "processors/signalforge_market_action_registry.py",
        "processors/signalforge_calibration_domains.py",
        "processors/signalforge_validation_workflow.py",
        "processors/problem_candidate_engine.py",
        "processors/problem_discovery_refresh.py",
        "processors/research_controller.py",
        "processors/signalforge_brain_v2_engine.py",
        "processors/signalforge_brain_v2_integration.py",
        "processors/research_orchestrator.py",
        "processors/company_reality.py",
        "processors/commercial_reality.py",
        "processors/floor60_reality.py",
        "processors/opportunity_decision.py",
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
    checks.update({f"module.{k}": v for k, v in module_contracts().items()})
    checks.update({f"source.{k}": v for k, v in source_contracts().items()})
    checks.update({f"behavior.{k}": v for k, v in behavior_contracts().items()})
    checks.update(frozen_gate_checks())
    checks.update(compile_checks())

    print("=" * 122)
    print("SIGNALFORGE R5 — FULL-SYSTEM OPPORTUNITY OPERATING LOOP — NO-DB ACCEPTANCE")
    print("=" * 122)
    passed = 0
    for name, ok in checks.items():
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
        passed += int(ok)
    failed = len(checks) - passed
    print("-" * 122)
    print(f"TOTAL={len(checks)} PASS={passed} FAIL={failed}")
    print("R5 advances execution readiness; real market calibration remains outcome-dependent and may validly remain 0 / UNVALIDATED.")
    print("=" * 122)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
