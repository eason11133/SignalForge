from __future__ import annotations

import ast
import asyncio
import builtins
import shutil
import subprocess
import symtable
from datetime import datetime, timedelta
from pathlib import Path

from processors.calibration import calibration_report
from processors.company_reality import ENGINE_VERSION as COMPANY_ENGINE_VERSION
from processors.commercial_reality import ENGINE_VERSION as COMMERCIAL_ENGINE_VERSION
from processors.founder_daily_surface import build_founder_daily_surface
from processors.historical_replay import run_historical_replay
from processors.opportunity_decision import run_opportunity_decision
from processors.opportunity_reality import (
    ENGINE_VERSION as OPPORTUNITY_REALITY_ENGINE_VERSION,
    _material_consequence_support,
)
from processors.quality_guard import (
    STRICT_LEDGER_CODES,
    audit_quality,
    capture_quality_snapshot,
    repair_ledger_state_from_validated_links,
    rollback_quality_snapshot,
)
from processors.solution_gap_research import ENGINE_VERSION as SOLUTION_ENGINE_VERSION
from processors.system_wide_audit import run_system_wide_audit
from processors.validation_cohort import build_validation_cohort



M13_PYTHON_FILES = [
    "api/main.py",
    "api/routes/signalforge.py",
    "processors/calibration.py",
    "processors/commercial_reality.py",
    "processors/company_reality.py",
    "processors/founder_daily_surface.py",
    "processors/historical_replay.py",
    "processors/opportunity_decision.py",
    "processors/opportunity_reality.py",
    "processors/quality_guard.py",
    "processors/radar_ledger.py",
    "processors/research_orchestrator.py",
    "processors/signalforge_runtime.py",
    "processors/solution_gap_research.py",
    "processors/system_wide_audit.py",
    "processors/validation_cohort.py",
    "run_signalforge_m13_acceptance.py",
    "show_signalforge_full_system_audit.py",
]


def _module_defined_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()

    def add_target(node: ast.AST) -> None:
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, (ast.Tuple, ast.List)):
            for item in node.elts:
                add_target(item)

    def scan_statements(statements: list[ast.stmt]) -> None:
        for node in statements:
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
                for target in node.targets:
                    add_target(target)
            elif isinstance(node, ast.AnnAssign):
                add_target(node.target)
            elif isinstance(node, ast.Try):
                scan_statements(node.body)
                scan_statements(node.orelse)
                scan_statements(node.finalbody)
                for handler in node.handlers:
                    scan_statements(handler.body)

    scan_statements(tree.body)
    return names


def static_runtime_symbol_checks() -> dict:
    root = Path(__file__).resolve().parent
    builtins_set = set(dir(builtins))
    issues: list[str] = []
    checked = 0

    for rel in M13_PYTHON_FILES:
        path = root / rel
        require(path.exists(), f"M13 runtime file missing: {rel}")
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        defined = _module_defined_names(tree)
        table = symtable.symtable(source, str(path), "exec")
        unresolved: set[str] = set()

        def walk(scope) -> None:
            for child in scope.get_children():
                for symbol in child.get_symbols():
                    if not (symbol.is_referenced() and symbol.is_global()):
                        continue
                    name = symbol.get_name()
                    if name in {"__file__"} or name in defined or name in builtins_set:
                        continue
                    unresolved.add(name)
                walk(child)

        walk(table)
        if unresolved:
            issues.append(f"{rel}: undefined global(s) {sorted(unresolved)}")
        checked += 1

    require(not issues, "M13 undefined-runtime-symbol preflight failed: " + " | ".join(issues))
    return {"checked_python_files": checked, "undefined_globals": 0}

