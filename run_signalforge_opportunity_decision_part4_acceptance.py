#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
from pathlib import Path

from processors.signalforge_opportunity_decision import (
    ENGINE_VERSION,
    TRACKS,
    ask_signalforge,
    build_decision_item,
    compare_decision_items,
    resource_allocation,
)

ROOT = Path(__file__).resolve().parent


def fixture_thesis(tid: str, title: str, strategic: str, *, zip2: str = "NOT_ZIP2_CLASS", fast: str = "NOT_READY", buyer: str = "SUPPORTED", gap: str = "SUPPORTED", right: str = "SUPPORTED", transition: str = "UNKNOWN", mismatch: str = "UNKNOWN"):
    return {
        "thesis_id": tid,
        "representative_title": title,
        "representative_problem": title + " problem",
        "strategic_track": strategic,
        "classification": "FOUNDER_TEST_READY",
        "zip2_readiness": zip2,
        "claim_states": {"C03":"SUPPORTED","C05":buyer,"C07":gap,"C09":"SUPPORTED","C10":"SUPPORTED","C11":"UNKNOWN","C13":"SUPPORTED"},
        "dimensions": {
            "problem_persistence":{"state":"SUPPORTED","basis":"fixture"},
            "transition_strength":{"state":transition,"basis":"fixture"},
            "system_mismatch":{"state":mismatch,"basis":"fixture"},
            "economic_materiality":{"state":"SUPPORTED","basis":"fixture"},
            "workaround_intensity":{"state":"SUPPORTED","basis":"fixture"},
            "buyer_formation":{"state":buyer,"basis":"fixture"},
            "gap_durability":{"state":gap,"basis":"fixture"},
            "asset_accessibility":{"state":"PARTIAL","basis":"fixture"},
            "distribution_leverage":{"state":"SUPPORTED","basis":"fixture"},
            "incumbent_response_power":{"state":"SUPPORTED","basis":"fixture"},
            "captureability":{"state":"SUPPORTED","basis":"fixture"},
            "expansion_surface":{"state":"PARTIAL" if zip2 != "NOT_ZIP2_CLASS" else "UNKNOWN","basis":"fixture"},
        },
        "structural_thesis":{"problem":title+" problem","transition":"fixture transition" if zip2 != "NOT_ZIP2_CLASS" else None,"wedge_type":"STRUCTURAL_TRANSITION" if zip2 != "NOT_ZIP2_CLASS" else "PROVEN_MARKET_WEDGE"},
        "founder_addressability": {
            "trust_burden":"LOW_TO_MEDIUM","learning_distance":"LOW","domains":["DEVTOOLS_AI"],"blocking_unknowns":[],
            "dimensions": {
                "task_capability":{"state":"SUPPORTED","basis":"fixture"},
                "domain_knowledge":{"state":"PARTIAL","basis":"fixture"},
                "buyer_access":{"state":"SUPPORTED","basis":"fixture"},
                "legitimacy":{"state":"SUPPORTED","basis":"fixture"},
                "bridgeability":{"state":"SUPPORTED","basis":"fixture"},
                "right_to_win":{"state":right,"basis":"fixture"},
            },
        },
        "fast_validation":{"state":fast,"market_action_candidate":fast in {"READY","RESEARCH_READY"},"falsification_cost_class":"LOW_OR_BOUNDED" if fast in {"READY","RESEARCH_READY"} else "UNKNOWN"},
        "best_next_action":{"mode":"MARKET_ACTION" if fast == "READY" else ("RESEARCH" if fast == "RESEARCH_READY" else "HOLD"),"action":"BOUNDED_CUSTOMER_TEST" if fast == "READY" else "FIND_DECISION_EVIDENCE","reason":"fixture route"},
        "best_next_evidence":{"dimension":"economic_materiality","action":"FIND_DIRECT_EVIDENCE"},
        "market_validation":{"status":"UNVALIDATED"},
    }


def fixture_trail(tid: str, title: str, decision: str, spend: str, pd: int, *, evidence: int = 8, buyer: str = "SUPPORTED", gap: str = "SUPPORTED"):
    return {
        "thesis_id": tid,"title":title,"problem":title+" problem","published_evidence_count":evidence,
        "claim_states":{"C03":"SUPPORTED","C05":buyer,"C07":gap,"C09":"SUPPORTED","C11":"UNKNOWN","C13":"SUPPORTED"},
        "revenue_wedge":{"decision":decision,"existing_spend":spend,"buyer_reachability":"STRONG","paid_dissatisfaction_count":pd},
        "paid_dissatisfaction":{"count":pd,"items":[]},
        "decision_frontier":{"question":"What one observation changes the decision next?","next_mode":"MARKET_ACTION" if decision=="TRY_NOW" else "RESEARCH"},
    }


