from __future__ import annotations

import ast
import asyncio
import builtins
import shutil
import subprocess
import symtable
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from processors.calibration import calibration_report
from processors.case_progression import ENGINE_VERSION as CASE_PROGRESSION_ENGINE
from processors.company_reality import ENGINE_VERSION as COMPANY_ENGINE
from processors.founder_daily_surface import build_founder_daily_surface
from processors.historical_replay import (
    ENGINE_VERSION as REPLAY_ENGINE,
    capture_forward_policy_snapshot,
    find_forward_policy_snapshot,
    forward_policy_snapshot_status,
    run_historical_replay,
)
from processors.market_closure_readiness import market_closure_readiness
from processors.market_ground_truth import validate_market_result_request
from processors.opportunity_decision import run_opportunity_decision
from processors.parallel_reality_bundle import ENGINE_VERSION as PARALLEL_ENGINE
from processors.problem_discovery_refresh import ENGINE_VERSION as DISCOVERY_ENGINE, discovery_due
from processors.problem_recurrence_multi import ENGINE_VERSION as RECURRENCE_ENGINE, run_problem_recurrence_multi
from processors.quality_guard import (
    audit_quality,
    capture_quality_snapshot,
    repair_ledger_state_from_validated_links,
    rollback_quality_snapshot,
)
from processors.research_orchestrator import (
    ENGINE_VERSION as ORCHESTRATOR_ENGINE,
    _buyer_shortlist_fingerprint,
    _classify_scraper_process_result,
)
from processors.signalforge_runtime import ENGINE_VERSION as RUNTIME_ENGINE
from processors.solution_gap_research import ENGINE_VERSION as SOLUTION_ENGINE, _community_solution_docs
from processors.system_wide_audit import run_system_wide_audit
from processors.validation_cohort import build_validation_cohort
import processors.historical_replay as replay_module
import processors.validation_cohort as cohort_module


M14_PYTHON_FILES = [
    "processors/calibration.py",
    "processors/case_progression.py",
    "processors/company_reality.py",
    "processors/founder_daily_surface.py",
    "processors/historical_replay.py",
    "processors/market_closure_readiness.py",
    "processors/opportunity_engine.py",
    "processors/parallel_reality_bundle.py",
    "processors/problem_candidate_engine.py",
    "processors/problem_discovery_refresh.py",
    "processors/problem_recurrence_multi.py",
    "processors/quality_guard.py",
    "processors/research_orchestrator.py",
    "processors/signalforge_runtime.py",
    "processors/solution_gap_research.py",
    "processors/system_wide_audit.py",
    "processors/validation_cohort.py",
    "run_radar_cycle.py",
    "run_signalforge_m14_acceptance.py",
    "show_signalforge_full_system_audit.py",
]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _module_defined_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()

    def add_target(node: ast.AST) -> None:
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, (ast.Tuple, ast.List)):
            for item in node.elts:
                add_target(item)

    def scan(statements: list[ast.stmt]) -> None:
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
                scan(node.body); scan(node.orelse); scan(node.finalbody)
                for handler in node.handlers:
                    scan(handler.body)

    scan(tree.body)
    return names


def static_runtime_symbol_checks() -> dict:
    root = Path(__file__).resolve().parent
    builtin_names = set(dir(builtins))
    issues: list[str] = []
    for rel in M14_PYTHON_FILES:
        path = root / rel
        require(path.exists(), f"M14 runtime file missing: {rel}")
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
                    if name in {"__file__"} or name in defined or name in builtin_names:
                        continue
                    unresolved.add(name)
                walk(child)

        walk(table)
        if unresolved:
            issues.append(f"{rel}: undefined global(s) {sorted(unresolved)}")
    require(not issues, "M14 undefined-runtime-symbol preflight failed: " + " | ".join(issues))
    return {"checked_python_files": len(M14_PYTHON_FILES), "undefined_globals": 0}


def api_route_contract_check() -> dict:
    from api.main import app
    paths = (app.openapi().get("paths") or {})
    expected = {
        "/api/signalforge/daily": "get",
        "/api/signalforge/status": "get",
        "/api/signalforge/trigger": "post",
        "/api/signalforge/audit": "get",
    }
    missing = [f"{method.upper()} {path}" for path, method in expected.items() if method not in (paths.get(path) or {})]
    require(not missing, "SignalForge API route contract missing: " + ", ".join(missing))
    return {"status": "PASS", "checked": len(expected), "verification": "OPENAPI_EFFECTIVE_PATHS"}