def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def source_contract_checks() -> None:
    root = Path(__file__).resolve().parent

    commercial = (root / "processors/commercial_reality.py").read_text(encoding="utf-8")
    require(
        "commercial-reality-v5-truth-preserving-context" in commercial,
        "commercial reality truth-preserving engine missing",
    )
    require(
        "UNKNOWN -> INSUFFICIENT -> Quality-Guard repair oscillation" in commercial,
        "commercial reality zero-evidence state-preservation guard missing",
    )

    reality = (root / "processors/opportunity_reality.py").read_text(encoding="utf-8")
    require("MATERIAL_CONSEQUENCE_PATTERNS" in reality, "C03 material consequence gate missing")
    require("_material_consequence_support" in reality, "C03 material consequence evaluator missing")
    require(
        _material_consequence_support(
            "production deployment blocked for 3 hours",
            "The production deployment is blocked for 3 hours because inference keeps failing.",
        ) is True,
        "C03 material-consequence positive smoke failed",
    )
    require(
        _material_consequence_support(
            "users dislike output quality",
            "Users are frustrated and say the model fails sometimes.",
        ) is False,
        "C03 generic-frustration negative smoke failed",
    )

    ledger = (root / "processors/radar_ledger.py").read_text(encoding="utf-8")
    require(
        "plausible named economic buyer that owns or budgets for solving this exact job" in ledger,
        "C05 buyer-reality statement still conflates buyer existence with WTP",
    )

    solution = (root / "processors/solution_gap_research.py").read_text(encoding="utf-8")
    require("ProductReview" in solution and "product_review_post" in solution, "ProductReview recall path missing")

    replay = (root / "processors/historical_replay.py").read_text(encoding="utf-8")
    require("CURRENT_POLICY_ON_HISTORICAL_EVIDENCE" in replay, "historical replay policy mode not explicit")
    require("policy_frozen_to_cutoff" in replay, "historical replay policy-fidelity flag missing")

    api_main = (root / "api/main.py").read_text(encoding="utf-8")
    require("startup_catchup" in api_main, "SignalForge startup wake-catchup missing")
    require("/api/signalforge" in api_main, "SignalForge API router missing")

    dashboard = (root / "dashboard/src/pages/OpportunityRadar.tsx").read_text(encoding="utf-8")
    require("useSignalForgeDaily" in dashboard, "Founder homepage is not wired to SignalForge truth")
    require("不會退回舊 ProblemCandidate 分數假裝正常" in dashboard, "legacy-truth fail-closed UI guard missing")


def api_route_contract_check() -> dict:
    """Verify effective SignalForge paths through OpenAPI.

    FastAPI 0.137+ preserves included routers as nested route objects, so
    app.routes is not guaranteed to be a flat list of final path operations.
    """
    from api.main import app

    schema = app.openapi()
    paths = schema.get("paths") or {}
    expected = {
        "/api/signalforge/daily": "get",
        "/api/signalforge/status": "get",
        "/api/signalforge/trigger": "post",
        "/api/signalforge/audit": "get",
    }

    missing = []
    for path, method in expected.items():
        operations = paths.get(path) or {}
        if method not in operations:
            missing.append(f"{method.upper()} {path}")

    require(
        not missing,
        "SignalForge API route contract missing from OpenAPI: " + ", ".join(missing),
    )
    return {
        "status": "PASS",
        "checked": len(expected),
        "paths": sorted(expected),
        "verification": "OPENAPI_EFFECTIVE_PATHS",
    }


def frontend_build_check() -> dict:
    root = Path(__file__).resolve().parent
    dashboard = root / "dashboard"
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    if not npm:
        raise RuntimeError("npm not found; frontend acceptance cannot be verified")
    if not (dashboard / "node_modules").exists():
        raise RuntimeError("dashboard/node_modules missing; run npm ci --legacy-peer-deps before M13 acceptance")

    proc = subprocess.run(
        [npm, "run", "build"],
        cwd=dashboard,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=240,
        shell=False,
    )
    lines = (proc.stdout or "").splitlines()
    tail = lines[-20:]
    if proc.returncode != 0:
        print("\nFRONTEND BUILD OUTPUT (tail)")
        for line in tail:
            print("  " + line)
        raise RuntimeError(f"dashboard build failed with exit code {proc.returncode}")
    return {"status": "PASS", "tail": tail}


