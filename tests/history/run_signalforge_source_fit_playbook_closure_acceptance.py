from __future__ import annotations

import sys, types

def _stub_database():
    db_pkg = sys.modules.setdefault("database", types.ModuleType("database"))
    conn = types.ModuleType("database.connection")
    class Field:
        def in_(self,*_): return self
        def is_(self,*_): return self
    class Dummy:
        id=Field(); candidate_id=Field(); claim_id=Field(); evidence_id=Field(); case_id=Field()
    for name in ("ProblemCandidate","RadarCase","RadarClaim","RadarClaimEvidence","RadarEvidence"):
        setattr(conn,name,Dummy)
    conn.async_session=None
    sys.modules["database.connection"]=conn
    setattr(db_pkg,"connection",conn)

_stub_database()
from processors.signalforge_founder_query_contracts import SOURCE_PROFILE_REGISTRY, source_fit_for_problem_class
from processors.signalforge_founder_idea_loop import build_source_adequacy, build_decision_frontier
from processors.signalforge_money_trail import route_founder_playbook

results=[]
def check(name, cond, detail=None):
    ok=bool(cond); results.append((name,ok,detail)); print(("PASS" if ok else "FAIL"), name, "" if detail is None else "— "+str(detail)); return ok

health=[
    {"source":"HACKER_NEWS_ALGOLIA","status":"SUCCESS","count":0},
    {"source":"STACK_OVERFLOW_API","status":"SUCCESS","count":0},
    {"source":"GITHUB_ISSUES","status":"SUCCESS","count":0},
    {"source":"GITHUB_REPOSITORIES","status":"SUCCESS","count":0},
]

def summary_for(text, *, partial=False):
    sf=source_fit_for_problem_class(text)
    h=list(health)
    coverage="COMPLETE_FOR_CONFIGURED_FAST_SOURCES"
    if partial:
        h[-1]={"source":"GITHUB_REPOSITORIES","status":"FAILED","count":0}
        coverage="PARTIAL"
    base={
        "problem_discussions":0,"firsthand_pain":0,"workarounds":0,"existing_solutions":0,"paid_signals":0,
        "post_purchase_complaints":0,"coverage":coverage,
        "language_coverage":"SUPPORTED_BY_CURRENT_QUERY_BRIDGE","source_health":h,"source_fit":sf,
    }
    base["source_adequacy"]=build_source_adequacy(fresh_summary=base, source_fit=sf)
    return base

def unknown_money(*, buyer_state="UNKNOWN", buyer_label="UNKNOWN", reach="UNKNOWN", spend="UNKNOWN"):
    return {
        "buyer_segment":{"key":"PRIMARY_SEGMENT_UNKNOWN" if buyer_state=="UNKNOWN" else "AI_AGENCY", "label":buyer_label,"state":buyer_state},
        "revenue_wedge":{"existing_spend":spend,"buyer_reality":"UNKNOWN" if buyer_state=="UNKNOWN" else "PARTIAL","unresolved_gap":"UNKNOWN","buyer_reachability":reach},
        "paid_dissatisfaction":{"count":0},
        "problem":"AI agencies repeatedly validate client opportunities before building.",
        "founder_playbook":{},
    }

dev="AI coding agent forgets repository rules after context compaction"
ag="SignalForge — Market Evidence Intelligence for AI Agencies and product studios doing opportunity validation"
ecom="Shopify merchants manually reconcile marketplace orders and app data"

