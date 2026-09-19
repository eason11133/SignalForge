from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path.cwd().resolve()


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8", errors="strict")


def count_call(tree: ast.AST, name: str) -> int:
    n = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name) and fn.id == name:
                n += 1
            elif isinstance(fn, ast.Attribute) and fn.attr == name:
                n += 1
    return n


def main() -> int:
    main_src = read("api/main.py")
    api_src = read("api/routes/signalforge_brain_v2.py")
    runtime_src = read("processors/signalforge_runtime.py")
    orch_src = read("processors/research_orchestrator.py")
    decision_src = read("processors/opportunity_decision.py")
    integration_src = read("processors/signalforge_brain_v2_integration.py")

    trees = {
        "main": ast.parse(main_src, filename="api/main.py"),
        "api": ast.parse(api_src, filename="api/routes/signalforge_brain_v2.py"),
        "runtime": ast.parse(runtime_src, filename="processors/signalforge_runtime.py"),
        "orchestrator": ast.parse(orch_src, filename="processors/research_orchestrator.py"),
        "decision": ast.parse(decision_src, filename="processors/opportunity_decision.py"),
        "integration": ast.parse(integration_src, filename="processors/signalforge_brain_v2_integration.py"),
    }

    api_post_decorators = []
    for node in ast.walk(trees["api"]):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dec in node.decorator_list:
                if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
                    if dec.func.attr.lower() in {"post", "put", "patch", "delete"}:
                        api_post_decorators.append(dec.func.attr.lower())

    # Lazy API contract: Brain engine/store/runtime are imported inside endpoint functions,
    # never at module import time. The only module-level imports may be stdlib/FastAPI.
    top_level_brain_imports = []
    for node in trees["api"].body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            module = getattr(node, "module", "") or ""
            names = [a.name for a in getattr(node, "names", [])]
            if "signalforge_brain_v2" in module or any("signalforge_brain_v2" in x for x in names):
                top_level_brain_imports.append((module, names))

    checks = {
        "main_brain_router_imported_once": main_src.count("signalforge_brain_v2") >= 2,
        "main_brain_router_mounted_once": main_src.count('prefix="/api/signalforge/brain-v2"') == 1,
        "brain_api_read_only": len(api_post_decorators) == 0,
        "brain_api_lazy_imports": not top_level_brain_imports,
        "brain_api_unavailable_is_nonblocking": "BRAIN_V2_UNAVAILABLE_NON_BLOCKING" in api_src and '"production_impact": "NONE"' in api_src,
        "brain_api_g3_transition_hypothesis_read": '@router.get("/transition-hypothesis/{hypothesis_id}")' in api_src and "get_transition_hypothesis" in api_src,
        "brain_api_g3_bridge_hypothesis_read": '@router.get("/bridge-hypothesis/{hypothesis_id}")' in api_src and "get_structural_bridge_hypothesis" in api_src,
        "runtime_full_system_marker_once": runtime_src.count("SIGNALFORGE_BRAIN_V2_FULL_SYSTEM_DERIVED_RUNTIME_R1") == 1,
        "runtime_launcher_called_once": count_call(trees["runtime"], "launch_brain_v2_refresh_nonblocking") == 1,
        "runtime_no_inline_brain_refresh": "await refresh_signalforge_brain_v2" not in runtime_src and "asyncio.wait_for(refresh_signalforge_brain_v2" not in runtime_src,
        "runtime_production_pass_saved_before_launch": runtime_src.find('_save(state)\n        # SIGNALFORGE_BRAIN_V2_FULL_SYSTEM_DERIVED_RUNTIME_R1') >= 0,
        "runtime_brain_exception_nonblocking": "BRAIN_V2_DERIVED_LAUNCH_FAIL_NON_BLOCKING" in runtime_src,
        "orchestrator_full_system_marker_once": orch_src.count("SIGNALFORGE_BRAIN_V2_FULL_SYSTEM_RESEARCH_ADVISORY_R1") == 1,
        "orchestrator_reads_brain_advisory": "safe_brain_research_advisory" in orch_src,
        "orchestrator_merges_after_blocking_gates": "merge_research_source_priority" in orch_src and "blocking_gate_groups=gate_groups" in orch_src,
        "orchestrator_records_execution_telemetry": "safe_record_brain_research_execution" in orch_src and "brain_research_execution" in orch_src,
        "integration_preserves_production_groups": "if group in prod" in integration_src and "for group in prod" in integration_src,
        "decision_authority_cutover_marker_once": decision_src.count("SIGNALFORGE_BRAIN_V2_FULL_SYSTEM_AUTHORITY_CUTOVER_R1") == 1,
        "legacy_gate_removed": "gate_existing_decision" not in decision_src,
        "legacy_next_gate_override_removed": 'solo_transition.get("next_gate")' not in decision_src,
        "legacy_context_has_no_decision_authority": "LEGACY_CONTEXT_ONLY_NO_DECISION_AUTHORITY" in decision_src and 'solo_transition["decision_authority"] = False' in decision_src,
        "legacy_solo_score_not_sort_authority": "solo_score" not in decision_src[decision_src.find("rows.sort("): decision_src.find("attach_progression_packets")],
        "legacy_solo_not_why_now_authority": 'solo_transition.get("transition_gap")' not in decision_src and 'solo_transition.get("opportunity_structure")' not in decision_src,
        "brain_structural_authority_declared": "BRAIN_V2_DERIVED_PORTFOLIO" in decision_src,
        "no_direct_brain_radar_mutator_in_integration": all(x not in integration_src for x in ("RadarClaim(", "RadarCase(", ".state =", ".system_verdict =")),
        "python_ast_parse_all": True,
    }

    failed = [k for k, v in checks.items() if not v]
    print("=" * 124)
    print("SignalForge Brain v2 — FULL-SYSTEM INTEGRATION ACCEPTANCE")
    print("=" * 124)
    print(json.dumps(checks, ensure_ascii=False, indent=2))
    if failed:
        print("FAILED_CHECKS:", ", ".join(failed))
        print("FINAL_STATUS: SIGNALFORGE_BRAIN_V2_FULL_SYSTEM_INTEGRATION_ACCEPTANCE_FAIL")
        return 2
    print("FINAL_STATUS: SIGNALFORGE_BRAIN_V2_FULL_SYSTEM_INTEGRATION_ACCEPTANCE_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
