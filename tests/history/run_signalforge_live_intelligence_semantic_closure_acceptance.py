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

from processors.signalforge_founder_query_contracts import source_fit_for_problem_class
from processors.signalforge_founder_idea_loop import (
    build_decision_frontier,
    build_source_adequacy,
    classify_trace_relevance,
    summarize_fresh_probe,
)

results=[]
def check(name, cond, detail=None):
    ok=bool(cond); results.append((name,ok,detail)); print(("PASS" if ok else "FAIL"), name, "" if detail is None else "— "+str(detail)); return ok

DEV_FAMILIES=["HACKER_NEWS","STACK_OVERFLOW","GITHUB_ISSUES","GITHUB_REPOSITORIES"]
HEALTH=[
    {"source":"HACKER_NEWS_ALGOLIA","source_family":"HACKER_NEWS","status":"SUCCESS","count":0},
    {"source":"STACK_OVERFLOW_API","source_family":"STACK_OVERFLOW","status":"SUCCESS","count":0},
    {"source":"GITHUB_ISSUES","source_family":"GITHUB_ISSUES","status":"SUCCESS","count":0},
    {"source":"GITHUB_REPOSITORIES","source_family":"GITHUB_REPOSITORIES","status":"SUCCESS","count":0},
]

def empty_money(problem):
    return {
        "buyer_segment":{"key":"PRIMARY_SEGMENT_UNKNOWN","label":"UNKNOWN","state":"UNKNOWN"},
        "revenue_wedge":{"existing_spend":"UNKNOWN","buyer_reality":"UNKNOWN","unresolved_gap":"UNKNOWN","buyer_reachability":"UNKNOWN"},
        "paid_dissatisfaction":{"count":0},
        "problem":problem,
    }

# A. Exact live source-fit false-positive case.
nonprofit="Productized LINE Bot / Workflow Automation for Small Nonprofits"
np_fit=source_fit_for_problem_class(nonprofit, configured_source_families=DEV_FAMILIES)
check("nonprofit LINE-bot thesis routes to buyer/problem observation profile, not developer tooling", np_fit.get("source_profile")=="NONPROFIT_OPERATIONS", np_fit)
check("developer-heavy configured families do not cover nonprofit observation domain", np_fit.get("source_fit_state")=="INSUFFICIENT" and not np_fit.get("matched_observation_source_families"), np_fit)
np_summary={
    "founder_query":nonprofit,
    "problem_discussions":0,"firsthand_pain":0,"workarounds":0,"existing_solutions":0,"paid_signals":0,"post_purchase_complaints":0,
    "coverage":"COMPLETE_FOR_CONFIGURED_FAST_SOURCES","language_coverage":"SUPPORTED_BY_CURRENT_QUERY_BRIDGE","source_health":HEALTH,"source_fit":np_fit,
}
np_summary["source_adequacy"]=build_source_adequacy(fresh_summary=np_summary, source_fit=np_fit)
check("transport/source-set complete remains separate from source-fit", np_summary["source_adequacy"].get("transport_complete") is True and np_summary["source_adequacy"].get("source_set_complete") is True and np_summary["source_adequacy"].get("source_fit_sufficient") is False, np_summary["source_adequacy"])
np_front=build_decision_frontier(published_money_trail=empty_money(nonprofit), fresh_summary=np_summary)
check("nonprofit 0 traces cannot PARK when observation-source fit is insufficient", np_front.get("founder_hypothesis_disposition")=="WAIT_FOR_SOURCE_FIT" and np_front.get("next_mode")=="SOURCE_FIT_RESEARCH", np_front)
check("source-fit gate does not create market absence or truth", np_fit.get("market_truth_writes")==0 and np_front.get("published_thesis_disposition_changed") is False, np_front)

# Positive control: actual developer observation families are still sufficient for a developer problem.
dev="AI coding agent forgets repository rules after context compaction"
dev_fit=source_fit_for_problem_class(dev, configured_source_families=DEV_FAMILIES)
check("developer thesis still has adequate configured observation families", dev_fit.get("source_profile")=="DEVELOPER_TOOLING" and dev_fit.get("source_fit_state")=="SUFFICIENT" and len(dev_fit.get("matched_observation_source_families") or [])>=2, dev_fit)