# Source-fit router / source profiles.
dsf=source_fit_for_problem_class(dev); asf=source_fit_for_problem_class(ag); esf=source_fit_for_problem_class(ecom)
check("developer hypothesis routes DEVELOPER_TOOLING", dsf.get("source_profile")=="DEVELOPER_TOOLING", dsf)
check("developer source set is sufficient", dsf.get("source_fit_state")=="SUFFICIENT", dsf)
check("agency hypothesis routes AGENCY_SERVICES", asf.get("source_profile")=="AGENCY_SERVICES", asf)
check("agency developer-heavy source set is insufficient", asf.get("source_fit_state")=="INSUFFICIENT", asf)
check("ecommerce routes ECOMMERCE_OPERATOR", esf.get("source_profile")=="ECOMMERCE_OPERATOR", esf)
check("agency recommended source families are domain-specific", {"AGENCY_SERVICE_PAGES","AGENCY_REVIEWS","FOUNDER_COMMUNITIES","CONSULTING_JOB_POSTS","RESEARCH_TOOL_REVIEWS"}.issubset(set(asf.get("recommended_source_families") or [])), asf)
areg=SOURCE_PROFILE_REGISTRY["AGENCY_SERVICES"]
check("agency query grammar exists", any('market validation' in q for q in areg.get("query_grammar",[])) and any('product strategy' in q for q in areg.get("query_grammar",[])), areg.get("query_grammar"))
check("agency money grammar exists", {"pricing","retainer","discovery sprint","strategy engagement","research package"}.issubset(set(areg.get("money_grammar") or [])), areg.get("money_grammar"))
check("agency paid-dissatisfaction grammar exists", {"manual research","ChatGPT","Perplexity","hard to trust","still manual"}.issubset(set(areg.get("paid_dissatisfaction_grammar") or [])), areg.get("paid_dissatisfaction_grammar"))

# Separate transport / set / fit facts.
asum=summary_for(ag); adeq=asum["source_adequacy"]
check("transport complete is explicit", adeq.get("transport_state")=="TRANSPORT_COMPLETE")
check("source set complete is explicit", adeq.get("source_set_state")=="SOURCE_SET_COMPLETE")
check("source fit is independently insufficient", adeq.get("source_fit_state")=="SOURCE_FIT_INSUFFICIENT")

afront=build_decision_frontier(published_money_trail=unknown_money(), fresh_summary=asum)
check("source fit insufficient does not PARK", afront.get("founder_hypothesis_disposition")=="WAIT_FOR_SOURCE_FIT" and afront.get("next_mode")=="SOURCE_FIT_RESEARCH", afront)
check("source fit insufficient forbids market absence conclusion", "不能因目前 developer-heavy source set 的 0 traces 而 PARK" in str(afront.get("kill_if")), afront.get("kill_if"))
check("source fit insufficient forbids pricing/MVP/unrelated truth research", all(x in (afront.get("do_not_research") or []) for x in ["不要借用 unrelated Published thesis","不要研究價格","不要研究 MVP"]), afront.get("do_not_research"))

# PARK is only legal for complete + fit-sufficient + zero substantive traces.
dsum=summary_for(dev); dfront=build_decision_frontier(published_money_trail=unknown_money(), fresh_summary=dsum)
check("fit-sufficient complete zero traces may PARK", dfront.get("founder_hypothesis_disposition")=="PARK" and dfront.get("next_mode")=="PARK_FOUNDER_HYPOTHESIS", dfront)
partial=summary_for(dev, partial=True); pfront=build_decision_frontier(published_money_trail=unknown_money(), fresh_summary=partial)
check("incomplete source set cannot PARK", pfront.get("founder_hypothesis_disposition")!="PARK", pfront)

# Playbook prerequisite gates — exactly as Founder live spec.
pb_unknown=route_founder_playbook(published_money_trail=unknown_money(), decision_frontier={"founder_hypothesis_disposition":"CONTINUE","question":"Who is the real buyer?","next_mode":"FOUNDER_DISCOVERY"}, source_fit=dsf)
check("unknown buyer blocks playbook", pb_unknown.get("playbook_status")=="BLOCKED" and "BUYER_UNKNOWN" in (pb_unknown.get("blocked_by") or []), pb_unknown)
check("unknown buyer emits no half template", pb_unknown.get("target_count") is None and pb_unknown.get("channels")==[] and pb_unknown.get("opening_message") is None and pb_unknown.get("questions")==[], pb_unknown)

pb_park=route_founder_playbook(published_money_trail=unknown_money(buyer_state="SUPPORTED",buyer_label="AI agencies",reach="SUPPORTED"), decision_frontier={"founder_hypothesis_disposition":"PARK","question":"stop"}, source_fit=dsf)
check("parked hypothesis playbook is not applicable", pb_park.get("playbook_status")=="NOT_APPLICABLE", pb_park)

