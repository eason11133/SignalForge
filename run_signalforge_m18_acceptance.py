from __future__ import annotations

import ast
import asyncio
import builtins
import inspect
import json
import py_compile
import symtable
import tempfile
from pathlib import Path

PYTHON_FILES = [
    "api/main.py",
    "api/routes/signalforge.py",
    "processors/signalforge_runtime.py",
    "processors/system_wide_audit.py",
    "show_signalforge_full_system_audit.py",
    "run_radar_cycle.py",
    "processors/research_orchestrator.py",
    "processors/opportunity_reality.py",
    "processors/opportunity_decision.py",
    "processors/company_reality.py",
    "processors/commercial_reality.py",
    "processors/materiality_research.py",
    "processors/solution_gap_research.py",
    "processors/founder_daily_surface.py",
    "run_signalforge_m18_acceptance.py",
]


def _defined(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    def target(node: ast.AST) -> None:
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, (ast.Tuple, ast.List)):
            for item in node.elts:
                target(item)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name != "*":
                    names.add(alias.asname or alias.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                target(t)
        elif isinstance(node, ast.AnnAssign):
            target(node.target)
    return names


def undefined_globals(path: Path) -> list[str]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    defined = _defined(tree)
    builtin_names = set(dir(builtins))
    table = symtable.symtable(source, str(path), "exec")
    unresolved: set[str] = set()
    def walk(scope) -> None:
        for child in scope.get_children():
            for symbol in child.get_symbols():
                if not (symbol.is_referenced() and symbol.is_global()):
                    continue
                name = symbol.get_name()
                if name == "__file__" or name in defined or name in builtin_names:
                    continue
                unresolved.add(name)
            walk(child)
    walk(table)
    return sorted(unresolved)


def static_contract_check() -> dict:
    root = Path.cwd()
    unresolved = {}
    for rel in PYTHON_FILES:
        path = root / rel
        py_compile.compile(str(path), doraise=True)
        names = undefined_globals(path)
        if names:
            unresolved[rel] = names
    if unresolved:
        raise AssertionError(f"undefined globals: {unresolved}")

    runtime = (root / "processors/signalforge_runtime.py").read_text(encoding="utf-8")
    orch = (root / "processors/research_orchestrator.py").read_text(encoding="utf-8")
    reality = (root / "processors/opportunity_reality.py").read_text(encoding="utf-8")
    decision = (root / "processors/opportunity_decision.py").read_text(encoding="utf-8")
    materiality = (root / "processors/materiality_research.py").read_text(encoding="utf-8")
    solution = (root / "processors/solution_gap_research.py").read_text(encoding="utf-8")
    company = (root / "processors/company_reality.py").read_text(encoding="utf-8")
    commercial = (root / "processors/commercial_reality.py").read_text(encoding="utf-8")
    route = (root / "api/routes/signalforge.py").read_text(encoding="utf-8")
    audit = (root / "processors/system_wide_audit.py").read_text(encoding="utf-8")
    founder = (root / "processors/founder_daily_surface.py").read_text(encoding="utf-8")

    required = {
        "runtime": [
            "signalforge-runtime-v5-operational-published-truth",
            "UPGRADE_GUARD_PATH",
            "INTERRUPTED",
            'decision=cycle.get("final") or None',
            '"solution_gap": {',
            '"c07_same_cycle_evaluated":',
            '"final_reality_mode":',
        ],
        "orch": [
            "auto-research-orchestrator-v23-m18-operational-cutover",
            "raw_reality_refresh_required",
            '"materialize" if raw_reality_refresh_required else "persisted"',
            "solution_allowance = min(",
            "5 if advanced_count else 0",
        ],
        "reality": [
            "opportunity-reality-v7-persisted-final-snapshot",
            "read_persisted_opportunity_reality",
            "PERSISTED_EVIDENCE_SNAPSHOT",
            "RadarResearchAction",
        ],
        "decision": [
            "opportunity-decision-v17-persisted-reality-mode",
            'reality_mode: str = "materialize"',
            'mode not in {"materialize", "persisted"}',
        ],
        "materiality": [
            "materiality-research-v3-precomputed-structural-index",
            "_candidate_features",
            "_document_features",
            "_same_problem_from_features",
            "_material_support_from_features",
        ],
        "solution": [
            "solution-allocation-v2-two-family-completion",
            "_cached_same_families",
            "_validate_cached_same_problem",
            "c07_same_cycle_supported",
            "c07_same_cycle_evaluated",
            "persistent_rows",
        ],
        "company": [
            "company-reality-v5-batched-ledger",
            "_prime_reality_session_caches",
            "claim_ids=[int(c.id) for c in claims]",
        ],
        "commercial": [
            "commercial-reality-v6-batched-ledger",
            "_prime_reality_session_caches",
            "_refresh_claim_state_cached",
            "target_claim_ids",
        ],
        "route": ["_load_published_daily", "NO_PUBLISHED_SNAPSHOT"],
        "audit": ["deferred_while_cycle_running", "Unpublished DB truth is intentionally hidden"],
        "founder": ["decision: dict[str, Any] | None = None"],
    }
    sources = {
        "runtime": runtime, "orch": orch, "reality": reality,
        "decision": decision, "materiality": materiality, "solution": solution,
        "company": company, "commercial": commercial,
        "route": route, "audit": audit, "founder": founder,
    }
    for group, markers in required.items():
        for marker in markers:
            if marker not in sources[group]:
                raise AssertionError(f"missing {group} marker: {marker}")

    if "build_founder_daily_surface" in route:
        raise AssertionError("GET /daily still recomputes mutable DB truth")
    if 'updated = await run_opportunity_decision(\n            limit=50, reality_mode=final_reality_mode\n        )' not in orch:
        raise AssertionError("final Decision is not using the explicit reality mode")
    if orch.count("updated = await run_opportunity_decision(") != 1:
        raise AssertionError("normal cycle no longer has exactly one final Decision rebuild")
    return {"python_files": len(PYTHON_FILES), "undefined_globals": 0}


def materiality_equivalence_check() -> dict:
    from database.connection import ProblemCandidate
    from processors.materiality_research import (
        _same_problem_structural,
        _candidate_features,
        _document_features,
        _same_problem_from_features,
        _material_support_from_features,
    )
    from processors.opportunity_reality import _material_consequence_support

    candidate = ProblemCandidate(
        title="AI model output is unreliable under load",
        problem_statement="AI model produces unreliable output under concurrent load",
        actor="AI application developer",
        task="serve model output under concurrent requests",
        object="AI model output",
        failure_mode="unreliable output under load",
        consequence="2 hours debugging delay",
        buyer_context="engineering team",
        workaround="manual retries",
    )
    docs = [
        {"text": "AI model output fails under concurrent load and causes 2 hours debugging delay and manual workaround."},
        {"text": "Salesforce login authentication fails and causes 2 hours debugging delay."},
        {"text": "AI model output under load is unreliable but no concrete consequence is stated."},
    ]
    cf = _candidate_features(candidate)
    checked = 0
    for doc in docs:
        slow_same, slow_detail = _same_problem_structural(candidate, doc)
        df = _document_features(doc)
        fast_same, fast_detail = _same_problem_from_features(cf, df)
        if (slow_same, slow_detail) != (fast_same, fast_detail):
            raise AssertionError("precomputed C03 structural gate changed truth")
        if _material_consequence_support("", doc["text"]):
            old_material = _material_consequence_support(candidate.consequence, doc["text"])
            new_material = _material_support_from_features(cf["consequence_terms"], df)
            if old_material != new_material:
                raise AssertionError("precomputed C03 consequence gate changed truth")
        checked += 1
    return {"fixtures": checked, "truth_equivalent": True}


def solution_allocation_check() -> dict:
    from database.connection import RadarClaim
    from processors.solution_gap_research import (
        ALLOCATION_VERSION,
        _cached_same_families,
        _validate_cached_same_problem,
    )
    claim = RadarClaim(evidence_summary={
        "same_problem_pairs_v3": {
            "a": {
                "validation": "OK",
                "source_family": "community:deepseek",
                "result": {
                    "verdict": "SAME_PROBLEM",
                    "evidence_ids": ["CASE_4", "EVIDENCE_1"],
                },
            },
            "b": {
                "validation": "OK",
                "source_family": "github:other",
                "result": {
                    "verdict": "DIFFERENT_PROBLEM",
                    "evidence_ids": ["CASE_4", "EVIDENCE_2"],
                },
            },
        }
    })
    if _cached_same_families(claim) != {"community:deepseek"}:
        raise AssertionError("near-closure C06 cache priority is wrong")
    obj = {"verdict": "SAME_PROBLEM", "evidence_ids": ["CASE_4", "EVIDENCE_7"]}
    ok, reason = _validate_cached_same_problem(
        obj, case_id=4, current_evidence_id="EVIDENCE_2"
    )
    if not ok or obj.get("evidence_ids") != ["CASE_4", "EVIDENCE_2"]:
        raise AssertionError(f"rank-stable pair cache failed: {reason}")
    if ALLOCATION_VERSION != "solution-allocation-v2-two-family-completion":
        raise AssertionError("wrong C06 allocation contract")
    return {"two_family_completion": True, "rank_stable_cache": True}


def decision_mode_check() -> dict:
    from processors.opportunity_decision import run_opportunity_decision
    sig = inspect.signature(run_opportunity_decision)
    if "reality_mode" not in sig.parameters:
        raise AssertionError("Decision missing persisted reality mode")
    if sig.parameters["reality_mode"].default != "materialize":
        raise AssertionError("public Decision default must stay full materialization")
    return {"public_default": "materialize", "cycle_fast_mode": "persisted"}


def _load_runtime_isolated():
    import importlib.util
    import sys
    import types
    saved = {name: sys.modules.get(name) for name in (
        "processors.research_orchestrator",
        "processors.founder_daily_surface",
        "processors.historical_replay",
    )}
    try:
        research = types.ModuleType("processors.research_orchestrator")
        async def _never_cycle(*args, **kwargs):
            raise AssertionError("guard test unexpectedly entered a research cycle")
        research.run_research_cycle = _never_cycle
        research.print_research_cycle = _never_cycle
        sys.modules[research.__name__] = research
        founder = types.ModuleType("processors.founder_daily_surface")
        founder.build_founder_daily_surface = _never_cycle
        sys.modules[founder.__name__] = founder
        replay = types.ModuleType("processors.historical_replay")
        replay.capture_forward_policy_snapshot = _never_cycle
        sys.modules[replay.__name__] = replay
        spec = importlib.util.spec_from_file_location(
            "_signalforge_runtime_m18_acceptance",
            Path("processors/signalforge_runtime.py"),
        )
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        return module
    finally:
        for name, old in saved.items():
            if old is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old


async def runtime_barrier_behavior_check() -> dict:
    runtime = _load_runtime_isolated()
    with tempfile.TemporaryDirectory(prefix="signalforge_m18_") as td:
        base = Path(td)
        runtime.STATE_PATH = base / "state.json"
        runtime.LEASE_PATH = base / "lease.json"
        runtime.UPGRADE_GUARD_PATH = base / "guard.json"
        runtime.STATE_PATH.write_text(
            json.dumps({"status": "RUNNING", "last_success_at": None}),
            encoding="utf-8",
        )
        status = runtime.get_signalforge_runtime_status()
        if status.get("status") != "INTERRUPTED" or status.get("running"):
            raise AssertionError(f"stale RUNNING state not normalized: {status}")
        from datetime import timedelta
        runtime.UPGRADE_GUARD_PATH.write_text(json.dumps({
            "reason": "m18_acceptance",
            "expires_at": (runtime._utcnow() + timedelta(minutes=5)).isoformat(),
        }), encoding="utf-8")
        guarded = await runtime.run_signalforge_if_stale(force=False, reason="startup_catchup")
        if not guarded.get("skipped") or guarded.get("skip_reason") != "UPGRADE_GUARD":
            raise AssertionError(f"startup guard failed: {guarded}")
        if runtime.LEASE_PATH.exists():
            raise AssertionError("guarded startup acquired a mutation lease")
        runtime._clear_upgrade_guard()
    return {"published_truth_barrier": True}


async def main() -> None:
    print("=" * 126)
    print("SIGNALFORGE M18 OPERATIONAL CUTOVER ACCEPTANCE")
    print("=" * 126)
    print("No crawler. No full recurrence. No LLM. No DB mutation. No threshold weakening.")
    print()
    static = static_contract_check()
    materiality = materiality_equivalence_check()
    solution = solution_allocation_check()
    decision = decision_mode_check()
    barrier = await runtime_barrier_behavior_check()
    print(f"STATIC Python={static['python_files']} undefined_globals={static['undefined_globals']}")
    print(f"C03 FAST PATH status=PASS truth_equivalent={materiality['truth_equivalent']} fixtures={materiality['fixtures']}")
    print("C06/C07 DEPTH status=PASS two_family_completion=YES rank_stable_cache=YES same_cycle_C07=PRESERVED")
    print("FINAL DECISION status=PASS normal_cycle=PERSISTED_EVIDENCE raw_source_change=MATERIALIZE_ONCE ledger_point_queries=BATCHED")
    print("PUBLISHED TRUTH status=PASS reload_barrier=PRESERVED")
    print()
    print("SIGNALFORGE_M18_ACCEPTANCE_PASS")
    print("Next: one real Radar cycle, full audit, then Go-Live check.")
    print("=" * 126)


if __name__ == "__main__":
    asyncio.run(main())
