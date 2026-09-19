from __future__ import annotations

import ast
import asyncio
import builtins
import re
import symtable
from pathlib import Path

from database.connection import ProblemCandidate
from processors.calibration import calibration_report
from processors.market_closure_readiness import market_closure_readiness
from processors.materiality_research import ENGINE_VERSION as MATERIALITY_ENGINE, _same_problem_structural
from processors.opportunity_reality import _material_consequence_support
from processors.quality_guard import audit_quality
from processors.research_orchestrator import ENGINE_VERSION as ORCHESTRATOR_ENGINE
from processors.signalforge_runtime import ENGINE_VERSION as RUNTIME_ENGINE
from processors.system_wide_audit import ENGINE_VERSION as AUDIT_ENGINE
from processors.problem_recurrence_multi import ENGINE_VERSION as RECURRENCE_ENGINE

FILES = [
    "processors/materiality_research.py",
    "processors/problem_recurrence_multi.py",
    "processors/problem_candidate_engine.py",
    "processors/problem_discovery_refresh.py",
    "processors/research_orchestrator.py",
    "processors/signalforge_runtime.py",
    "processors/system_wide_audit.py",
    "run_signalforge_m15_acceptance.py",
    "show_signalforge_full_system_audit.py",
]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _defined(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    def target(node):
        if isinstance(node, ast.Name): names.add(node.id)
        elif isinstance(node, (ast.Tuple, ast.List)):
            for item in node.elts: target(item)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Import):
            for alias in node.names: names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name != "*": names.add(alias.asname or alias.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets: target(t)
        elif isinstance(node, ast.AnnAssign): target(node.target)
    return names


def static_symbol_check() -> dict:
    root = Path(__file__).resolve().parent
    builtin_names = set(dir(builtins))
    issues = []
    for rel in FILES:
        path = root / rel
        require(path.exists(), f"missing M15 file: {rel}")
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        defined = _defined(tree)
        table = symtable.symtable(source, str(path), "exec")
        unresolved = set()
        def walk(scope):
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
        if unresolved:
            issues.append(f"{rel}: {sorted(unresolved)}")
    require(not issues, "undefined global(s): " + " | ".join(issues))
    return {"files": len(FILES), "undefined_globals": 0}


def source_contract_check() -> dict:
    root = Path(__file__).resolve().parent
    require(ORCHESTRATOR_ENGINE == "auto-research-orchestrator-v21-m15-fast-evidence-conversion", "unexpected M15 orchestrator")
    require(RUNTIME_ENGINE == "signalforge-runtime-v3-fast-cycle-lease", "unexpected M15 runtime")
    require(MATERIALITY_ENGINE == "materiality-research-v1-direct-structural", "unexpected materiality engine")
    require(RECURRENCE_ENGINE == "radar-production-same-problem-v2-cycle-budgeted", "C02 truth engine changed")
    require(AUDIT_ENGINE == "system-wide-audit-v3-m15-fast-evidence", "unexpected M15 audit")

    orch = (root / "processors/research_orchestrator.py").read_text(encoding="utf-8")
    runtime = (root / "processors/signalforge_runtime.py").read_text(encoding="utf-8")
    reality = (root / "processors/opportunity_reality.py").read_text(encoding="utf-8")
    ledger = (root / "processors/radar_ledger.py").read_text(encoding="utf-8")

    require(orch.count("await run_problem_recurrence_multi(") == 1, "M15 must run production C02 exactly once per cycle")
    for marker in (
        "_refresh_groups_parallel", "asyncio.gather", "run_materiality_research",
        "_claim_prefetch_rows", "phase_seconds", "BATCHED_WITH_ROUND_FINAL_DECISION",
    ):
        require(marker in orch, f"M15 orchestrator marker missing: {marker}")
    require('rounds=1' in runtime, "runtime is not one-round")
    require('"C03","consequence_material","PROBLEM_REALITY",False,2,0.90' in ledger.replace(" ", ""), "C03 two-family/0.90 ledger contract changed")
    require("MATERIAL_CONSEQUENCE_PATTERNS" in reality, "strict C03 material consequence contract missing")
    return {"status": "PASS", "recurrence_calls_per_cycle": 1, "runtime_rounds": 1}


def api_contract_check() -> dict:
    from api.main import app
    paths = app.openapi().get("paths") or {}
    expected = {
        "/api/signalforge/daily": "get",
        "/api/signalforge/status": "get",
        "/api/signalforge/trigger": "post",
        "/api/signalforge/audit": "get",
    }
    missing = [f"{m.upper()} {p}" for p, m in expected.items() if m not in (paths.get(p) or {})]
    require(not missing, "SignalForge API missing: " + ", ".join(missing))
    return {"status": "PASS", "routes": len(expected)}


def materiality_behavior_check() -> dict:
    # Exercise the real production candidate contract. Constructing the ORM
    # object is in-memory only and performs no database write.
    candidate = ProblemCandidate(
        canonical_key="m15-acceptance-materiality-fixture",
        title="AI deployment fails in production",
        problem_statement="AI service deployment fails in production",
        actor="ML platform engineer",
        actor_category="ENGINEERING",
        task="deploy AI service",
        object="production deployment",
        failure_mode="deployment fails",
        consequence="production deployment blocked for 3 hours",
        buyer_context="engineering platform team",
        workaround="manual rollback and debugging",
        community_platform="acceptance",
        discussion_key="m15-materiality-smoke",
    )
    good_doc = {
        "text": "Our production deployment fails and the release is blocked for 3 hours while engineers debug the deployment failure."
    }
    bad_identity = {
        "text": "Our payroll export fails and accounting is blocked for 3 hours."
    }
    annoying_only = {
        "text": "The AI deployment UI is frustrating and annoying but we can still deploy normally."
    }
    for field in ("actor", "task", "object", "failure_mode", "consequence", "buyer_context"):
        require(hasattr(candidate, field), f"materiality fixture missing production field: {field}")

    same_good, detail = _same_problem_structural(candidate, good_doc)
    same_bad, _ = _same_problem_structural(candidate, bad_identity)
    require(same_good, f"same-problem materiality positive smoke failed: {detail}")
    require(not same_bad, "unrelated material consequence passed structural identity")
    require(_material_consequence_support(candidate.consequence, good_doc["text"]), "material consequence positive smoke failed")
    require(not _material_consequence_support(candidate.consequence, annoying_only["text"]), "generic annoyance became material consequence")
    return {"status": "PASS", "thresholds_weakened": False}


async def main() -> None:
    print("=" * 126)
    print("SIGNALFORGE M15 FAST GO-LIVE ACCEPTANCE")
    print("=" * 126)
    print("No crawler. No full recurrence. No LLM. No threshold weakening. No synthetic market outcome.")
    print("This acceptance is intentionally short; the next real Radar cycle is the end-to-end product test.\n")

    symbols = static_symbol_check()
    source = source_contract_check()
    api = api_contract_check()
    materiality = materiality_behavior_check()
    quality = await audit_quality()
    require(quality.get("status") == "PASS" and int(quality.get("critical_count", 0) or 0) == 0, "pre-cycle quality is not PASS")

    closure = market_closure_readiness()
    require(closure.get("unregistered_result_bypass_allowed") is False, "market-result bypass reopened")
    calibration = calibration_report()
    completed = int(calibration.get("completed_experiments", 0) or 0)
    if completed < 10:
        require((calibration.get("credibility") or {}).get("status") == "UNVALIDATED", "calibration overclaimed credibility")

    print(f"STATIC Python={symbols['files']} undefined_globals=0")
    print(f"SOURCE CONTRACT status={source['status']} recurrence_per_cycle=1 runtime_rounds=1")
    print(f"API status={api['status']} routes={api['routes']}")
    print(f"C03 MATERIALITY status={materiality['status']} thresholds_weakened=NO")
    print(f"QUALITY status={quality.get('status')} critical={quality.get('critical_count',0)}")
    print(f"MARKET CLOSURE bypass_allowed={closure.get('unregistered_result_bypass_allowed')} calibration={(calibration.get('credibility') or {}).get('status')}")
    print("\nSIGNALFORGE_M15_ACCEPTANCE_PASS")
    print("Next: python run_radar_cycle.py ; then python show_signalforge_full_system_audit.py")
    print("=" * 126)


if __name__ == "__main__":
    asyncio.run(main())
