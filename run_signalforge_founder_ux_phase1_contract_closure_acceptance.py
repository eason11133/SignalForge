from __future__ import annotations

from processors.signalforge_founder_view_models import (
    build_discussion_context,
    build_founder_hypothesis_opportunity_view,
    build_handoff_preview,
    build_lineage_review,
    build_opportunity_list_view,
    build_published_opportunity_view,
    build_today_view,
)

PASS=0; FAIL=0

def check(name, cond, detail=None):
    global PASS,FAIL
    if cond:
        PASS+=1; print(f"PASS  {name}" + (f" — {detail}" if detail is not None else ""))
    else:
        FAIL+=1; print(f"FAIL  {name}" + (f" — {detail}" if detail is not None else ""))

# 1. Compatibility is not canonical lineage.
compat = build_lineage_review({"status":"MATCHED","confidence":0.92,"problem_semantic_compatibility":0.9,"workflow_compatibility":0.9})
canon = build_lineage_review({"status":"CANONICAL_LINEAGE_MATCH","confidence":1.0,"published_thesis_id":"pth-rfq","problem_lineage_id":"pl-proc","canonical_binding_id":"bind-rfq-1"})
check("1.lineage_match_requires_canonical_identity", compat["state"]=="COMPATIBLE_PUBLISHED_EVIDENCE" and not compat["allow_truth_inheritance"] and canon["state"]=="CANONICAL_MATCH" and canon["allow_truth_inheritance"])

# 2. Founder hypothesis canonical match resolves to one Published opportunity home.
fh = build_founder_hypothesis_opportunity_view({
    "hypothesis_id":"fh-rfq","title":"RFQ Quote Comparator",
    "last_probe": {"fast_probe":{"coverage":"COMPLETE_FOR_CONFIGURED_FAST_SOURCES","problem_discussions":1,"firsthand_pain":1},
        "published_money_trail":{"published_thesis_match":{"status":"CANONICAL_LINEAGE_MATCH","published_thesis_id":"pth-rfq","problem_lineage_id":"pl-proc","canonical_binding_id":"bind-rfq-1"}},
        "decision_frontier":{"next_mode":"EXISTING_THESIS_REVIEW","question":"是否確認為同一問題族群？"}}
})
pub = build_published_opportunity_view(
    {"thesis_id":"pth-rfq","title":"Procurement Quote Normalization","problem_lineage_id":"pl-proc"},
    {"buyer_segment":{"segment":"Procurement"},"current_spend":{"status":"UNKNOWN"},"paid_dissatisfaction":{"status":"UNKNOWN","count":0},"revenue_wedge":{"buyer_reachability":"UNKNOWN"}},
    {"thesis_id":"pth-rfq","founder_action":"INVESTIGATE"},
)
listed = build_opportunity_list_view([fh,pub])
check("2.canonical_opportunity_has_one_home", fh["opportunity_id"]==pub["opportunity_id"] and fh["alias_of"]==pub["opportunity_id"] and listed["count"]==1, listed)

# 3. Owner and Founder attention are distinct: PARK must not enter Today.
parked = build_published_opportunity_view(
    {"thesis_id":"park-1","title":"Parked","problem_lineage_id":"pl-park"},
    {"current_spend":{"status":"UNKNOWN"},"paid_dissatisfaction":{"status":"UNKNOWN","count":0},"revenue_wedge":{"buyer_reachability":"UNKNOWN"}},
    {"thesis_id":"park-1","founder_action":"PARK"},
)
today_park = build_today_view([parked])
check("3.owner_is_not_attention", parked["owner"]["state"]=="FOUNDER" and parked["requires_founder_action"] is False and today_park["items"]==[], today_park)

# 4. Today ranking is canonical attention priority, never input ordering.
low=[]
for i,prio in enumerate((10,20,30),1):
    low.append(build_published_opportunity_view(
        {"thesis_id":f"low-{i}","title":f"Low {i}","problem_lineage_id":f"pl-low-{i}"},
        {"current_spend":{"status":"UNKNOWN"},"paid_dissatisfaction":{"status":"UNKNOWN","count":0},"revenue_wedge":{"buyer_reachability":"UNKNOWN"}},
        {"thesis_id":f"low-{i}","founder_action":"VALIDATE_DISTRIBUTION","attention":{"attention_state":"NEEDS_FOUNDER_INPUT","requires_founder_action":True,"attention_priority":prio,"inbox_reason":"需要確認一件事。","attention_event_id":f"evt-low-{i}"}},
    ))