# B. Exact live English Output Trainer false-trace case.
eot="English Output Trainer for Taiwan Exam Students"
def tr(title, excerpt, *, pain=(), workaround=(), paid=(), dissatisfaction=()):
    return {
        "source":"GITHUB_ISSUES","kind":"ISSUE","title":title,"excerpt":excerpt,"url":"https://example.invalid/"+title.replace(" ","-"),
        "signals":{"pain":list(pain),"workaround":list(workaround),"paid":list(paid),"dissatisfaction":list(dissatisfaction)},
        "truth_status":"UNVALIDATED_SEARCH_TRACE",
    }

bad=[
    tr("GPTsHunter submission", "I submitted a GPT directory project and the submission form is broken.", pain=("broken",)),
    tr("redditgifts tracking issue", "We manually track redditgifts packages because tracking fails.", pain=("manual","fails"), workaround=("manual",), dissatisfaction=("fails",)),
    tr("Facebook LAMA vocabulary bug", "Vocabulary mapping bug in the Facebook LAMA benchmark.", pain=("bug",)),
]
fresh={
    "founder_query":eot,
    "traces":bad,
    "sources":[
        {"source":"HACKER_NEWS_ALGOLIA","status":"SUCCESS","count":0},
        {"source":"STACK_OVERFLOW_API","status":"SUCCESS","count":0},
        {"source":"GITHUB_ISSUES","status":"SUCCESS","count":3},
        {"source":"GITHUB_REPOSITORIES","status":"SUCCESS","count":0},
    ],
    "language_coverage":"SUPPORTED_BY_CURRENT_QUERY_BRIDGE",
}
s=summarize_fresh_probe(fresh)
check("three unrelated live-like GitHub hits are not substantive problem discussions", s.get("problem_discussions")==0, s)
check("unrelated live-like GitHub hits are not firsthand pain", s.get("firsthand_pain")==0, s)
check("unrelated live-like GitHub hits cannot become workarounds or paid signals", s.get("workarounds")==0 and s.get("paid_signals")==0, s)
check("irrelevant/insufficient traces remain inspectable", s.get("relevant_trace_count")==0 and s.get("irrelevant_trace_count")==3 and len(s.get("inspectable_irrelevant_traces") or [])==3, s.get("trace_relevance"))
check("no irrelevant trace creates spend or paid-dissatisfaction observation", not s.get("spend_observations") and not s.get("paid_dissatisfaction_observations"), s)

# Relevance gate must not over-filter a genuinely compatible trace.
good=tr(
    "Taiwan GSAT student English writing practice is hard",
    "We are Taiwan exam students and we struggle to produce English writing and translation under time pressure.",
    pain=("hard",),
)
good_rel=classify_trace_relevance(hypothesis_text=eot, trace=good)
check("actor + exam-domain + language-output compatible trace is countable", good_rel.get("state")=="RELEVANT" and good_rel.get("countable") is True, good_rel)
with_good=dict(fresh); with_good["traces"]=[*bad,good]
sg=summarize_fresh_probe(with_good)
check("only the compatible trace enters problem-discussion counter", sg.get("problem_discussions")==1 and sg.get("relevant_trace_count")==1 and sg.get("irrelevant_trace_count")==3, sg)
check("only compatible firsthand pain enters pain counter", sg.get("firsthand_pain")==1, sg)

# Counter contract: keyword overlap alone never reaches Decision Frontier.
eot_fit=source_fit_for_problem_class(eot, configured_source_families=DEV_FAMILIES)
s["source_fit"]=eot_fit
s["source_adequacy"]=build_source_adequacy(fresh_summary=s, source_fit=eot_fit)
eot_front=build_decision_frontier(published_money_trail=empty_money(eot), fresh_summary=s)
check("irrelevant GitHub hits cannot push Decision Frontier into buyer/spend research", eot_front.get("founder_hypothesis_disposition")=="WAIT_FOR_SOURCE_FIT" and eot_front.get("next_mode")=="SOURCE_FIT_RESEARCH", eot_front)
check("fresh relevance routing keeps zero Market Truth authority", "MARKET_TRUTH" in str(s.get("truth_boundary") or "").upper() and np_fit.get("market_truth_writes")==0, s.get("truth_boundary"))

passed=sum(1 for _,ok,_ in results if ok)
print("-"*100)
print(f"RESULT: {passed}/{len(results)} PASS")
if passed != len(results): raise SystemExit(1)
print("FINAL_STATUS: SIGNALFORGE_LIVE_INTELLIGENCE_SEMANTIC_CLOSURE_ACCEPTANCE_PASS")
