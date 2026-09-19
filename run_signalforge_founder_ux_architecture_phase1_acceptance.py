from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent

from processors.signalforge_founder_view_models import (
    architecture_status,
    build_discussion_context,
    build_evidence_inspector_view,
    build_founder_hypothesis_opportunity_view,
    build_handoff_preview,
    build_learning_view,
    build_lineage_review,
    build_market_test_view,
    build_opportunity_list_view,
    build_outcome_view,
    build_published_opportunity_view,
    build_today_view,
    opportunity_id,
    stable_id,
)

PASS = 0
FAIL = 0


def check(name: str, cond: bool, detail=None):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"PASS  {name}" + (f" — {detail}" if detail is not None else ""))
    else:
        FAIL += 1
        print(f"FAIL  {name}" + (f" — {detail}" if detail is not None else ""))


status = architecture_status()
check("phase1.status", status.get("status") == "PASS" and status.get("phase") == "PHASE_1_PRODUCT_VIEW_MODEL")
check("phase1.ten_view_models", len(status.get("view_models") or []) == 10, status.get("view_models"))
check("phase1.frontend_business_logic_forbidden", status.get("frontend_business_logic_allowed") is False)
check("phase1.no_full_chatgpt_requirement", status.get("chatgpt_full_live_integration_required_this_phase") is False)
check("phase1.no_eason_runtime_requirement", status.get("eason_one_runtime_required_this_phase") is False)
check("phase1.zero_market_truth_writes", status.get("market_truth_writes") == 0)

# Stable identity must depend on canonical ids, never title/fuzzy text.
o1 = opportunity_id("FOUNDER_HYPOTHESIS", "fh-canonical-1")
o2 = opportunity_id("FOUNDER_HYPOTHESIS", "fh-canonical-1")
o3 = opportunity_id("FOUNDER_HYPOTHESIS", "fh-canonical-2")
check("identity.deterministic", o1 == o2)
check("identity.distinct_canonical_objects", o1 != o3)
check("identity.types_have_namespaces", stable_id("MARKET_TEST", "ma-1") != stable_id("OUTCOME", "ma-1"))

# Zero-evidence Founder idea must not inherit nearest Published evidence.
founder_zero = {
    "hypothesis_id": "fh-rfq-001",
    "title": "RFQ Quote Comparator",
    "description": "採購團隊手動整理多家供應商報價。",
    "last_probe": {
        "fast_probe": {"coverage": "COMPLETE_FOR_CONFIGURED_FAST_SOURCES", "problem_discussions": 0, "firsthand_pain": 0},
        "published_money_trail": {
            "published_thesis_match": {"status": "NO_MATCH", "candidates_considered": []},
            "buyer_segment": {"segment": "Engineering Team"},
            "current_spend": {"status": "STRONG"},
            "paid_dissatisfaction": {"status": "SUPPORTED", "count": 12},
        },
        "decision_frontier": {
            "next_mode": "PARK_FOUNDER_HYPOTHESIS",
            "question": "限定採購領域後是否仍完全找不到 recurring pain？",
            "today_action": "先停，不做 generic research",
            "kill_if": "限定採購領域查證後仍無 recurring pain",
        },
    },
}
zero_view = build_founder_hypothesis_opportunity_view(founder_zero)
check("zero_evidence.current_call_not_product_build", zero_view["current_call"]["state"] == "PARK")
check("zero_evidence.buyer_unknown", zero_view["money"]["buyer"]["state"] == "UNKNOWN")
check("zero_evidence.spend_unknown", zero_view["money"]["existing_spend"]["state"] == "UNKNOWN")
check("zero_evidence.paid_dissatisfaction_unknown", zero_view["money"]["paid_dissatisfaction"]["state"] == "UNKNOWN")
check("zero_evidence.no_truth_inheritance", zero_view["lineage_review"]["truth_inheritance"] == "NO_TRUTH_INHERITANCE")
check("zero_evidence.founder_provenance_explicit", zero_view["source"]["kind"] == "FOUNDER_HYPOTHESIS" and zero_view["source"]["market_authority"] == "NONE")
check("zero_evidence.same_mental_model_fields", all(k in zero_view for k in ("current_call", "why", "decision_frontier", "next_action", "stop_condition", "owner")))