pb_fit=route_founder_playbook(published_money_trail=unknown_money(buyer_state="PARTIAL",buyer_label="AI agencies",reach="SUPPORTED"), decision_frontier=afront, source_fit=asf)
check("source-fit insufficient blocks playbook", pb_fit.get("playbook_status")=="BLOCKED" and "SOURCE_FIT_INSUFFICIENT" in (pb_fit.get("blocked_by") or []), pb_fit)

pb_reach=route_founder_playbook(published_money_trail=unknown_money(buyer_state="PARTIAL",buyer_label="AI agencies",reach="UNKNOWN"), decision_frontier={"founder_hypothesis_disposition":"CONTINUE","question":"Is the pain recurring?","next_mode":"FOUNDER_DISCOVERY"}, source_fit=dsf)
check("unknown reachability blocks playbook", pb_reach.get("playbook_status")=="BLOCKED" and "REACHABILITY_UNKNOWN" in (pb_reach.get("blocked_by") or []), pb_reach)

ready_money=unknown_money(buyer_state="PARTIAL",buyer_label="AI agencies",reach="SUPPORTED",spend="PARTIAL")
ready_front={"founder_hypothesis_disposition":"CONTINUE","question":"Is this recurring paid pain?","next_mode":"FOUNDER_DISCOVERY","decision_unknown":{"unknown_key":"RECURRING_PAIN","state":"UNKNOWN_NEEDS_FOUNDER_DISCOVERY","owner":"FOUNDER"}}
pb_ready=route_founder_playbook(published_money_trail=ready_money, decision_frontier=ready_front, source_fit=dsf)
check("ready Founder discovery emits complete playbook", pb_ready.get("playbook_status")=="READY" and pb_ready.get("target_count") and pb_ready.get("where_to_find") and pb_ready.get("opening_message") and len(pb_ready.get("questions") or [])==5, pb_ready)
check("ready discovery does not invent payment timing", pb_ready.get("when_to_ask_for_payment") is None, pb_ready)

# Paid validation only after buyer/reachability/frontier prerequisites and a complete existing playbook.
paid_money=unknown_money(buyer_state="SUPPORTED",buyer_label="AI agencies",reach="SUPPORTED",spend="STRONG")
paid_money["founder_playbook"]={"channels":["LinkedIn","Warm referrals","Agency directories"],"questions":["q1","q2","q3","q4","q5"],"outreach_message":"Ask about the last real workflow before pitching.","offer_rule":"Ask for a paid pilot only after current spend + unresolved gap are established.","sample_target":10}
paid_front={"founder_hypothesis_disposition":"CONTINUE","question":"Will a reachable buyer pay?","next_mode":"MARKET_ACTION","decision_unknown":{"unknown_key":"WILLINGNESS_TO_PAY","state":"UNKNOWN_NEEDS_FOUNDER_DISCOVERY","owner":"FOUNDER"}}
pb_paid=route_founder_playbook(published_money_trail=paid_money, decision_frontier=paid_front, source_fit=dsf)
check("paid-ready case emits complete PAID_VALIDATION playbook", pb_paid.get("playbook_status")=="READY" and pb_paid.get("playbook_type")=="PAID_VALIDATION" and pb_paid.get("target_count")==10 and pb_paid.get("when_to_ask_for_payment"), pb_paid)

# Truth / authority invariants.
check("source-fit routing has zero market authority", asf.get("market_truth_writes")==0 and "C01_C14" in str(asf.get("truth_boundary")), asf.get("truth_boundary"))
check("decision frontier never mutates Published thesis", afront.get("published_thesis_disposition_changed") is False, afront)
check("playbook is execution guidance only", "MARKET_TRUTH" in str(pb_ready.get("truth_boundary") or "").upper() or "DOES_NOT_ASSERT" in str(pb_ready.get("truth_boundary") or "").upper(), pb_ready.get("truth_boundary"))

passed=sum(1 for _,ok,_ in results if ok)
print("-"*100)
print(f"RESULT: {passed}/{len(results)} PASS")
if passed != len(results): raise SystemExit(1)
print("FINAL_STATUS: SIGNALFORGE_SOURCE_FIT_PLAYBOOK_GATE_CLOSURE_ACCEPTANCE_PASS")