high = build_published_opportunity_view(
    {"thesis_id":"high","title":"ACTION NOW","problem_lineage_id":"pl-high"},
    {"current_spend":{"status":"STRONG"},"paid_dissatisfaction":{"status":"FOUND","count":2},"revenue_wedge":{"buyer_reachability":"KNOWN"}},
    {"thesis_id":"high","founder_action":"ACTION_NOW"},
)
today_ranked=build_today_view([*low,high])
check("4.today_uses_priority_not_input_order", today_ranked["items"][0]["opportunity_id"]==high["opportunity_id"] and high["opportunity_id"] in {x["opportunity_id"] for x in today_ranked["items"]}, today_ranked)

# 5. Founder-facing copy cannot leak known English backend prose/enums.
lang = build_published_opportunity_view(
    {"thesis_id":"health","title":"Healthcare Claims","problem_lineage_id":"pl-health"},
    {"buyer_segment":{"segment":"Healthcare operations"},"current_spend":{"status":"STRONG"},"paid_dissatisfaction":{"status":"FOUND","count":4},"revenue_wedge":{"buyer_reachability":"WEAK"}},
    {"thesis_id":"health","founder_action":"PARK_OR_PARTNER","founder_actionability":{"reason":"Trust/domain/buyer access does not fit the Founder."},"decision_frontier":{"question":"Can the Founder reach a trusted channel?","kill_if":"No credible access path."}},
)
check("5.founder_language_boundary", "Trust/domain" not in lang["why"] and lang["money"]["paid_dissatisfaction"]["label"]=="有證據" and lang["decision_frontier"]["question"]=="你能不能透過可信管道接觸到真正的目標買家？", lang)

# 6. ChatGPT context separates thesis identity from immutable snapshot identity.
no_snapshot = build_discussion_context(lang)
with_snapshot_view = build_published_opportunity_view(
    {"thesis_id":"snap-thesis","title":"Snapshot Thesis","problem_lineage_id":"pl-snap","published_snapshot_id":"snap-20260906-001","published_revision":21},
    {"current_spend":{"status":"UNKNOWN"},"paid_dissatisfaction":{"status":"UNKNOWN","count":0},"revenue_wedge":{"buyer_reachability":"UNKNOWN"}},
    {"thesis_id":"snap-thesis","founder_action":"INVESTIGATE"},
)
with_snapshot=build_discussion_context(with_snapshot_view)
check("6.snapshot_identity_is_not_thesis_id", no_snapshot["published_thesis_id"]=="health" and no_snapshot["published_snapshot_id"] is None and with_snapshot["published_snapshot_id"]=="snap-20260906-001" and with_snapshot["published_revision"]==21)

# 7. Eason One reservation has stable future Work Contract slots without runtime side effects.
handoff=build_handoff_preview(opportunity_view=high, market_test={"market_test_id":"mt-1","test":"做出 upload-first prototype","why":"驗證真實使用","deliverable":"可操作 prototype","deadline":"2026-09-10","must_verify":["PDF parsing"],"constraints":["不要做 ERP"],"max_cost":{"amount":3000,"currency":"TWD"}})
required=("why","deliverable","deadline","must_verify","constraints","source_opportunity_id","source_market_test_id")
check("7.eason_reservation_contract_complete", all(k in handoff for k in required) and handoff["runtime_integration_available"] is False and handoff["status"]=="RESERVED_NOT_EXECUTABLE", handoff)

print('-'*96)
print(f"RESULT: {PASS}/{PASS+FAIL} PASS")
if FAIL: raise SystemExit(1)
print("FINAL_STATUS: SIGNALFORGE_FOUNDER_UX_PHASE1_CONTRACT_CLOSURE_ACCEPTANCE_PASS")
