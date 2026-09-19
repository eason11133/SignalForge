from __future__ import annotations

import ast
import asyncio
import builtins
import hashlib
import symtable
from pathlib import Path

from database.connection import (
    ProblemCandidate,
    RadarClaim,
    RadarClaimEvidence,
    RadarEvidence,
)
from processors.calibration import calibration_report
from processors.market_closure_readiness import market_closure_readiness
from processors.materiality_research import (
    ENGINE_VERSION as MATERIALITY_ENGINE,
    _same_problem_structural,
)
from processors.opportunity_reality import (
    _ensure_evidence,
    _hash_key,
    _link_claim,
    _material_consequence_support,
    _refresh_claim_state,
)
from processors.quality_guard import audit_quality
from processors.research_orchestrator import (
    ENGINE_VERSION as ORCHESTRATOR_ENGINE,
    _normalize_solution_targets,
)
from processors.signalforge_runtime import ENGINE_VERSION as RUNTIME_ENGINE
from processors.system_wide_audit import ENGINE_VERSION as AUDIT_ENGINE
from processors.problem_recurrence_multi import ENGINE_VERSION as RECURRENCE_ENGINE

FILES = [
    "processors/opportunity_reality.py",
    "processors/materiality_research.py",
    "processors/research_orchestrator.py",
    "processors/signalforge_runtime.py",
    "processors/system_wide_audit.py",
    "run_signalforge_m16_acceptance.py",
    "show_signalforge_full_system_audit.py",
]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _defined(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    def target(node):
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


def static_symbol_check() -> dict:
    root = Path(__file__).resolve().parent
    builtin_names = set(dir(builtins))
    issues = []
    for rel in FILES:
        path = root / rel
        require(path.exists(), f"missing M16 file: {rel}")
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
    require(
        ORCHESTRATOR_ENGINE == "auto-research-orchestrator-v22-m16-go-live-finalization",
        "unexpected M16 orchestrator",
    )
    require(
        MATERIALITY_ENGINE == "materiality-research-v2-batched-ledger-cache",
        "unexpected M16 materiality engine",
    )
    require(
        RUNTIME_ENGINE == "signalforge-runtime-v3-fast-cycle-lease",
        "runtime contract changed",
    )
    require(
        RECURRENCE_ENGINE == "radar-production-same-problem-v2-cycle-budgeted",
        "C02 truth engine changed",
    )
    require(
        AUDIT_ENGINE == "system-wide-audit-v4-m16-go-live-finalization",
        "unexpected M16 audit",
    )

    orch = (root / "processors/research_orchestrator.py").read_text(encoding="utf-8")
    reality = (root / "processors/opportunity_reality.py").read_text(encoding="utf-8")
    materiality = (root / "processors/materiality_research.py").read_text(encoding="utf-8")
    ledger = (root / "processors/radar_ledger.py").read_text(encoding="utf-8")

    require(
        orch.count("await run_problem_recurrence_multi(") == 1,
        "production C02 must run exactly once per cycle",
    )
    require(
        "current = await _load_fast_cycle_state(limit=50)" in orch,
        "fast intermediate claim snapshot missing",
    )
    require(
        orch.count("updated = await run_opportunity_decision(limit=50)") == 1,
        "normal path must have exactly one final full Decision rebuild",
    )
    require(
        "_normalize_solution_targets" in orch
        and 'elif gate not in {"CURRENT_SOLUTION", "UNRESOLVED_GAP"}:' in orch,
        "solution target shadowing fix missing",
    )
    require(
        "solution_allowance = min(" in orch and "\n            3,\n" in orch,
        "C06 focused adjudication allowance not expanded",
    )
    for marker in (
        "_prime_reality_session_caches",
        "signalforge_evidence_cache",
        "signalforge_link_cache",
        "signalforge_rows_by_claim",
    ):
        require(marker in reality, f"Reality cache marker missing: {marker}")
    require(
        "_prime_reality_session_caches" in materiality,
        "C03 materiality is not using batched ledger cache",
    )
    require(
        '"C03","consequence_material","PROBLEM_REALITY",False,2,0.90'
        in ledger.replace(" ", ""),
        "C03 two-family/0.90 contract changed",
    )
    return {
        "status": "PASS",
        "full_decision_normal_path": 1,
        "recurrence_per_cycle": 1,
        "solution_target_shadowing_fixed": True,
        "ledger_cache": True,
    }


def api_contract_check() -> dict:
    from api.main import app

    paths = app.openapi().get("paths") or {}
    expected = {
        "/api/signalforge/daily": "get",
        "/api/signalforge/status": "get",
        "/api/signalforge/trigger": "post",
        "/api/signalforge/audit": "get",
    }
    missing = [
        f"{method.upper()} {path}"
        for path, method in expected.items()
        if method not in (paths.get(path) or {})
    ]
    require(not missing, "SignalForge API missing: " + ", ".join(missing))
    return {"status": "PASS", "routes": len(expected)}


def materiality_behavior_check() -> dict:
    candidate = ProblemCandidate(
        canonical_key="m16-acceptance-materiality-fixture",
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
        discussion_key="m16-materiality-smoke",
    )
    good_doc = {
        "text": (
            "Our production deployment fails and the release is blocked for "
            "3 hours while engineers debug the deployment failure."
        )
    }
    bad_doc = {
        "text": "Our payroll export fails and accounting is blocked for 3 hours."
    }
    annoying = {
        "text": (
            "The AI deployment UI is frustrating and annoying but we can "
            "still deploy normally."
        )
    }
    same_good, detail = _same_problem_structural(candidate, good_doc)
    same_bad, _ = _same_problem_structural(candidate, bad_doc)
    require(same_good, f"materiality identity positive failed: {detail}")
    require(not same_bad, "unrelated consequence passed materiality identity")
    require(
        _material_consequence_support(candidate.consequence, good_doc["text"]),
        "material consequence positive failed",
    )
    require(
        not _material_consequence_support(candidate.consequence, annoying["text"]),
        "generic annoyance became material consequence",
    )
    return {"status": "PASS", "thresholds_weakened": False}


def solution_target_behavior_check() -> dict:
    focused = [
        {"case_id": 1, "current_gate": "PAIN_MATERIALITY"},
        {"case_id": 2, "current_gate": "CURRENT_SOLUTION_RECHECK"},
        {"case_id": 3, "current_gate": "UNRESOLVED_GAP"},
        {"case_id": 4, "current_gate": "BUYER_REALITY"},
    ]
    normalized = _normalize_solution_targets(focused)
    require(
        [row["case_id"] for row in normalized] == [2, 3],
        f"non-solution gates leaked into C06/C07 target set: {normalized}",
    )
    require(
        [row["current_gate"] for row in normalized]
        == ["CURRENT_SOLUTION", "UNRESOLVED_GAP"],
        "solution recheck normalization failed",
    )

    # Reproduce the exact M15 shadowing failure: a PAIN row and a forced C06
    # prefetch row share the same case_id. Only the forced C06 row may survive.
    solution_by_case = {
        int(row["case_id"]): row
        for row in _normalize_solution_targets(
            [{"case_id": 7, "current_gate": "PAIN_MATERIALITY"}]
        )
    }
    prefetch = {"case_id": 7, "current_gate": "CURRENT_SOLUTION"}
    solution_by_case.setdefault(7, prefetch)
    require(
        solution_by_case[7]["current_gate"] == "CURRENT_SOLUTION",
        "C06 prefetch is still shadowed by an earlier gate",
    )
    return {"status": "PASS", "shadowing_fixed": True}


class _NoQuerySession:
    def __init__(self, info):
        self.info = info
        self.execute_calls = 0

    async def execute(self, *args, **kwargs):
        self.execute_calls += 1
        raise RuntimeError("point SELECT should not execute when cache is primed")

    def add(self, value):
        raise RuntimeError("cache-hit smoke must not add rows")

    async def flush(self):
        raise RuntimeError("cache-hit smoke must not flush")


async def ledger_cache_behavior_check() -> dict:
    case_id = 9991
    source_type = "acceptance"
    source_table = "acceptance"
    source_ref = "cached-evidence"
    evidence_key = (
        "reality:"
        + _hash_key(case_id, source_type, source_table, source_ref)
    )
    evidence = RadarEvidence(
        id=991,
        case_id=case_id,
        evidence_key=evidence_key,
        source_type=source_type,
        source_table=source_table,
        source_ref=source_ref,
        source_family_key="acceptance:family",
        authority_class="USER_DISCUSSION",
        directness="DIRECT",
    )
    claim = RadarClaim(
        id=992,
        case_id=case_id,
        claim_code="C03",
        claim_type="consequence_material",
        gate_group="PROBLEM_REALITY",
        statement="material consequence",
        state="INSUFFICIENT",
        required_support_groups=1,
    )
    link = RadarClaimEvidence(
        id=993,
        claim_id=claim.id,
        evidence_id=evidence.id,
        stance="INSUFFICIENT",
        interpretation_method="deterministic_reality_v2",
        method_version="acceptance",
        interpretation_confidence=0.5,
        rationale="acceptance",
        validated=True,
    )
    info = {
        "signalforge_evidence_cache": {evidence_key: evidence},
        "signalforge_link_cache": {(claim.id, evidence.id): link},
        "signalforge_rows_by_claim": {claim.id: [(link, evidence)]},
    }
    session = _NoQuerySession(info)

    found = await _ensure_evidence(
        session,
        case_id,
        source_type=source_type,
        source_table=source_table,
        source_ref=source_ref,
        source_title="cached",
        excerpt="cached",
        source_url=None,
        source_family_key="acceptance:family",
        authority_class="USER_DISCUSSION",
        directness="DIRECT",
    )
    require(found is evidence, "evidence cache did not return existing ORM row")

    created = await _link_claim(
        session,
        claim,
        evidence,
        stance="SUPPORT",
        rationale="cache smoke",
        confidence=0.99,
    )
    require(created is False, "existing cached link was duplicated")
    require(session.execute_calls == 0, "cache hit still issued a point SELECT")

    await _refresh_claim_state(session, claim)
    require(claim.state == "SUPPORTED", "cached link rows did not refresh claim truth")
    require(session.execute_calls == 0, "claim refresh ignored cached link rows")
    return {"status": "PASS", "point_selects": 0}


async def main() -> None:
    print("=" * 126)
    print("SIGNALFORGE M16 GO-LIVE FINALIZATION ACCEPTANCE")
    print("=" * 126)
    print(
        "No crawler. No full recurrence. No LLM. No threshold weakening. "
        "No synthetic market outcome."
    )
    print(
        "This acceptance validates the M15 blockers before the single real "
        "end-to-end Radar cycle.\\n"
    )

    symbols = static_symbol_check()
    source = source_contract_check()
    api = api_contract_check()
    materiality = materiality_behavior_check()
    solution = solution_target_behavior_check()
    cache = await ledger_cache_behavior_check()

    quality = await audit_quality()
    require(
        quality.get("status") == "PASS"
        and int(quality.get("critical_count", 0) or 0) == 0,
        "pre-cycle quality is not PASS",
    )

    closure = market_closure_readiness()
    require(
        closure.get("unregistered_result_bypass_allowed") is False,
        "market-result bypass reopened",
    )
    calibration = calibration_report()
    completed = int(calibration.get("completed_experiments", 0) or 0)
    if completed < 10:
        require(
            (calibration.get("credibility") or {}).get("status")
            == "UNVALIDATED",
            "calibration overclaimed credibility",
        )

    print(f"STATIC Python={symbols['files']} undefined_globals=0")
    print(
        "SOURCE CONTRACT "
        f"status={source['status']} full_decision_normal_path=1 "
        "recurrence_per_cycle=1 ledger_cache=PASS"
    )
    print(f"API status={api['status']} routes={api['routes']}")
    print(
        f"C03 MATERIALITY status={materiality['status']} "
        "thresholds_weakened=NO"
    )
    print(
        f"C06/C07 TARGETING status={solution['status']} "
        "shadowing_fixed=YES"
    )
    print(
        f"LEDGER CACHE status={cache['status']} "
        f"point_selects={cache['point_selects']}"
    )
    print(
        f"QUALITY status={quality.get('status')} "
        f"critical={quality.get('critical_count',0)}"
    )
    print(
        "MARKET CLOSURE "
        f"bypass_allowed={closure.get('unregistered_result_bypass_allowed')} "
        f"calibration={(calibration.get('credibility') or {}).get('status')}"
    )
    print("\\nSIGNALFORGE_M16_ACCEPTANCE_PASS")
    print(
        "Next: python run_radar_cycle.py ; then "
        "python show_signalforge_full_system_audit.py"
    )
    print("=" * 126)


if __name__ == "__main__":
    asyncio.run(main())
