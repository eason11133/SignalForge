"""Separate mature research constructs used by SignalForge.

SignalForge previously overloaded one object called "opportunity" with customer pain,
external change, market supply, and founder fit. Mature entrepreneurship/market research
keeps these observations conceptually separate. This module materializes separate research
objects without pretending the unresolved cross-object opportunity linkage is solved.
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter
from typing import Any

from processors.opportunity_evidence_atoms import ensure_observation_schema

ENGINE_VERSION = "opportunity-research-objects-u8-need-solution-diffusion-gap"

ENABLER_PATTERNS = {
    "TECHNOLOGY": re.compile(r"\b(?:ai|agent|model|api|automation|open[- ]source|computer vision|voice ai|ocr|robot|released|launched|now supports?|can now)\b", re.I),
    "REGULATION": re.compile(r"\b(?:regulation|law|mandate|compliance|deadline|required|rule|act|directive)\b", re.I),
    "PLATFORM": re.compile(r"\b(?:platform|app store|marketplace|browser|mobile|cloud|social network|payment rail|api now)\b", re.I),
    "COST_CURVE": re.compile(r"\b(?:price cut|cost fell|cheaper|lower cost|commoditi[sz]ed|free tier)\b", re.I),
    "BEHAVIOR": re.compile(r"\b(?:adoption|users now|customers now|shift to|moved to|increasingly use|remote work|online)\b", re.I),
}


def _clean(v: Any) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()


def _ref(o: dict[str, Any]) -> str:
    return f"{o.get('source')}:{o.get('source_table')}:{o.get('source_ref')}"


def _id(prefix: str, *parts: Any) -> str:
    return prefix + "_" + hashlib.sha1("|".join(_clean(x).lower() for x in parts).encode()).hexdigest()[:18]


def enabler_type(o: dict[str, Any]) -> str:
    text = " ".join([_clean(o.get("change_span")), _clean(o.get("title")), _clean(o.get("text"))])
    for kind, pat in ENABLER_PATTERNS.items():
        if pat.search(text):
            return kind
    return "OTHER_CHANGE"


def need_fragment(o: dict[str, Any]) -> dict[str, Any] | None:
    if o.get("evidence_disposition") not in {"DIRECT_NEED", "INCOMPLETE_NEED"}:
        return None
    atom=o.get("evidence_atom") or {}
    return {
        "object_id": _id("need", o.get("observation_id"), atom.get("text")),
        "object_type": "NEED_FRAGMENT",
        "status": "EVIDENCE_FRAGMENT_NOT_OPPORTUNITY",
        "evidence_ref": _ref(o),
        "disposition": o.get("evidence_disposition"),
        "feedback_role": o.get("feedback_role"),
        "source_intent": o.get("source_intent"),
        "source_family": o.get("source_family"),
        "source_ref": o.get("source_ref"),
        "source_role": o.get("source_role"),
        "need_frame": o.get("need_frame") or {},
        "actor": o.get("actor_scope"),
        "workflow": o.get("workflow"),
        "vertical": o.get("vertical"),
        "product_id": o.get("product_id") or None,
        "problem": _clean(o.get("problem_span"))[:1200],
        "workaround": _clean(o.get("current_behavior_span"))[:600] or None,
        "burden": _clean(o.get("burden_span"))[:600] or None,
        "frequency": _clean(o.get("frequency_span"))[:600] or None,
        "legacy_primary_signature": o.get("primary_problem_signature") or None,
        "lexical_terms": list(o.get("problem_lexical_terms") or [])[:18],
    }


def external_enabler(o: dict[str, Any]) -> dict[str, Any] | None:
    if not (o.get("change_explicit") and o.get("change_authority")):
        return None
    span=_clean(o.get("change_span") or o.get("text"))
    return {
        "object_id": _id("enabler", o.get("source_family"), o.get("source_ref"), span),
        "object_type": "EXTERNAL_ENABLER",
        "status": "OBSERVED_CHANGE_NOT_YET_LINKED_TO_VENTURE",
        "enabler_type": enabler_type(o),
        "evidence_ref": _ref(o),
        "span": span[:1200],
        "vertical": o.get("vertical"),
        "workflow": o.get("workflow"),
        "source_role": o.get("source_role"),
    }



def _signal_score(o: dict[str, Any]) -> float:
    text=_clean(o.get("problem_span") or o.get("text"))
    score=1.0
    if re.search(r"\b(?:because\s+i|because\s+we|i\s+hate|i\s+needed|we\s+needed|every\s+time\s+i\s+had\s+to)\b", text, re.I): score+=1.2
    if re.search(r"\b(?:built|made|created|developed|wrote)\b", text, re.I): score+=0.8
    if _clean(o.get("workflow")).lower() not in {"", "other", "unknown"}: score+=0.5
    if bool(o.get("manual_behavior")) or bool(o.get("burden_explicit")) or bool(o.get("frequency_explicit")): score+=0.5
    return round(score,2)


def user_innovation_signal(o: dict[str, Any]) -> dict[str, Any] | None:
    if str(o.get("feedback_role") or "") != "USER_INNOVATION_NEED_SOLUTION":
        return None
    if str(o.get("source_intent") or "") != "SELF_SOLUTION_FOR_OWN_NEED":
        return None
    # User innovation requires a firsthand user/community source.  Employer listings,
    # vendor supply, news and market context may describe internally built solutions,
    # but that is not a user-developed need-solution pair.
    fam=str(o.get("source_family") or o.get("source") or "").lower()
    role=str(o.get("source_role") or "").upper()
    if role!="FIRSTHAND_USER_PAIN" or fam not in {"reddit_rss","reddit","community_raw","hackernews","stackexchange","app_store_reviews"}:
        return None
    text=_clean(o.get("problem_span") or o.get("text"))
    return {
        "object_id":_id("userinnovation",o.get("observation_id"),text),
        "object_type":"USER_INNOVATION_NEED_SOLUTION_SIGNAL",
        "status":"OBSERVED_SELF_SOLUTION_NEEDS_INDEPENDENT_MARKET_CORROBORATION",
        "evidence_ref":_ref(o),
        "text":text[:1400],
        "need_frame":o.get("need_frame") or {},
        "actor":o.get("actor_scope"),"workflow":o.get("workflow"),"vertical":o.get("vertical"),
        "source_family":fam,"source_role":role,"source_intent":o.get("source_intent"),
        "product_id":o.get("product_id") or None,"product_name":o.get("product_name") or None,
        "signal_score":_signal_score(o),
        "need_solution_pair_status":"OBSERVED_SELF_SOLUTION_FOR_OWN_NEED",
        "peer_adoption_status":"UNKNOWN_NOT_YET_EVIDENCED",
        "diffusion_status":"UNKNOWN_NOT_YET_EVIDENCED",
        "commercialization_gap_status":"CANDIDATE_ONLY_NOT_PROVEN",
        "truth_boundary":"A user/maker built something for an expressed own need. This is a Need-Solution signal only; peer adoption, diffusion failure, independent demand, willingness-to-pay, and commercialization gap remain unproven until separately evidenced.",
    }


def solution_supply_signal(o: dict[str, Any]) -> dict[str, Any] | None:
    role=str(o.get("feedback_role") or "")
    if role not in {"SUPPLIER_PITCH","POSITIVE_CAPABILITY"}:
        return None
    text=_clean(o.get("problem_span") or o.get("text"))
    return {
        "object_id":_id("solutionsupply",o.get("observation_id"),text),
        "object_type":"SOLUTION_SUPPLY_SIGNAL",
        "status":"OBSERVED_SOLUTION_CONTEXT_NOT_CUSTOMER_PAIN",
        "feedback_role":role,
        "evidence_ref":_ref(o),
        "text":text[:1400],
        "product_id":o.get("product_id") or None,"product_name":o.get("product_name") or None,
        "workflow":o.get("workflow"),"vertical":o.get("vertical"),
        "truth_boundary":"A solution/capability statement is evidence of solution context only. It is not independent customer pain or buyer willingness-to-pay.",
    }


def policy_context(o: dict[str, Any]) -> dict[str, Any] | None:
    if str(o.get("feedback_role") or "") != "POLICY_OPINION":
        return None
    return {
        "object_id":_id("policy",o.get("observation_id"),o.get("problem_span")),
        "object_type":"POLICY_OPINION_CONTEXT",
        "status":"OBSERVED_NORMATIVE_CONTEXT_NOT_WORKFLOW_PAIN",
        "evidence_ref":_ref(o),
        "text":_clean(o.get("problem_span") or o.get("text"))[:1200],
        "vertical":o.get("vertical"),"workflow":o.get("workflow"),
    }

def employer_demand_signal(o: dict[str, Any]) -> dict[str, Any] | None:
    if str(o.get("feedback_role") or "") != "EMPLOYER_DEMAND_CONTEXT":
        return None
    text=_clean(o.get("problem_span") or o.get("reported_problem_span") or o.get("text"))
    if not text:
        text=_clean((o.get("raw_doc") or {}).get("text"))
    return {
        "object_id":_id("employerdemand",o.get("observation_id"),o.get("source_ref"),text[:200]),
        "object_type":"EMPLOYER_DEMAND_CONTEXT",
        "status":"OBSERVED_HIRING_OR_EMPLOYER_CONTEXT_NOT_USER_DEMAND",
        "evidence_ref":_ref(o),"text":text[:1200],"workflow":o.get("workflow"),"vertical":o.get("vertical"),
        "truth_boundary":"A job/employer record can indicate organizational activity or capability demand, but it is not a user innovation, customer pain recurrence, or willingness-to-pay evidence.",
    }


def market_state(o: dict[str, Any]) -> dict[str, Any] | None:
    fam=str(o.get("source_family") or "").lower()
    # Supply existence is a market-state fact even when the listing is free.  Paid supply
    # remains a separate field and must never be interpreted as buyer WTP.
    if str(o.get("source_role") or "") != "MARKET_SUPPLY" and fam not in {"app_store","market_supply_external"} and not o.get("paid_supply"):
        return None
    return {
        "object_id": _id("market", o.get("product_id"), o.get("source_ref"), o.get("title")),
        "object_type": "MARKET_STATE",
        "status": "OBSERVED_SUPPLY_NOT_BUYER_WTP",
        "evidence_ref": _ref(o),
        "product_id": o.get("product_id") or None,
        "product_name": o.get("product_name") or o.get("title"),
        "vertical": o.get("vertical"),
        "workflow": o.get("workflow"),
        "supply_exists": True,
        "paid_supply": bool(o.get("paid_supply")),
        "commercial_context": bool(o.get("commercial_context_explicit")),
        "truth_boundary": "Observed supply existence is not buyer willingness-to-pay.",
    }


def market_state_from_doc(d: dict[str, Any]) -> dict[str, Any] | None:
    fam=str(d.get("source_family") or "").lower();role=str(d.get("source_role") or d.get("source_role_hint") or "").upper()
    source=str(d.get("source") or "").lower();table=str(d.get("table") or d.get("source_table") or "").lower();name=str(d.get("source_name") or "").lower()
    supply_surface = role=="MARKET_SUPPLY" or fam in {"app_store","market_supply_external","software_supply"} or source in {"market_supply_external","app_store","apple_itunes_search"} or "app_store_apps" in table or "itunes_search" in name
    if not supply_surface:
        return None
    pid=d.get("product_id") or d.get("app_id") or d.get("trackId") or d.get("pk")
    name=d.get("product_name") or d.get("app_name") or d.get("trackName") or d.get("title")
    return {
        "object_id":_id("marketdoc",pid,d.get("pk") or d.get("source_ref"),name),"object_type":"MARKET_STATE",
        "status":"OBSERVED_SUPPLY_NOT_BUYER_WTP","evidence_ref":f"{d.get('source')}:{d.get('table')}:{d.get('pk')}",
        "product_id":pid or None,"product_name":name,"vertical":d.get("vertical") or d.get("app_category") or d.get("category"),
        "workflow":d.get("workflow"),"supply_exists":True,"paid_supply":bool(d.get("paid_supply")),
        "text":_clean(d.get("text") or d.get("description") or name)[:1600],"retrieval_query":_clean(d.get("search_query"))[:500] or None,
        "commercial_context":bool(d.get("commercial_context_explicit")) or bool(d.get("price") or d.get("formatted_price")),"source_contract_match":{"role":role,"family":fam,"source":source,"table":table},
        "truth_boundary":"Observed raw supply document proves supply existence only; it does not prove buyer demand or willingness-to-pay.",
    }


def workflow_context(o: dict[str, Any]) -> dict[str, Any] | None:
    if not (o.get("manual_behavior") or _clean(o.get("workflow")).lower() not in {"", "other"}):
        return None
    if o.get("evidence_disposition") not in {"DIRECT_NEED", "INCOMPLETE_NEED"}:
        return None
    return {
        "object_id": _id("workflow", o.get("observation_id"), o.get("workflow")),
        "object_type": "WORKFLOW_CONTEXT",
        "status": "OBSERVED_WORKFLOW",
        "evidence_ref": _ref(o),
        "actor": o.get("actor_scope"),
        "workflow": o.get("workflow"),
        "vertical": o.get("vertical"),
        "manual_behavior": bool(o.get("manual_behavior")),
        "workaround": _clean(o.get("current_behavior_span"))[:600] or None,
    }


def build_research_objects(observations: list[dict[str, Any]], raw_docs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    needs=[];enablers=[];markets=[];workflows=[];user_innovations=[];solution_signals=[];policy_contexts=[];employer_demand=[]
    role_counts=Counter();intent_counts=Counter();schema_upgraded=0
    migrated=[]
    for raw in observations:
        oldv=raw.get("evidence_schema_version");o=ensure_observation_schema(raw)
        schema_upgraded += int(oldv != o.get("evidence_schema_version"))
        migrated.append(o);role_counts[str(o.get("feedback_role") or "UNRESOLVED")]+=1;intent_counts[str(o.get("source_intent") or "UNRESOLVED")]+=1
    for o in migrated:
        x=need_fragment(o)
        if x:needs.append(x)
        x=external_enabler(o)
        if x:enablers.append(x)
        x=market_state(o)
        if x:markets.append(x)
        x=workflow_context(o)
        if x:workflows.append(x)
        x=user_innovation_signal(o)
        if x:user_innovations.append(x)
        x=solution_supply_signal(o)
        if x:solution_signals.append(x)
        x=policy_context(o)
        if x:policy_contexts.append(x)
        x=employer_demand_signal(o)
        if x:employer_demand.append(x)
    # Market/supply documents can be filtered out by the need-observation parser. Materialize
    # them directly from the source corpus so market state is not accidentally forced through pain parsing.
    if raw_docs:
        existing={str(x.get("evidence_ref") or "") for x in markets}
        for d in raw_docs:
            m=market_state_from_doc(d)
            if m and str(m.get("evidence_ref") or "") not in existing:
                markets.append(m);existing.add(str(m.get("evidence_ref") or ""))
    user_innovations.sort(key=lambda x:float(x.get("signal_score") or 0),reverse=True)
    return {
        "engine_version":ENGINE_VERSION,
        "need_fragments":needs,
        "external_enablers":enablers,
        "market_states":markets,
        "workflow_contexts":workflows,
        "user_innovation_signals":user_innovations,
        "solution_supply_signals":solution_signals,
        "policy_contexts":policy_contexts,
        "employer_demand_signals":employer_demand,
        "counts":{
            "need_fragments":len(needs),"external_enablers":len(enablers),"market_states":len(markets),"workflow_contexts":len(workflows),
            "user_innovation_signals":len(user_innovations),"solution_supply_signals":len(solution_signals),"policy_contexts":len(policy_contexts),"employer_demand_signals":len(employer_demand),
            "need_dispositions":dict(Counter(x.get("disposition") for x in needs)),
            "enabler_types":dict(Counter(x.get("enabler_type") for x in enablers)),
            "feedback_roles":dict(role_counts),"source_intents":dict(intent_counts),"schema_upgraded":schema_upgraded,
        },
        "frontier_boundary":"Need, user-innovation Need-Solution signals, employer demand, solution supply, policy context, external enablers and market states are separate evidence objects. Automatic venture-opportunity linkage remains intentionally not self-certified.",
    }


def static_acceptance() -> dict[str, bool]:
    need={"observation_id":"o1","evidence_disposition":"INCOMPLETE_NEED","feedback_role":"PROBLEM_REPORT","source_role":"FIRSTHAND_USER_PAIN","primary_pain_authority":True,"direct_pain":True,"problem_polarity":"NEGATIVE","problem_target":"PRIMARY_SOURCE_SUBJECT","evidence_atom":{"text":"I retype every booking by hand."},"source":"community","source_family":"reddit_rss","source_table":"r","source_ref":"1","actor_scope":"owner","native_scope":"smallbusiness","workflow":"booking","vertical":"services","problem_span":"I retype every booking by hand.","manual_behavior":True}
    change={"observation_id":"o2","source":"news","source_table":"n","source_ref":"2","change_explicit":True,"change_authority":True,"change_span":"Voice AI is now available through a low-cost API.","text":"Voice AI is now available through a low-cost API.","source_role":"STRUCTURAL_OR_MARKET_CONTEXT","vertical":"services","workflow":"booking"}
    supply={"observation_id":"o3","source":"market_supply_external","source_table":"apps","source_ref":"3","source_role":"MARKET_SUPPLY","paid_supply":True,"product_id":"p","product_name":"Booking Tool","vertical":"services","workflow":"booking"}
    free_supply={"observation_id":"o4","source":"market_supply_external","source_family":"app_store","source_table":"apps","source_ref":"4","source_role":"MARKET_SUPPLY","paid_supply":False,"product_id":"free","product_name":"Free Booking Tool","vertical":"services","workflow":"booking"}
    ui={"observation_id":"o5","source":"community","source_table":"posts","source_ref":"5","feedback_role":"USER_INNOVATION_NEED_SOLUTION","problem_span":"Built a tool to generate slides from research papers because I hate formatting decks.","workflow":"research","vertical":"knowledge_work"}
    pitch={"observation_id":"o6","source":"community","source_table":"posts","source_ref":"6","feedback_role":"SUPPLIER_PITCH","problem_span":"Here's a quick demo. We built this to solve browser automation for companies.","workflow":"automation"}
    positive={"observation_id":"o7","source":"community","source_table":"posts","source_ref":"7","feedback_role":"POSITIVE_CAPABILITY","problem_span":"You can see agent status and don't have to keep watching the dashboard.","workflow":"agent_monitoring"}
    policy={"observation_id":"o8","source":"community","source_table":"posts","source_ref":"8","feedback_role":"POLICY_OPINION","problem_span":"Products that fail regulation should disclose it up front."}
    raw_supply={"source":"market_supply_external","source_family":"app_store","source_role_hint":"MARKET_SUPPLY","table":"apps","pk":"raw1","title":"Raw Tool","app_id":"raw1","app_name":"Raw Tool","app_category":"Business","paid_supply":False}
    common={"source_role":"FIRSTHAND_USER_PAIN","primary_pain_authority":True,"direct_pain":True,"problem_polarity":"NEGATIVE","problem_target":"PRIMARY_SOURCE_SUBJECT","source_family":"reddit_rss","native_scope":"community"}
    ui={**common,**ui};pitch={**common,**pitch};positive={**common,**positive};policy={**common,**policy}
    job={"observation_id":"j1","source":"jobs","source_family":"jobs","source_table":"job_listings","source_ref":"j1","source_role":"HIRING_OR_VENDOR_CONTEXT","feedback_role":"EMPLOYER_DEMAND_CONTEXT","problem_span":"Director of Business Operations - build automation for internal workflows","text":"Director of Business Operations - build automation for internal workflows","workflow":"ops","vertical":"professional_services"}
    bad_job_ui={**job,"observation_id":"j2","source_ref":"j2","feedback_role":"USER_INNOVATION_NEED_SOLUTION","problem_span":"We built automation because our teams needed it."}
    x=build_research_objects([need,change,supply,free_supply,ui,pitch,positive,policy,job,bad_job_ui],[raw_supply])
    return {
        "need_is_separate_object":len(x["need_fragments"])==1,
        "external_change_is_separate_object":len(x["external_enablers"])==1,
        "market_supply_is_separate_object":len(x["market_states"])==3,
        "free_supply_not_misread_as_paid":any(m.get("product_id")=="free" and m.get("supply_exists") and not m.get("paid_supply") for m in x["market_states"]),
        "user_innovation_is_separate_signal":len(x["user_innovation_signals"])==1 and x["user_innovation_signals"][0]["status"].startswith("OBSERVED_SELF_SOLUTION"),
        "supplier_and_positive_are_solution_context":len(x["solution_supply_signals"])==2,
        "policy_is_context_not_need":len(x["policy_contexts"])==1,
        "no_context_signal_leaks_into_need":len(x["need_fragments"])==1,
        "frontier_linkage_boundary_explicit":"not self-certified" in x["frontier_boundary"],
        "raw_supply_materializes_without_pain_parser":any(m.get("product_id")=="raw1" for m in x["market_states"]),
        "role_schema_telemetry_visible":"feedback_roles" in x["counts"],
        "job_is_employer_context_not_user_innovation":len(x.get("employer_demand_signals") or [])>=1 and all((u.get("source_family") or "")!="jobs" for u in x.get("user_innovation_signals") or []),
    }

