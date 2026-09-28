from __future__ import annotations

import json
import py_compile
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def check(name: str, value: bool, details: str = "") -> tuple[str, bool, str]:
    return name, bool(value), details


def main() -> int:
    results: list[tuple[str, bool, str]] = []

    # Import-safe, no-DB deterministic contracts.
    from processors.signalforge_strategic_rebase import static_acceptance as strategic_acceptance
    from processors.signalforge_calibration_domains import static_acceptance as calibration_acceptance
    from processors.structural_validation_registry import static_acceptance as structural_acceptance
    from api.signalforge_founder_precision_closure import _community_precision, _opportunity_precision, _research_state_precision

    for prefix, report in (
        ("strategic", strategic_acceptance()),
        ("calibration", calibration_acceptance()),
        ("structural_registry", structural_acceptance()),
    ):
        for key, value in report.items():
            results.append(check(f"{prefix}.{key}", bool(value)))

    # Precision closure regression: zero same-problem evidence is legal.
    candidate = {
        "id": 253,
        "problem_statement": "Claude Code assumptions cause incorrect reporting",
        "failure_mode": "assumptions produce wrong reported numbers",
        "task": "verify coding-agent reports",
        "object": "Claude Code",
        "consequence": "days of wasted work",
        "community_evidence_count": 2,
        "community_user_count": 2,
        "community_problem_score": 90,
        "evidence": [
            {"id": 1, "relation": "community_problem", "title": "Change account email", "excerpt": "cannot update account email", "source_ref": "a"},
            {"id": 2, "relation": "community_problem", "title": "Sandbox security", "excerpt": "sandbox permissions discussion", "source_ref": "b"},
        ],
    }
    filtered = _community_precision(candidate)
    results.append(check("precision.zero_same_problem_is_valid", filtered.get("community_evidence_count") == 0, json.dumps(filtered.get("founder_grouping_precision"))))

    # C05 generic related hiring context cannot support a thesis; narrow DIRECT may.
    related = _opportunity_precision({
        "candidate_id": 253,
        "claim_states": {"C05": "SUPPORTED"},
        "current_solutions": [],
        "published_evidence": [{"claim_code":"C05","stance":"SUPPORT","directness":"RELATED","validated":True,"source_title":"AI Architect","excerpt":"generic AI hiring"}],
    })
    direct = _opportunity_precision({
        "candidate_id": 253,
        "claim_states": {"C05": "SUPPORTED"},
        "current_solutions": [],
        "published_evidence": [{"claim_code":"C05","stance":"SUPPORT","directness":"DIRECT","validated":True,"source_title":"Named buyer exact responsibility","excerpt":"exact thesis-aligned budget owner"}],
    })
    results.append(check("precision.related_c05_cannot_support", (related.get("claim_states") or {}).get("C05") == "INSUFFICIENT"))
    results.append(check("precision.direct_c05_can_remain_supported", (direct.get("claim_states") or {}).get("C05") == "SUPPORTED"))

    state = _research_state_precision({
        "status":"NOT_REGISTERED","candidate_id":253,
        "claim_states":{"C05":"INSUFFICIENT","C07":"INSUFFICIENT","C11":"UNKNOWN"},
        "solo_assessment":{"next_gate":"BUYER_REALITY"},
        "best_next_research":None,
    })
    priority = ((state.get("best_next_research") or {}).get("priority") or [])
    results.append(check("precision.research_state_no_cross_request_cache", any(x.get("claim_code") == "C05" for x in priority)))

    # Source-level contracts / authority cutover.
    sources = {
        "precision": (ROOT / "api/signalforge_founder_precision_closure.py").read_text(encoding="utf-8"),
        "route": (ROOT / "api/routes/signalforge.py").read_text(encoding="utf-8"),
        "candidate_engine": (ROOT / "processors/problem_candidate_engine.py").read_text(encoding="utf-8"),
        "buyer": (ROOT / "processors/research_orchestrator.py").read_text(encoding="utf-8"),
        "opportunity_reality": (ROOT / "processors/opportunity_reality.py").read_text(encoding="utf-8"),
        "controller": (ROOT / "processors/research_controller.py").read_text(encoding="utf-8"),
        "main": (ROOT / "api/main.py").read_text(encoding="utf-8"),
        "front_main": (ROOT / "dashboard/src/main.tsx").read_text(encoding="utf-8"),
        "app": (ROOT / "dashboard/src/App.tsx").read_text(encoding="utf-8"),
        "research_ui": (ROOT / "dashboard/src/pages/Research.tsx").read_text(encoding="utf-8"),
        "search_ui": (ROOT / "dashboard/src/pages/SearchPage.tsx").read_text(encoding="utf-8"),
        "system_ui": (ROOT / "dashboard/src/pages/System.tsx").read_text(encoding="utf-8"),
    }
    results.extend([
        check("source.precision_cache_removed", "_CACHE" not in sources["precision"]),
        check("source.problem_candidate_counts_same_problem_posts", '"community_evidence_count": len(same_posts)' in sources["candidate_engine"]),
        check("source.problem_candidate_zero_is_valid", '"zero_is_valid": True' in sources["candidate_engine"]),
        check("source.generic_buyer_retrieval_remains_insufficient", 'Generic market retrieval is candidate/context generation only.' in sources["opportunity_reality"] and 'stance = "INSUFFICIENT"' in sources["opportunity_reality"]),
        check("source.narrow_buyer_support_can_be_direct", 'directness=("DIRECT" if stance == "SUPPORT" else "RELATED")' in sources["buyer"]),
        check("source.radar_controller_not_founder_authority", '"founder_next_action": "BRAIN_V2_STRATEGIC_ACTION_QUEUE"' in sources["controller"]),
        check("source.db_failure_is_503", 'status_code=503' in sources["main"] and 'PRODUCTION_DATABASE_UNAVAILABLE' in sources["main"]),
        check("source.healthz_exists", '@app.get("/healthz")' in sources["main"]),
        check("ui.legacy_candidate_decision_queue_retired", 'import "./signalforgeFounderDecisionQueueV3"' not in sources["front_main"]),
        check("ui.thesis_detail_is_canonical_route", 'path="theses/:id"' in sources["app"] and (ROOT / "dashboard/src/pages/ThesisDetail.tsx").exists()),
        check("ui.research_is_opportunity_bound", 'Opportunity-bound Research Workspace' in sources["research_ui"] and 'Create research project' not in sources["research_ui"]),
        check("ui.search_separates_intelligence_and_corpus", 'Opportunity search ≠ raw corpus search' in sources["search_ui"]),
        check("ui.system_has_split_calibration", 'Structural / Zip2 calibration' in sources["system_ui"] and 'Founder addressability calibration' in sources["system_ui"]),
    ])

    profile = json.loads((ROOT / "config/company_capability_profile.json").read_text(encoding="utf-8"))
    results.append(check("profile.ai_not_domain_credibility", "cannot prove domain knowledge" in str((profile.get("strategic_search_policy") or {}).get("ai_boundary", ""))))
    results.append(check("profile.dual_objective", (profile.get("strategic_search_policy") or {}).get("primary_long_term_objective") == "EASON_ADDRESSABLE_ZIP2_STRUCTURAL" and (profile.get("strategic_search_policy") or {}).get("secondary_short_term_objective") == "EASON_ADDRESSABLE_FAST_VALIDATION"))

    # Compile every changed Python file without importing DB/provider dependencies.
    py_files = [
        "api/main.py", "api/signalforge_founder_precision_closure.py", "api/routes/signalforge.py", "api/routes/signalforge_brain_v2.py",
        "processors/problem_candidate_engine.py", "processors/research_orchestrator.py", "processors/research_controller.py", "processors/founder_daily_surface.py",
        "processors/signalforge_brain_v2_engine.py", "processors/validation_registry.py", "processors/signalforge_strategic_rebase.py",
        "processors/signalforge_calibration_domains.py", "processors/structural_validation_registry.py",
        "create_signalforge_structural_checkpoint.py", "record_signalforge_structural_checkpoint.py",
    ]
    for rel in py_files:
        try:
            py_compile.compile(str(ROOT / rel), doraise=True)
            results.append(check(f"compile.{rel}", True))
        except Exception as exc:
            results.append(check(f"compile.{rel}", False, f"{type(exc).__name__}: {exc}"))

    failed = [r for r in results if not r[1]]
    print("="*110)
    print("SIGNALFORGE FULL-SYSTEM OPPORTUNITY INTELLIGENCE REBASE — NO-DB ACCEPTANCE")
    print("="*110)
    for name, ok, details in results:
        print(f"{'PASS' if ok else 'FAIL':4}  {name}" + (f" :: {details}" if details and not ok else ""))
    print("-"*110)
    print(f"TOTAL={len(results)} PASS={len(results)-len(failed)} FAIL={len(failed)}")
    print("Market calibration is intentionally not promoted by this acceptance.")
    print("="*110)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
