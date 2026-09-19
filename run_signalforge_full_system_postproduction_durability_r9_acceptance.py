"""SignalForge R9 no-DB acceptance: post-production durability + attempt-evidence closure.

R8 live acceptance exposed a runtime-only NameError after production research and
Brain refresh had already advanced: ``Mapping`` was used by warm-cache telemetry
but not imported by ``signalforge_runtime``.  R9 closes the direct symbol defect,
removes telemetry from production-failure authority, and makes both successful
and failed attempts preserve the same diagnostic surfaces needed to validate
Brain -> Governor -> Founder execution routing.

Nothing in this acceptance grants C01-C14, market-result, or calibration authority.
"""
from __future__ import annotations

import ast
import builtins
import hashlib
import py_compile
import symtable
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parent

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


def _runtime_typing_import_names(source: str) -> set[str]:
    names: set[str] = set()
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "typing":
            names.update(alias.asname or alias.name for alias in node.names)
    return names


def _module_defined_names(source: str) -> set[str]:
    tree = ast.parse(source)
    out: set[str] = set(dir(builtins))
    for node in tree.body:
        if isinstance(node, ast.Import):
            out.update((alias.asname or alias.name.split(".")[0]) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            out.update((alias.asname or alias.name) for alias in node.names)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    out.add(target.id)
    return out


def _runtime_global_refs_resolved(source: str, function_names: set[str]) -> bool:
    table = symtable.symtable(source, "signalforge_runtime.py", "exec")
    defined = _module_defined_names(source)
    children = {child.get_name(): child for child in table.get_children()}
    for name in function_names:
        child = children.get(name)
        if child is None:
            return False
        for symbol in child.get_symbols():
            if symbol.is_referenced() and symbol.is_global() and symbol.get_name() not in defined:
                return False
    return True


def _load_runtime_pure_helpers() -> dict[str, Any]:
    """Execute only R9 pure helpers using imports declared by the real module."""
    source = text("processors/signalforge_runtime.py")
    tree = ast.parse(source)
    wanted = {"_warm_cache_readiness", "_safe_warm_cache_readiness", "_attempt_cycle_projection"}
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in wanted]
    if {n.name for n in nodes} != wanted:
        raise AssertionError("R9 runtime pure helper set is incomplete")
    module = ast.Module(body=nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    ns: dict[str, Any] = {"Any": Any}
    typing_names = _runtime_typing_import_names(source)
    if "Mapping" in typing_names:
        ns["Mapping"] = Mapping
    exec(compile(module, "<r9-runtime-pure-helpers>", "exec"), ns)
    return ns


def behavior_checks() -> dict[str, bool]:
    out: dict[str, bool] = {}
    ns = _load_runtime_pure_helpers()
    direct = ns["_warm_cache_readiness"]
    safe = ns["_safe_warm_cache_readiness"]
    project = ns["_attempt_cycle_projection"]

    cycle = {
        "phase_seconds": {"total_cycle": 480.0},
        "phase_value": {"c02_recurrence": {"retrieval_cache": {"hit": True}}},
        "cycle_profile": {"retrieval_cache": {"hits": 2, "misses": 1, "writes": 1}},
        "production_admission": {"bounded_active_workload": 16},
        "execution_governor": {"route_counts": {"FOUNDER_DISCOVERY": 1}},
        "operating_queue": {"counts": {"founder_discovery": 1}},
        "post_brain_routing": {"brain_advisory_source": "SAME_REFRESH_SNAPSHOT"},
        "strategic_routing_coherence": {"status": "PASS", "mismatch_count": 0},
        "final": {"reality_mode": "persisted"},
    }
    warm = direct(cycle)
    out["direct_warm_cache_projection_executes_with_real_typing_imports"] = warm["status"] == "WARM_HITS_CONFIRMED"
    out["warm_cache_projection_never_claims_speedup"] = warm["performance_claimed"] is False

    original = ns["_warm_cache_readiness"]
    ns["_warm_cache_readiness"] = lambda _cycle: (_ for _ in ()).throw(NameError("simulated telemetry symbol defect"))
    degraded = safe(cycle)
    ns["_warm_cache_readiness"] = original
    out["telemetry_projection_failure_is_non_blocking"] = (
        degraded["status"] == "DEGRADED_OBSERVABILITY_NON_BLOCKING"
        and degraded["production_impact"] == "NONE"
        and "NameError" in degraded["error"]
    )

    projected = project(cycle, brain_refresh={"status": "PASS", "advisory": {"status": "PASS"}})
    out["attempt_projection_keeps_phase_profile"] = projected["phase_seconds"]["total_cycle"] == 480.0 and projected["cycle_profile"]["retrieval_cache"]["hits"] == 2
    out["attempt_projection_keeps_brain_and_routing"] = projected["brain_refresh"]["status"] == "PASS" and projected["post_brain_routing"]["brain_advisory_source"] == "SAME_REFRESH_SNAPSHOT"
    out["attempt_projection_keeps_coherence_and_cache"] = projected["strategic_routing_coherence"]["status"] == "PASS" and projected["warm_cache_readiness"] == {}
    out["attempt_projection_keeps_final_reality_mode"] = projected["final_reality_mode"] == "persisted"
    return out


def source_checks() -> dict[str, bool]:
    runtime = text("processors/signalforge_runtime.py")
    audit = text("processors/system_wide_audit.py")
    api = text("api/routes/signalforge.py")
    return {
        "runtime_imports_mapping_for_runtime_isinstance": "from typing import Any, Mapping" in runtime,
        "r8_runtime_global_refs_now_resolve": _runtime_global_refs_resolved(
            runtime,
            {"_warm_cache_readiness", "_safe_warm_cache_readiness", "_attempt_cycle_projection"},
        ),
        "warm_cache_projection_is_guarded": 'cycle["warm_cache_readiness"] = _safe_warm_cache_readiness(cycle)' in runtime,
        "partial_cycle_initialized_before_production_try": 'cycle: dict[str, Any] = {}' in runtime and 'brain_refresh: dict[str, Any] = {}' in runtime,
        "pass_attempt_uses_common_projection": '"status": "PASS",\n                **_attempt_cycle_projection(cycle, brain_refresh=brain_refresh),' in runtime,
        "fail_attempt_uses_common_projection": '"status": "FAIL",\n                "failed_phase": progress_snapshot.get("phase")' in runtime and '**_attempt_cycle_projection(cycle, brain_refresh=brain_refresh)' in runtime,
        "last_success_persists_strategic_coherence": '"strategic_routing_coherence": cycle.get("strategic_routing_coherence") or {}' in runtime,
        "last_success_persists_warm_cache_readiness": '"warm_cache_readiness": cycle.get("warm_cache_readiness") or {}' in runtime,
        "system_audit_separates_last_attempt_brain": '"last_attempt_brain_refresh"' in audit,
        "system_audit_separates_last_attempt_routing": '"last_attempt_post_brain_routing"' in audit and '"last_attempt_strategic_routing_coherence"' in audit,
        "system_audit_separates_last_attempt_cache": '"last_attempt_warm_cache_readiness"' in audit,
        "api_has_compact_live_acceptance_summary": "@router.get('/live-acceptance')" in api and "engineering_live_gate" in api,
        "api_live_acceptance_does_not_claim_market_accuracy": "market_calibration_claimed': False" in api and "ENGINEERING_EXECUTION_EVIDENCE_ONLY" in api,
        "r9_does_not_add_direct_market_truth_writer": "market_ground_truth" not in runtime and "RadarClaim" not in runtime,
    }


def compile_checks() -> dict[str, bool]:
    out: dict[str, bool] = {}
    for rel in [
        "processors/signalforge_runtime.py",
        "processors/system_wide_audit.py",
        "api/routes/signalforge.py",
    ]:
        try:
            py_compile.compile(str(ROOT / rel), doraise=True)
            out[rel] = True
        except Exception:
            out[rel] = False
    return out


def main() -> int:
    checks: dict[str, bool] = {}
    for key, ok in behavior_checks().items():
        checks[f"behavior.{key}"] = ok
    for key, ok in source_checks().items():
        checks[f"source.{key}"] = ok
    for (rel, name), expected in FROZEN_FUNCTION_HASHES.items():
        checks[f"unchanged.{Path(rel).name}.{name}"] = function_hash(rel, name) == expected
    for rel, ok in compile_checks().items():
        checks[f"compile.{rel}"] = ok

    print("=" * 126)
    print("SIGNALFORGE R9 — FULL-SYSTEM POST-PRODUCTION DURABILITY + ATTEMPT-EVIDENCE CLOSURE — NO-DB ACCEPTANCE")
    print("=" * 126)
    for name, ok in checks.items():
        print(f"{'PASS' if ok else 'FAIL':4}  {name}")
    passed = sum(1 for ok in checks.values() if ok)
    failed = len(checks) - passed
    print("-" * 126)
    print(f"TOTAL={len(checks)} PASS={passed} FAIL={failed}")
    print("R9 prevents observability-only projections from killing production and preserves post-Brain live evidence on both PASS and FAIL attempts.")
    print("C01-C14 and Market Calibration remain evidence/outcome-owned.")
    print("=" * 126)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