def frontend_build_check() -> dict:
    root = Path(__file__).resolve().parent
    dashboard = root / "dashboard"
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    require(bool(npm), "npm not found; frontend acceptance cannot be verified")
    require((dashboard / "node_modules").exists(), "dashboard/node_modules missing")
    proc = subprocess.run(
        [npm, "run", "build"], cwd=dashboard,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
        timeout=240, shell=False,
    )
    tail = (proc.stdout or "").splitlines()[-20:]
    if proc.returncode != 0:
        print("\nFRONTEND BUILD OUTPUT (tail)")
        for line in tail:
            print("  " + line)
        raise RuntimeError(f"dashboard build failed with exit code {proc.returncode}")
    return {"status": "PASS", "tail": tail}


def source_contract_checks() -> None:
    require(ORCHESTRATOR_ENGINE == "auto-research-orchestrator-v20-m14-go-live", "unexpected M14 orchestrator")
    require(RECURRENCE_ENGINE == "radar-production-same-problem-v2-cycle-budgeted", "unexpected C02 recurrence engine")
    require(DISCOVERY_ENGINE == "problem-discovery-refresh-v1-budgeted-stale-aware", "unexpected problem discovery engine")
    require(SOLUTION_ENGINE == "solution-gap-reality-closure-v8-community-recall", "unexpected C06/C07 engine")
    require(COMPANY_ENGINE == "company-reality-v4-gap-actionable-execution", "unexpected company reality engine")
    require(CASE_PROGRESSION_ENGINE == "case-progression-v2-go-live-diversity", "unexpected progression engine")
    require(PARALLEL_ENGINE == "parallel-reality-bundle-research-v2-precision", "unexpected parallel reality engine")
    require(RUNTIME_ENGINE == "signalforge-runtime-v2-cross-process-lease", "unexpected runtime engine")
    require(REPLAY_ENGINE == "historical-replay-v3-forward-policy-snapshots", "unexpected replay engine")

    root = Path(__file__).resolve().parent
    orchestrator = (root / "processors/research_orchestrator.py").read_text(encoding="utf-8")
    for marker in (
        "MAX_SOURCE_GROUPS_PER_CYCLE", "PASS_WITH_CLI_ERROR", "PYTHONIOENCODING",
        "run_problem_discovery_refresh", "run_problem_recurrence_multi",
        "parallel_context_gaps", "buyer_claim_stance_ai_v2_evidence_versioned",
    ):
        require(marker in orchestrator, f"M14 orchestrator contract missing {marker}")
    candidate = (root / "processors/problem_candidate_engine.py").read_text(encoding="utf-8")
    require("last_seen_by_discovery" in candidate, "stable CandidateEvidence discovery marker missing")
    require("delete(CandidateEvidence)" not in candidate, "discovery still delete/reinserts CandidateEvidence")
    runtime = (root / "processors/signalforge_runtime.py").read_text(encoding="utf-8")
    require("capture_forward_policy_snapshot" in runtime, "successful-cycle forward policy capture missing")
    dashboard = (root / "dashboard/src/pages/OpportunityRadar.tsx").read_text(encoding="utf-8")
    require("下一個可改變 Gate 的證據" in dashboard, "Founder next-evidence surface missing")
    require("clean frozen" in dashboard, "Founder frozen clean-control surface missing")