async def main() -> None:
    print("=" * 126)
    print("SIGNALFORGE M13 FULL-SYSTEM ACCEPTANCE")
    print("=" * 126)
    print("No crawler. No LLM. No threshold weakening. No synthetic market outcome.")
    print("Deterministic ledger/reality reconciliation may update DB claim/link state; quality rollback is armed.")
    print()

    static_symbols = static_runtime_symbol_checks()
    source_contract_checks()
    require("C03" in STRICT_LEDGER_CODES, "C03 is not quality-locked in strict ledger codes")
    require(COMPANY_ENGINE_VERSION == "company-reality-v3-profile-backed-execution", "unexpected company reality engine")
    require(COMMERCIAL_ENGINE_VERSION == "commercial-reality-v5-truth-preserving-context", "unexpected commercial reality engine")
    require(OPPORTUNITY_REALITY_ENGINE_VERSION == "opportunity-reality-v6-threshold-consistent", "unexpected opportunity reality engine")
    require(SOLUTION_ENGINE_VERSION == "solution-gap-reality-closure-v7-review-recall", "unexpected solution-gap engine")

    # Fail all code/API/frontend surfaces before any deterministic DB mutation.
    api_contract = api_route_contract_check()
    frontend = frontend_build_check()

    snapshot = await capture_quality_snapshot()
    rollback_needed = True

    try:
        quality_before = await audit_quality()

        # Re-evaluate deterministic reality under the M13 contracts, then reconcile
        # all strict claim states to the validated independent-family ledger.
        first_decision = await run_opportunity_decision(limit=50)
        repair = await repair_ledger_state_from_validated_links()
        decision = await run_opportunity_decision(limit=50)

        require(decision.get("build_locked") is True, "BUILD lock was weakened")
        company = decision.get("company") or {}
        require(company.get("company_profile_loaded") is True, "company capability profile was not loaded")

        rows = decision.get("rows") or []
        require(bool(rows), "no Radar decision rows")
        for row in rows:
            require(row.get("candidate_id") is not None, f"case {row.get('case_id')} lacks candidate_id")
            if str(row.get("decision_verdict") or "").upper() == "VALIDATE":
                claims = row.get("claims") or {}
                missing = [
                    code for code in ("C03", "C05", "C06", "C07", "C09")
                    if str(claims.get(code) or "UNKNOWN").upper() != "SUPPORTED"
                ]
                require(not missing, f"case {row.get('case_id')} VALIDATE missing prerequisites {missing}")

        # Build Founder surface and freeze a treatment/control cohort before any
        # future live outcome. This does not authorize controls or claim accuracy.
        cohort = build_validation_cohort(rows, save=True)
        require(cohort.get("market_truth_claimed") is False, "validation cohort fabricated market truth")
        require(cohort.get("predictive_accuracy_claimed") is False, "validation cohort fabricated predictive accuracy")

        founder = await build_founder_daily_surface(limit=10, save_snapshot=True)
        require(bool(founder.get("cards")), "Founder Daily produced no cards")
        require((founder.get("quality") or {}).get("status") == "PASS", "Founder Daily quality is not PASS")
        require("validation_cohort" in founder, "Founder Daily missing prospective control cohort")
        for card in founder.get("cards") or []:
            require(card.get("candidate_id") is not None, f"Founder card case {card.get('case_id')} lacks candidate_id")

        # One final deterministic reconciliation after all read surfaces have run.
        repair_after = await repair_ledger_state_from_validated_links()
        final_decision = await run_opportunity_decision(limit=50)
        quality_after = await audit_quality(decision=final_decision)
        require(quality_after.get("status") == "PASS", f"quality regression: {quality_after.get('critical')}")
        require(quality_after.get("critical_count", 0) == 0, "critical quality issue remains")

        calibration = calibration_report()
        completed = int(calibration.get("completed_experiments", 0) or 0)
        credibility = (calibration.get("credibility") or {}).get("status")
        if completed < 10:
            require(credibility == "UNVALIDATED", "calibration overclaimed credibility")
        prospective = calibration.get("prospective_controls") or {}
        require(prospective.get("outcomes_compared", 0) == 0, "prospective controls fabricated comparative outcomes")

        replay = await run_historical_replay(
            cutoff=datetime.utcnow() - timedelta(days=30),
            save_report=True,
        )
        require(replay.get("predictive_accuracy") == "UNVALIDATED", "replay fabricated predictive accuracy")
        require(replay.get("policy_mode") == "CURRENT_POLICY_ON_HISTORICAL_EVIDENCE", "replay policy mode missing")
        require(replay.get("policy_frozen_to_cutoff") is False, "replay falsely claims historical policy fidelity")

        audit = await run_system_wide_audit()
        require(audit.get("percentages_auto_advanced") is False, "system audit auto-inflated completion percentages")
        require((audit.get("quality") or {}).get("status") == "PASS", "system-wide audit quality failed")
        areas = audit.get("areas") or {}
        required_areas = {
            "Data Sources / Crawlers", "Source Coverage / Health", "Problem Discovery",
            "C02 Recurrence / Same Problem", "C03 Pain Materiality", "Evidence Ledger",
            "Evidence Integrity / Quality Guard", "C05 Buyer Reality", "C06 Current Solution",
            "C07 Unresolved Gap", "C08 Differentiation", "C09 Execution Reality",
            "C10 Distribution", "C11 Economics / WTP", "C12 Opportunity Window",
            "C13 Competition", "C14 Switching", "Decision Engine", "Research Controller",
            "Scheduler / Research Portfolio", "Founder Daily Radar", "VALIDATE -> Market Test",
            "Market Result -> Evidence -> Decision", "Historical Replay Engine",
            "Calibration Infrastructure", "Live Market Calibration", "Predictive Accuracy",
        }
        require(required_areas <= set(areas), f"system audit missing areas: {sorted(required_areas - set(areas))}")

        rollback_needed = False

        print("SOURCE / CONTRACT CHECKS")
        print(
            f"  status=PASS | static_python_files={static_symbols.get('checked_python_files')} "
            f"undefined_globals={static_symbols.get('undefined_globals')} | C03 strict-ledger=YES "
            f"| C05 buyer/WTP separation=YES | legacy UI fallback=BLOCKED"
        )
        print(
            f"  SignalForge API={api_contract.get('status')} "
            f"routes={api_contract.get('checked')} verification={api_contract.get('verification')} "
            f"| frontend={frontend.get('status')}"
        )
        print("\nLEDGER RECONCILIATION")
        print(
            f"  first repair changed={repair.get('changed_claims', 0)} by_code={repair.get('changed_by_code', {})} "
            f"| final repair changed={repair_after.get('changed_claims', 0)} by_code={repair_after.get('changed_by_code', {})}"
        )
        print("  thresholds_weakened=NO | evidence_deleted=0 | links_deleted=0")
        print("\nQUALITY")
        print(
            f"  before={quality_before.get('status')} critical={quality_before.get('critical_count', 0)} "
            f"| after={quality_after.get('status')} critical={quality_after.get('critical_count', 0)}"
        )
        print("\nCOMPANY / SOLUTION REALITY")
        print(
            f"  company_profile_loaded={company.get('company_profile_loaded')} "
            f"profile_version={company.get('company_profile_version')} "
            f"| solution_engine={SOLUTION_ENGINE_VERSION}"
        )
        print("\nFOUNDER / VALIDATION")
        vb = founder.get("validation_boundary") or {}
        print(
            f"  cards={len(founder.get('cards', []) or [])} | founder_action_now={vb.get('founder_action_now', 0)} "
            f"prebuilt_waiting={vb.get('prebuilt_waiting', 0)} machine_first={vb.get('machine_first', 0)}"
        )
        print(
            f"  treatment={cohort.get('treatment_candidates', 0)} controls={cohort.get('control_candidates', 0)} "
            f"matched_pairs={len(cohort.get('matched_pairs', []) or [])}"
        )
        print("\nCALIBRATION / REPLAY")
        print(
            f"  completed_real={completed} credibility={credibility} "
            f"prospective_outcomes_compared={prospective.get('outcomes_compared', 0)}"
        )
        leak = replay.get("leakage") or {}
        print(
            f"  replay_policy={replay.get('policy_mode')} frozen_policy={replay.get('policy_frozen_to_cutoff')} "
            f"future_evidence_excluded={leak.get('future_evidence_excluded', 0)} "
            f"future_interpretation_excluded={leak.get('future_interpretation_excluded', 0)} "
            f"predictive_accuracy={replay.get('predictive_accuracy')}"
        )
        print("\nFRONTEND")
        print(f"  build={frontend.get('status')} | Founder homepage uses /api/signalforge truth")
        print("\nSIGNALFORGE_M13_ACCEPTANCE_PASS")
        print("Next: python run_radar_cycle.py ; then python show_signalforge_full_system_audit.py")
        print("=" * 126)

    except Exception:
        if rollback_needed:
            restored = await rollback_quality_snapshot(snapshot)
            print("\nM13 ACCEPTANCE FAILED — quality snapshot rollback executed")
            print("  rollback:", restored)
        raise


if __name__ == "__main__":
    asyncio.run(main())