both_t = fixture_thesis("both","Agency reconciliation","BOTH",zip2="ZIP2_CANDIDATE",fast="READY",transition="SUPPORTED",mismatch="SUPPORTED")
cash_t = fixture_thesis("cash","RFQ comparator","FAST_VALIDATION",fast="RESEARCH_READY")
zip_t = fixture_thesis("zip","Agent authority","ZIP2_STRUCTURAL",zip2="ZIP2_CANDIDATE",fast="NOT_READY",transition="SUPPORTED",mismatch="SUPPORTED")
park_t = fixture_thesis("park","Generic AI wrapper","NEITHER",fast="NOT_READY",buyer="UNKNOWN",gap="UNKNOWN")

both = build_decision_item(both_t, fixture_trail("both","Agency reconciliation","TRY_NOW","STRONG",3,evidence=12))
cash = build_decision_item(cash_t, fixture_trail("cash","RFQ comparator","INVESTIGATE","PARTIAL",1,evidence=9))
zip2 = build_decision_item(zip_t, fixture_trail("zip","Agent authority","NOT_NOW","UNKNOWN",0,evidence=7))
park = build_decision_item(park_t, fixture_trail("park","Generic AI wrapper","NOT_NOW","UNKNOWN",0,evidence=6,buyer="UNKNOWN",gap="UNKNOWN"))
items=[both,cash,zip2,park]
comp=compare_decision_items(items,cash_need="HIGH",long_term="HIGH")
alloc=resource_allocation(comp,weekly_hours=10,cash_need="HIGH",long_term="HIGH")
ask_cash=ask_signalforge("哪些方向現在有第一筆錢 evidence？",comp)
ask_zip=ask_signalforge("哪些 ZIP2 長期方向值得 watch？",comp)
ask_watch=ask_signalforge("什麼時候要重新看 PARK 的題目？",comp)

checks = {
    "engine.version": ENGINE_VERSION.endswith("part4-v1"),
    "tracks.enum": tuple(TRACKS) == ("CASH","BOTH","ZIP2","PARK"),
    "tracks.both": both["current_track"] == "BOTH",
    "tracks.cash": cash["current_track"] == "CASH",
    "tracks.zip2": zip2["current_track"] == "ZIP2",
    "tracks.park": park["current_track"] == "PARK",
    "canonical.not_overwritten": both["canonical_strategic_track"] == "BOTH" and cash["canonical_strategic_track"] == "FAST_VALIDATION",
    "founder_fit.exposed": both["founder_fit"]["dimensions"]["buyer_access"]["state"] == "SUPPORTED",
    "founder_fit.no_market_authority": "OBJECTIVE_MARKET" in both["founder_fit"]["truth_boundary"],
    "structural_mapper.exposed": any(x["dimension"] == "transition_strength" and x["state"] == "SUPPORTED" for x in zip2["structural_mapper"]["dimensions"]),
    "structural_mapper.no_invention": "NO_STRUCTURAL_FACT_IS_INVENTED" in zip2["structural_mapper"]["truth_boundary"],
    "wedge_ladder.paid_outcome_unknown": next(x for x in both["wedge_ladder"]["stages"] if x["stage"]=="REAL_PAID_OUTCOME")["state"] == "UNKNOWN",
    "wedge_ladder.market_only": both["wedge_ladder"]["paid_outcome_authority"] == "REAL_MARKET_OUTCOME_ONLY",
    "part3.disposition_used": both["part3_disposition"]["current_disposition"] == "ADVANCE",
    "rank.top_both": comp["top"]["thesis_id"] == "both",
    "rank.no_opaque_score": all("score" not in x for x in comp["items"]),
    "rank.method_transparent": comp["ranking_method"] == "TRANSPARENT_LEXICOGRAPHIC_RULES_NO_OPAQUE_TOTAL_SCORE",
    "rank.change_explanation": bool(cash["what_changes_rank"]),
    "do_not_research.market_action": any(x["topic"] == "MORE_GENERIC_DESK_RESEARCH" for x in both["do_not_research"]),
    "trigger.zip2_promote_to_both": any(x.get("to") == "BOTH" for x in zip2["promotion_demotion_watch"]["promote_if"]),
    "trigger.cash_structural_watch": any(x.get("trigger") == "STRUCTURAL_TRANSITION" for x in cash["promotion_demotion_watch"]["watch_for"]),
    "trigger.not_auto_truth": "DO_NOT_AUTO_PROMOTE_OR_DEMOTE_TRUTH" in zip2["promotion_demotion_watch"]["truth_boundary"],
    "resource.advisory_only": alloc["advisory_only"] is True,
    "resource.within_budget": alloc["allocated_hours"] <= 10 and alloc["unallocated_hours"] >= 0,
    "resource.has_cash_time": any(x["bucket"] == "CASH_VALIDATION" and x["hours"] > 0 for x in alloc["allocations"]),
    "resource.has_zip_watch": any(x["bucket"] == "ZIP2_WATCH" for x in alloc["allocations"]),
    "ask.cash_bounded": ask_cash["intent"] == "CASH" and all(x["current_track"] in {"CASH","BOTH"} for x in ask_cash["matches"]),
    "ask.zip2_bounded": ask_zip["intent"] == "ZIP2" and all(x["current_track"] in {"ZIP2","BOTH"} for x in ask_zip["matches"]),
    "ask.watch": ask_watch["intent"] == "WATCH" and bool(ask_watch["matches"]),
    "ask.no_llm_truth": "DOES_NOT_USE_FREEFORM_LLM_TEXT_TO_CREATE_MARKET_FACTS" in ask_cash["truth_boundary"],
    "truth.zero_writes_items": all(x["market_truth_writes"] == 0 for x in items),
    "truth.zero_writes_compare": comp["market_truth_writes"] == 0,
}