async def pure_behavior_checks() -> dict:
    now = datetime.utcnow().isoformat()
    due, reason = discovery_due({"max_post_id": 9, "last_success_at": now}, {"max_post_id": 9})
    require(due is False and reason == "FRESH", "fresh discovery incorrectly due")
    due2, reason2 = discovery_due({"max_post_id": 9, "last_success_at": now}, {"max_post_id": 10})
    require(due2 is True and reason2 == "CORPUS_CHANGED", "corpus-change discovery not triggered")

    scrape = _classify_scraper_process_result(
        name="jobs", returncode=1, before_run_id=5,
        after_run={"id": 6, "status": "completed", "records_new": 3},
        output_tail="terminal summary failed",
    )
    require(scrape.get("status") == "PASS_WITH_CLI_ERROR", "DB scraper truth did not override tail CLI error")

    shortlist = [{"structured_source":"arbeitnow","id":"1","company":"Acme","title":"AI Engineer","text":"own model reliability under load","semantic_score":.6,"lexical_score":.1,"shared_terms":["reliability"],"domain_shared":["ai"]}]
    f1 = _buyer_shortlist_fingerprint(1, shortlist)
    shortlist2 = [dict(shortlist[0], text="own model reliability under load with new budget mandate")]
    f2 = _buyer_shortlist_fingerprint(1, shortlist2)
    require(f1 != f2, "buyer cache fingerprint ignores changed evidence text")

    posts = [
        SimpleNamespace(id=1,title="Claude keeps forgetting context",body="Claude keeps forgetting context and fails our workflow repeatedly.",url="u1",posted_at=None,created_at=None,num_comments=3,platform_id=1,subreddit="x"),
        SimpleNamespace(id=2,title="Claude benchmark release",body="Claude benchmark release is faster and improved.",url="u2",posted_at=None,created_at=None,num_comments=2,platform_id=1,subreddit="x"),
        SimpleNamespace(id=3,title="Generic model issue",body="This model is broken but no named product appears in this complaint.",url="u3",posted_at=None,created_at=None,num_comments=2,platform_id=1,subreddit="x"),
    ]
    docs = _community_solution_docs(posts)
    require(len(docs) == 1 and docs[0].get("solution_identity") == "Claude", "community named-solution recall precision smoke failed")

    original_cohort_path = cohort_module.PATH
    original_forward_dir = replay_module.FORWARD_POLICY_DIR
    try:
        with tempfile.TemporaryDirectory() as td:
            cohort_module.PATH = Path(td) / "cohort.json"
            rows = [
                {"case_id":1,"decision_verdict":"INVESTIGATE","market_validation_boundary":"PREBUILT_WAITING_FOR_VALIDATE","attention_score":90},
                {"case_id":2,"decision_verdict":"INVESTIGATE","market_validation_boundary":"PREBUILT_WAITING_FOR_VALIDATE","attention_score":70},
                {"case_id":3,"decision_verdict":"WATCH","market_validation_boundary":"MACHINE_FIRST","attention_score":88},
                {"case_id":4,"decision_verdict":"WATCH","market_validation_boundary":"MACHINE_FIRST","attention_score":68},
            ]
            c1 = build_validation_cohort(rows, save=True)
            ids1 = [p["pair_id"] for p in c1["matched_pairs"]]
            c2 = build_validation_cohort([dict(r, attention_score=(r["attention_score"]+5)) for r in rows], save=True)
            require([p["pair_id"] for p in c2["matched_pairs"]] == ids1, "validation cohort silently rematched existing pairs")
            contaminated_rows = [dict(r) for r in rows]
            contaminated_rows[2]["market_validation_boundary"] = "PREBUILT_WAITING_FOR_VALIDATE"
            contaminated_rows[2]["decision_verdict"] = "INVESTIGATE"
            c3 = build_validation_cohort(contaminated_rows, save=True)
            require(c3.get("contaminated_pairs", 0) >= 1, "later-selected control not flagged contaminated")
            require(c3.get("selection_snapshot_frozen") is True, "validation selection snapshot not frozen")

        with tempfile.TemporaryDirectory() as td:
            replay_module.FORWARD_POLICY_DIR = Path(td)
            fake = {"engine_version":"decision-test","build_locked":True,"verdict_counts":{"WATCH":1},"rows":[{"case_id":1,"candidate_id":1,"title":"x","decision_verdict":"WATCH","current_gate":"C03","attention_score":10,"market_validation_boundary":"MACHINE_FIRST","claims":{"C03":"UNKNOWN"}}]}
            snap = await capture_forward_policy_snapshot(decision=fake, source="acceptance_pure")
            require(Path(snap["snapshot_path"]).exists(), "forward policy snapshot not persisted")
            found = find_forward_policy_snapshot(datetime.utcnow() + timedelta(seconds=2))
            require(found is not None and found.get("rows", [])[0].get("case_id") == 1, "forward policy snapshot lookup failed")
    finally:
        cohort_module.PATH = original_cohort_path
        replay_module.FORWARD_POLICY_DIR = original_forward_dir

    blocked = False
    try:
        validate_market_result_request(
            case_id=999999, event="ACQUISITION", result="PASS",
            experiment_id="definitely-unregistered-m14-acceptance",
            actor_label="actor", amount=None, currency=None,
        )
    except ValueError as exc:
        blocked = "not pre-registered" in str(exc)
    require(blocked, "unregistered market result bypass is not blocked")

    return {"status":"PASS","discovery":2,"scraper_truth":1,"buyer_cache":1,"solution_recall":3,"cohort_freeze":3,"forward_snapshot":2,"market_bypass":1}