possible = build_lineage_review({
    "status": "AMBIGUOUS",
    "confidence": 0.64,
    "match_reason": ["workflow overlap"],
    "candidates_considered": [{"title": "Procurement Pre-System"}],
    "problem_semantic_compatibility": 0.8,
    "workflow_compatibility": 0.7,
    "actor_buyer_compatibility": 0.2,
    "economic_job_compatibility": 0.5,
})
check("lineage.possible_review_first_class", possible["state"] == "POSSIBLE_MATCH_REVIEW")
check("lineage.possible_no_inheritance", possible["allow_truth_inheritance"] is False)
check("lineage.review_actions_exist", possible["review_actions"] == ["CONFIRM_SAME_LINEAGE", "KEEP_SEPARATE", "COMPARE_EVIDENCE"])
matched = build_lineage_review({"status": "MATCHED", "confidence": 0.91, "match_reason": ["same workflow", "same buyer"]})
check("lineage.compatible_match_cannot_inherit", matched["state"] == "COMPATIBLE_PUBLISHED_EVIDENCE" and matched["allow_truth_inheritance"] is False)
canonical = build_lineage_review({"status": "CANONICAL_LINEAGE_MATCH", "confidence": 1.0, "published_thesis_id": "ot-1", "problem_lineage_id": "pl-1", "canonical_binding_id": "bind-1"})
check("lineage.canonical_match_can_inherit", canonical["state"] == "CANONICAL_MATCH" and canonical["allow_truth_inheritance"] is True)

# Published thesis: market classification and Founder action are distinct semantics.
thesis = {
    "thesis_id": "ot-health-1",
    "title": "Healthcare Claims Automation",
    "problem_lineage_id": "pl-health",
}
trail = {
    "buyer_segment": {"segment": "Healthcare operations"},
    "current_spend": {"status": "STRONG"},
    "paid_dissatisfaction": {"status": "SUPPORTED", "count": 4},
    "revenue_wedge": {"buyer_reachability": "WEAK"},
}
decision = {
    "thesis_id": "ot-health-1",
    "current_track": "BOTH",
    "market_track": "BOTH",
    "founder_action": "PARK_OR_PARTNER",
    "hard_kill": False,
    "founder_actionability": {"reason": "Trust/domain/buyer access does not fit the Founder."},
    "decision_frontier": {"question": "Can the Founder reach a trusted channel?", "kill_if": "No credible access path."},
}
pub_view = build_published_opportunity_view(thesis, trail, decision)
check("published.actionability_not_market_track", pub_view["current_call"]["state"] == "DO_NOT_INVEST_NOW")
check("published.founder_label_natural_chinese", pub_view["current_call"]["label"] == "現在不適合你投入")
check("published.stable_problem_lineage_id", pub_view["stable_ids"]["problem_lineage_id"] == stable_id("PROBLEM_LINEAGE", "pl-health"))
check("published.owner_founder_for_decision", pub_view["owner"]["state"] == "FOUNDER")

# List and Today are projections over Opportunity, not backend-part navigation.
list_view = build_opportunity_list_view([zero_view, pub_view])
check("list.single_home_per_opportunity", {x["opportunity_id"] for x in list_view["items"]} == {zero_view["opportunity_id"], pub_view["opportunity_id"]})
today = build_today_view([zero_view, pub_view])
check("today.parked_owner_is_not_attention", len(today["items"]) == 0 and zero_view["requires_founder_action"] is False and pub_view["requires_founder_action"] is False, today)
action_view = build_published_opportunity_view(
    {"thesis_id": "ot-action-1", "title": "RFQ Quote Comparator", "problem_lineage_id": "pl-rfq"},
    {"buyer_segment": {"segment": "Procurement"}, "current_spend": {"status": "STRONG"}, "paid_dissatisfaction": {"status": "FOUND", "count": 2}, "revenue_wedge": {"buyer_reachability": "KNOWN"}},
    {"thesis_id": "ot-action-1", "founder_action": "ACTION_NOW", "decision_frontier": {"question": "現在是否值得鎖定一個 paid test？"}},
)
today_action = build_today_view([zero_view, pub_view, action_view])
check("today.action_now_enters_inbox", len(today_action["items"]) == 1 and today_action["items"][0]["opportunity_id"] == action_view["opportunity_id"])
check("today.max_three", len(today_action["items"]) <= 3)