# Ensure pure projection functions did not mutate canonical fixture input.
base=fixture_thesis("immut","Immutable","FAST_VALIDATION",fast="READY")
before=json.dumps(base,sort_keys=True)
_ = build_decision_item(base, fixture_trail("immut","Immutable","TRY_NOW","STRONG",2))
checks["truth.input_not_mutated"] = before == json.dumps(base,sort_keys=True)

# Source wiring: actual product files, not README-only acceptance.
api=(ROOT/"api/routes/signalforge.py").read_text(encoding="utf-8")
client=(ROOT/"dashboard/src/api/client.ts").read_text(encoding="utf-8")
hooks=(ROOT/"dashboard/src/api/hooks.ts").read_text(encoding="utf-8")
app=(ROOT/"dashboard/src/App.tsx").read_text(encoding="utf-8")
sidebar=(ROOT/"dashboard/src/components/Sidebar.tsx").read_text(encoding="utf-8")
page=(ROOT/"dashboard/src/pages/DecisionSystem.tsx").read_text(encoding="utf-8")
checks.update({
    "source.api_portfolio": "'/decision/portfolio'" in api and "build_opportunity_decision_portfolio" in api,
    "source.api_compare": "'/decision/compare'" in api and "compare_theses" in api,
    "source.api_ask": "'/decision/ask'" in api and "ask_current_signalforge" in api,
    "source.api_watch": "'/decision/watch'" in api,
    "source.client": "signalforgeDecisionPortfolio" in client and "compareSignalForgeDecisions" in client and "askSignalForgeDecision" in client,
    "source.hooks": "useSignalForgeDecisionPortfolio" in hooks and "useCompareSignalForgeDecisions" in hooks and "useAskSignalForgeDecision" in hooks,
    "source.page": "Founder Resource Allocation" in page and "Trigger Watch" in page and "What changes the ranking" in page and "Do Not Research" in page,
    "source.no_unused_textof_helper": "const textOf" not in page,
    "source.route": 'path="decide"' in app,
    "source.sidebar": 'to: "/decide"' in sidebar and "選哪個做" in sidebar,
})

failed=[]
for name,ok in checks.items():
    print(("PASS" if ok else "FAIL").ljust(6),name)
    if not ok: failed.append(name)
print("\nSUMMARY",len(checks)-len(failed),"/",len(checks),"PASS")
if failed:
    print("FAILED:",", ".join(failed))
    raise SystemExit(1)
print("Part 4 product logic acceptance PASS: fixture portfolio exercises CASH/BOTH/ZIP2/PARK, Founder Fit, Structural Mapper, Wedge Ladder, Compare, Trigger Watch, resource allocation and bounded Ask without Market Truth writes.")