async def main() -> None:
    print("=" * 126)
    print("SIGNALFORGE M14 GO-LIVE READINESS ACCEPTANCE")
    print("=" * 126)
    print("No crawler. No LLM. No threshold weakening. No synthetic market outcome.")
    print("All code/API/frontend/pure behavior checks run before deterministic DB mutation.")
    print()

    symbols = static_runtime_symbol_checks()
    source_contract_checks()
    api_contract = api_route_contract_check()
    frontend = frontend_build_check()
    pure = await pure_behavior_checks()

    snapshot = await capture_quality_snapshot()
    rollback_needed = True
    try:
        quality_before = await audit_quality()
        require(quality_before.get("status") == "PASS", "pre-M14 quality is not PASS")

        # Exercise the production C02 path with zero AI spend. Deterministic
        # matches/actions may update DB; quality rollback is armed.
        recurrence = await run_problem_recurrence_multi(ai_call_allowance=0)
        require(int(recurrence.get("llm_calls", 0) or 0) == 0, "C02 zero-AI acceptance spent LLM calls")

        decision0 = await run_opportunity_decision(limit=50)
        repair = await repair_ledger_state_from_validated_links()
        decision = await run_opportunity_decision(limit=50)
        rows = decision.get("rows") or []
        require(bool(rows), "no Radar decision rows")
        require(decision.get("build_locked") is True, "BUILD lock weakened")

        cohort1 = build_validation_cohort(rows, save=True)
        pair_ids1 = [str(p.get("pair_id")) for p in cohort1.get("matched_pairs", []) or []]
        cohort2 = build_validation_cohort(rows, save=True)
        pair_ids2 = [str(p.get("pair_id")) for p in cohort2.get("matched_pairs", []) or []]
        require(pair_ids1 == pair_ids2, "real validation cohort is not idempotently frozen")
        require(cohort2.get("selection_snapshot_frozen") is True, "real cohort not frozen")
        require(cohort2.get("market_truth_claimed") is False, "cohort fabricated market truth")
        require(cohort2.get("predictive_accuracy_claimed") is False, "cohort fabricated accuracy")

        founder = await build_founder_daily_surface(limit=10, save_snapshot=True)
        require(bool(founder.get("cards")), "Founder Daily produced no cards")
        require((founder.get("quality") or {}).get("status") == "PASS", "Founder Daily quality failed")
        vc = founder.get("validation_cohort") or {}
        require(vc.get("selection_snapshot_frozen") is True, "Founder surface lost frozen cohort truth")

        closure = market_closure_readiness()
        require(closure.get("ready_for_first_real_result") is True, "market closure pipeline not ready for first real result")
        require(closure.get("unregistered_result_bypass_allowed") is False, "market result bypass reopened")

        calibration = calibration_report()
        prospective = calibration.get("prospective_controls") or {}
        require(prospective.get("selection_snapshot_frozen") is True, "calibration lost frozen control truth")
        require(prospective.get("outcomes_compared", 0) == 0, "calibration fabricated comparative outcomes")
        require(prospective.get("clean_outcomes_compared", 0) == 0, "calibration fabricated clean comparative outcomes")
        completed = int(calibration.get("completed_experiments", 0) or 0)
        if completed < 10:
            require((calibration.get("credibility") or {}).get("status") == "UNVALIDATED", "calibration overclaimed credibility")

        replay = await run_historical_replay(cutoff=datetime.utcnow() - timedelta(days=30), save_report=True)
        require(replay.get("policy_mode") == "CURRENT_POLICY_ON_HISTORICAL_EVIDENCE", "replay policy mode changed dishonestly")
        require(replay.get("policy_frozen_to_cutoff") is False, "replay fabricated historical policy fidelity")
        require(replay.get("predictive_accuracy") == "UNVALIDATED", "replay fabricated predictive accuracy")
        require((replay.get("forward_policy_recording") or {}).get("forward_recording_ready") is True, "forward policy recording not ready")

        repair_after = await repair_ledger_state_from_validated_links()
        final_decision = await run_opportunity_decision(limit=50)
        quality_after = await audit_quality(decision=final_decision)
        require(quality_after.get("status") == "PASS" and quality_after.get("critical_count", 0) == 0, "M14 quality regression")

        audit = await run_system_wide_audit()
        require(audit.get("percentages_auto_advanced") is False, "M14 audit auto-inflated percentages")
        require((audit.get("quality") or {}).get("status") == "PASS", "M14 system audit quality failed")
        areas = audit.get("areas") or {}
        required_areas = {
            "Data Sources / Crawlers","Source Coverage / Health","Problem Discovery","C02 Recurrence / Same Problem","C03 Pain Materiality",
            "Evidence Ledger","Evidence Integrity / Quality Guard","C05 Buyer Reality","C06 Current Solution","C07 Unresolved Gap","C08 Differentiation",
            "C09 Execution Reality","C10 Distribution","C11 Economics / WTP","C12 Opportunity Window","C13 Competition","C14 Switching","Decision Engine",
            "Research Controller","Scheduler / Research Portfolio","Founder Daily Radar","VALIDATE -> Market Test","Market Result -> Evidence -> Decision",
            "Historical Replay Engine","Calibration Infrastructure","Live Market Calibration","Predictive Accuracy",
        }
        require(required_areas <= set(areas), "M14 audit missing tracked areas")

        rollback_needed = False

        print("STATIC / SURFACE")
        print(f"  Python={symbols['checked_python_files']} undefined_globals=0 | API={api_contract['status']} routes={api_contract['checked']} | frontend={frontend['status']}")
        print("PURE BEHAVIOR")
        print(f"  status={pure['status']} discovery/cache/scraper/solution/cohort/replay/market contracts=PASS")
        print("C02 / LEDGER / QUALITY")
        print(f"  recurrence cases={recurrence.get('cases', 0)} docs={recurrence.get('documents', 0)} llm_calls=0 | repair={repair.get('changed_claims',0)}->{repair_after.get('changed_claims',0)}")
        print(f"  quality {quality_before.get('status')} -> {quality_after.get('status')} critical={quality_after.get('critical_count',0)}")
        print("VALIDATION / MARKET CLOSURE")
        print(f"  matched={len(cohort2.get('matched_pairs',[]) or [])} clean={cohort2.get('clean_matched_pairs',0)} contaminated={cohort2.get('contaminated_pairs',0)} frozen={cohort2.get('selection_snapshot_frozen')}")
        print(f"  market_closure_ready={closure.get('ready_for_first_real_result')} preregistration={closure.get('preregistration_required')} bypass_allowed={closure.get('unregistered_result_bypass_allowed')}")
        print("REPLAY / CALIBRATION")
        print(f"  replay={replay.get('policy_mode')} forward_recording_ready={(replay.get('forward_policy_recording') or {}).get('forward_recording_ready')} predictive_accuracy={replay.get('predictive_accuracy')}")
        print(f"  calibration={(calibration.get('credibility') or {}).get('status')} clean_controls={prospective.get('clean_matched_pairs',0)} outcomes_compared={prospective.get('outcomes_compared',0)}")
        print("\nSIGNALFORGE_M14_ACCEPTANCE_PASS")
        print("Next: python run_radar_cycle.py ; then python show_signalforge_full_system_audit.py")
        print("=" * 126)
    except Exception:
        if rollback_needed:
            restored = await rollback_quality_snapshot(snapshot)
            print("\nM14 ACCEPTANCE FAILED — quality snapshot rollback executed")
            print("  rollback:", restored)
        raise


if __name__ == "__main__":
    asyncio.run(main())