inspector = build_evidence_inspector_view(opportunity_id_value=pub_view["opportunity_id"], supporting=[{"evidence_id": "ev1"}], contradicting=[{"evidence_id": "ev2"}], unknowns=["budget owner"], source_independence=2)
check("evidence.inspector_secondary", inspector["system_details_default_expanded"] is False)
check("evidence.support_and_contradiction_separate", len(inspector["supporting"]) == 1 and len(inspector["contradicting"]) == 1)

market_test = build_market_test_view({"action_id": "ma-18", "status": "PREREGISTERED", "hypothesis": "buyers pay", "target": "10 procurement buyers", "test": "paid pilot", "decision_rule": {"success": "2 paid", "failure": "0 paid"}, "max_cost": {"amount": 3000, "currency": "TWD"}, "max_sample": 10})
check("market_test.stable_id", market_test["market_test_id"] == stable_id("MARKET_TEST", "ma-18"))
check("market_test.locked_projection", market_test["locked"] is True)

outcome = build_outcome_view({"outcome_id": "out-18", "result": "PASS", "derived_counts": {"contacted": 10, "paid": 2}, "supports": ["initial paid behavior"], "does_not_prove": ["switching", "retention"]})
check("outcome.supports_vs_not_proves", outcome["supports"] == ["initial paid behavior"] and "switching" in outcome["does_not_prove"])
learning = build_learning_view({"status": "UNVALIDATED", "independent_market_tests": 3})
check("learning.unvalidated_does_not_change_ranking", learning["can_change_future_ranking"] is False)

discussion = build_discussion_context(pub_view, discussion_packet={"evidence_replay": {"supporting": 2}, "founder_memory": {"decisions": 1}}, active_market_test_id="mt-18")
check("chatgpt.context_uses_opportunity_identity", discussion["opportunity_id"] == pub_view["opportunity_id"])
check("chatgpt.context_is_contract_not_copy", "current_call" in discussion and "decision_frontier" in discussion and "money_summary" in discussion)

handoff = build_handoff_preview(opportunity_view=pub_view, market_test={"market_test_id": "mt-18", "test": "build upload-first prototype", "max_cost": {"amount": 3000, "currency": "TWD"}})
check("eason.reservation_only", handoff["status"] == "RESERVED_NOT_EXECUTABLE" and handoff["runtime_integration_available"] is False)
check("eason.confirmation_required", handoff["confirmation_required"] is True)

# Source/API contract: Phase 1 adds backend projection, not React business logic.
source = (ROOT / "processors/signalforge_founder_view_models.py").read_text(encoding="utf-8")
api = (ROOT / "api/routes/signalforge.py").read_text(encoding="utf-8")
check("source.no_market_truth_writer_import", "market_ground_truth" not in source and "radar_ledger" not in source)
check("source.owner_enum_complete", all(x in source for x in ("SIGNALFORGE", "FOUNDER", "CHATGPT", "EASON_ONE", "MARKET_WAIT")))
check("api.status_endpoint", "'/founder-ux/status'" in api)
check("api.today_endpoint", "'/founder-ux/today'" in api)
check("api.opportunities_endpoint", "'/founder-ux/opportunities'" in api)
check("api.detail_endpoint", "'/founder-ux/opportunities/{opportunity_id}'" in api)

print("-" * 96)
print(f"RESULT: {PASS}/{PASS+FAIL} PASS")
if FAIL:
    raise SystemExit(1)
print("FINAL_STATUS: SIGNALFORGE_FOUNDER_UX_ARCHITECTURE_PHASE1_ACCEPTANCE_PASS")
