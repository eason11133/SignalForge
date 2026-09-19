from __future__ import annotations

import json
import math
import os
import re
import time
from collections import Counter
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from processors.founder_thesis_research_control_u14 import Store, GapType
import processors.founder_research_resilience_u16 as u16
import processors.evidence_adjudication_u17 as u17

ENGINE_VERSION = "signalforge-thesis-conditioned-evidence-u18-v1"
STATE = Path(".radar_runtime/thesis_conditioned_evidence_u18.json")
U17_STATE = Path(".radar_runtime/evidence_adjudication_u17.json")
U16_STATE = Path(".radar_runtime/founder_research_resilience_u16.json")
TRUTH_BOUNDARY = (
    "GAP_LINEAGE_WITHOUT_THESIS_SEMANTIC_CONTEXT_IS_INSUFFICIENT; "
    "EVIDENCE_MUST MATCH BOTH THESIS AND GAP; "
    "GENERIC PAYMENT_OR_ADOPTION_EVIDENCE_CANNOT UPDATE A FOUNDER_THESIS; "
    "QUARANTINED_LEGACY_JUDGMENTS_DO_NOT COUNT AS MARKET_TRUTH; PRODUCT_IDEATION=0"
)

GAP_WORDS = {
    GapType.INDEPENDENT_NEED_RECURRENCE.value: {"independent","need","recurrence"},
    GapType.CURRENT_SOLUTION_SUPPLY.value: {"current","solution","supply"},
    GapType.PEER_ADOPTION_OR_DIFFUSION.value: {"peer","adoption","diffusion"},
    GapType.PAYMENT_BEHAVIOR.value: {"payment","behavior","wtp","pay","paid"},
}
GENERIC = {
    "research","current","solution","supply","independent","need","recurrence",
    "peer","adoption","diffusion","payment","behavior","evidence","gap",
    "local","llm","llms","software","github","app","tool","tools",
}

def _fresh() -> dict:
    return {
        "engine_version": ENGINE_VERSION,
        "contexts": {},
        "quarantine": [],
        "strategies_tried": {},
        "requests": [],
        "candidate_queue": {},
        "adjudication_runs": [],
        "provider": {"status":"UNKNOWN"},
    }

def _load() -> dict:
    if not STATE.exists(): return _fresh()
    d=json.loads(STATE.read_text(encoding="utf-8"))
    if d.get("engine_version") != ENGINE_VERSION:
        raise RuntimeError("U18_STATE_VERSION_MISMATCH")
    return d

def _atomic(path: Path,payload: dict) -> None:
    import tempfile
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix=path.name+".",suffix=".tmp",dir=str(path.parent))
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as f:
            json.dump(payload,f,ensure_ascii=False,indent=2,sort_keys=True)
            f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

def _tokens(text: str) -> List[str]:
    return [x for x in re.findall(r"[a-z0-9][a-z0-9_+-]{2,}",(text or "").lower()) if x not in {"research"}]

def _semantic_tokens(text: str) -> List[str]:
    return [x for x in _tokens(text) if x not in GENERIC]

def build_thesis_context(store: Store, thesis_id: str) -> dict:
    thesis=store.theses[thesis_id]
    source_queries=[]
    # Payment can be empty/generic. Build context from the sibling evidence gaps that describe the object itself.
    for gt in (
        GapType.INDEPENDENT_NEED_RECURRENCE,
        GapType.CURRENT_SOLUTION_SUPPLY,
        GapType.PEER_ADOPTION_OR_DIFFUSION,
    ):
        g=store.gap(thesis_id,gt.value)
        q=(g.last_query or "").strip()
        if q and q.lower() not in {gt.value.lower(),gt.value.lower().replace("_"," ")}:
            source_queries.append(q)
    counts=Counter()
    first_seen=[]
    for q in source_queries:
        for tok in _tokens(q):
            if tok not in first_seen:first_seen.append(tok)
            if tok not in GENERIC: counts[tok]+=1

    # Include recurring object terms even when they are common operational nouns; exclude pure gap labels.
    all_counts=Counter(tok for q in source_queries for tok in _tokens(q) if tok not in GAP_WORDS[GapType.PAYMENT_BEHAVIOR.value])
    ranked=[x for x,_ in counts.most_common()]
    for x,_ in all_counts.most_common():
        if x not in ranked and x not in GENERIC: ranked.append(x)
    # Fallback permits object nouns such as slides/papers even if a future generic list changes.
    if len(ranked)<2:
        for x in first_seen:
            if x not in GENERIC and x not in ranked:ranked.append(x)
    # Preserve useful object nouns explicitly from source queries.
    for x in ("paper","papers","slide","slides","presentation","presentations","privacy","format","formatting"):
        if any(x in _tokens(q) for q in source_queries) and x not in ranked:
            ranked.append(x)

    terms=ranked[:8]
    quality="PASS" if len(terms)>=2 else "INSUFFICIENT"
    context_text=" ".join(terms)
    pack={
        "thesis_id":thesis_id,
        "card_id":thesis.card_id,
        "thesis_type":thesis.thesis_type,
        "source_queries":source_queries,
        "subject_terms":terms,
        "context_text":context_text,
        "quality":quality,
        "contract_version":"THESIS_CONTEXT_V1",
    }
    s=_load();s["contexts"][thesis_id]=pack;_atomic(STATE,s)
    return pack

def query_contract(query: str, ctx: dict) -> dict:
    q=set(_tokens(query));subject=set(ctx.get("subject_terms") or [])
    overlap=sorted(q & subject)
    normalized=(query or "").strip().lower().replace("-","_").replace(" ","_")
    generic_label=normalized in {
        "payment_behavior","peer_adoption_or_diffusion","current_solution_supply",
        "independent_need_recurrence","payment","adoption","diffusion","recurrence","supply"
    }
    passed=(ctx.get("quality")=="PASS" and not generic_label and len(overlap)>=1 and len(q)>=2)
    return {"pass":passed,"subject_overlap":overlap,"generic_gap_label":generic_label}

def gap_question(gap: str, ctx: dict) -> str:
    c=ctx["context_text"]
    if gap==GapType.INDEPENDENT_NEED_RECURRENCE.value:
        return f"Do independent users report recurring firsthand pain or constraints in the workflow/topic: {c}?"
    if gap==GapType.CURRENT_SOLUTION_SUPPLY.value:
        return f"Do current solutions materially address the workflow/topic: {c}?"
    if gap==GapType.PEER_ADOPTION_OR_DIFFUSION.value:
        return f"Is there direct evidence that peers actually adopt or use relevant solutions for: {c}?"
    return f"Is there explicit payment, spend, budget, purchase, subscription, or willingness-to-pay for solving: {c}?"

def query_family(gap: str, ctx: dict) -> List[str]:
    base=" ".join(ctx.get("subject_terms") or [])[:180]
    if not base:return []
    if gap==GapType.INDEPENDENT_NEED_RECURRENCE.value:
        tails=["tedious manual problem","annoying workflow","privacy formatting pain","hours spent workaround"]
    elif gap==GapType.CURRENT_SOLUTION_SUPPLY.value:
        tails=["software github","open source product"]
    elif gap==GapType.PEER_ADOPTION_OR_DIFFUSION.value:
        tails=["users adoption forks stars","people using workflow","adoption comments"]
    else:
        tails=["paid price subscription","spent budget purchase","willing pay price"]
    out=[]
    for tail in tails:
        q=" ".join((base+" "+tail).split()[:9])
        if query_contract(q,ctx)["pass"] and q not in out:out.append(q)
    return out

def _reverse_gap_judgment(g,item:dict) -> None:
    status=str(item.get("status") or item.get("judgment") or "")
    sg=str(item.get("source_group") or item.get("evidence_id") or "")
    if status=="CONFIRMED_SUPPORT":
        if sg in g.confirmed_support_groups:g.confirmed_support_groups.remove(sg)
        if g.adjudicated>0:g.adjudicated-=1
    elif status=="CONFIRMED_REFUTE":
        if g.confirmed_refute>0:g.confirmed_refute-=1
        if g.adjudicated>0:g.adjudicated-=1
    elif status in {"RELATED_BUT_NOT_EVIDENCE","INSUFFICIENT"}:
        if g.related_or_insufficient>0:g.related_or_insufficient-=1
        if g.adjudicated>0:g.adjudicated-=1
    elif status=="DEPENDENT_DUPLICATE":
        if g.dependent_duplicates>0:g.dependent_duplicates-=1

def quarantine_context_invalid_u17(store: Store) -> dict:
    summary={"scanned":0,"quarantined":0,"support_revoked":0,"other_judgments_revoked":0}
    if not U17_STATE.exists():return summary
    d=json.loads(U17_STATE.read_text(encoding="utf-8"))
    u18=_load()
    existing={x.get("queue_id") for x in u18["quarantine"]}
    for qid,item in (d.get("queue") or {}).items():
        gap=str(item.get("gap") or "")
        tid=str(item.get("thesis_id") or "")
        if tid not in store.theses:continue
        summary["scanned"]+=1
        ctx=build_thesis_context(store,tid)
        qc=query_contract(str(item.get("query") or ""),ctx)
        status=str(item.get("status") or "")
        if status=="PENDING":continue
        if status.startswith("QUARANTINED_"):continue
        if qc["pass"]:continue
        if qid not in existing:
            old=status
            _reverse_gap_judgment(store.gaps[item["gap_id"]],item)
            u18["quarantine"].append({
                "queue_id":qid,"thesis_id":tid,"gap_id":item.get("gap_id"),"gap":gap,
                "old_status":old,"query":item.get("query"),"source_group":item.get("source_group"),
                "reason":"THESIS_CONTEXT_QUERY_CONTRACT_FAILED","at":time.time(),
            })
            existing.add(qid)
            summary["quarantined"]+=1
            if old=="CONFIRMED_SUPPORT":summary["support_revoked"]+=1
            else:summary["other_judgments_revoked"]+=1
        item["status"]="QUARANTINED_LINEAGE_CONTEXT_INSUFFICIENT"
        item["u18_query_contract"]=qc
    store._persist()
    _atomic(U17_STATE,d);_atomic(STATE,u18)
    return summary

def reconcile_u16_overlays(store: Store) -> dict:
    if not U16_STATE.exists():return {"updated":0}
    d=json.loads(U16_STATE.read_text(encoding="utf-8"))
    overlays=d.get("gap_overlays") or {}
    u17d=json.loads(U17_STATE.read_text(encoding="utf-8")) if U17_STATE.exists() else {"queue":{}}
    updated=0
    for gid,g in store.gaps.items():
        ov=overlays.get(gid)
        if not ov:continue
        pending=sum(1 for x in (u17d.get("queue") or {}).values() if x.get("gap_id")==gid and x.get("status")=="PENDING")
        old=(ov.get("verification_pending_count"),ov.get("last_outcome"),ov.get("research_state"))
        ov["verification_pending_count"]=pending
        if pending:
            ov["last_outcome"]="VERIFICATION_PENDING";ov["research_state"]="WAITING_FOR_VERIFICATION"
        elif g.confirmed>0:
            ov["last_outcome"]="CONFIRMED_SUPPORT"
            ov["research_state"]="RESEARCH_SUFFICIENT" if g.confirmed>=u16.TARGET[g.gap_type] else "ACTIVE"
        elif any(x.get("gap_id")==gid and str(x.get("status","")).startswith("QUARANTINED_")
                 for x in (u17d.get("queue") or {}).values()):
            ov["last_outcome"]="CONTEXT_INVALIDATED";ov["research_state"]="ACTIVE"
        new=(ov.get("verification_pending_count"),ov.get("last_outcome"),ov.get("research_state"))
        if new!=old:updated+=1
    _atomic(U16_STATE,d)
    return {"updated":updated}

def provider_status() -> dict:
    env=u17.load_project_env()
    out={"status":"AVAILABLE" if env["openai_key_after"] else "UNAVAILABLE","env":env,"checked_at":time.time()}
    s=_load();s["provider"]=out;_atomic(STATE,s)
    return out

class ThesisVerifier:
    def __init__(self,max_calls:int=3,client_factory=None):
        self.max_calls=max_calls;self.calls=0
        self.client_factory=client_factory
        self.available=bool(os.getenv("OPENAI_API_KEY")) or client_factory is not None
        self.model=os.getenv("SIGNALFORGE_U18_VERIFY_MODEL","gpt-5-mini")

    def adjudicate(self,gap:str,ctx:dict,items:List[dict]) -> Dict[str,dict]:
        if not self.available or self.calls>=self.max_calls or not items:return {}
        self.calls+=1
        try:
            if self.client_factory:client=self.client_factory()
            else:
                from openai import OpenAI
                client=OpenAI()
            compact=[{
                "candidate_id":x["candidate_id"],"source_group":x.get("source_group"),
                "text":(x.get("text") or "")[:1800]
            } for x in items[:10]]
            prompt=(
                "You are a strict evidence adjudicator for SignalForge. "
                "FOUNDER THESIS CONTEXT: "+json.dumps(ctx,ensure_ascii=False)+
                " ATOMIC GAP QUESTION: "+gap_question(gap,ctx)+
                " For each candidate return JSON only: {\"items\":[{\"candidate_id\":\"...\","
                "\"thesis_match\":\"MATCH|MISMATCH|UNCERTAIN\",\"gap_judgment\":\"CONFIRMED_SUPPORT|"
                "CONFIRMED_REFUTE|RELATED_BUT_NOT_EVIDENCE|INSUFFICIENT\",\"rationale\":\"...\"}]}. "
                "A candidate may count as CONFIRMED_SUPPORT only if thesis_match=MATCH AND it directly supports "
                "the atomic gap question. Generic payment, generic adoption, adjacent workflows, vendor promotion, "
                "and merely similar keywords do not count. Do not infer market size or build recommendation. Candidates="
                +json.dumps(compact,ensure_ascii=False)
            )
            text=None
            if hasattr(client,"responses"):
                r=client.responses.create(model=self.model,input=prompt)
                text=getattr(r,"output_text",None)
            if not text and hasattr(client,"chat"):
                r=client.chat.completions.create(model=self.model,messages=[{"role":"user","content":prompt}],temperature=0)
                text=r.choices[0].message.content
            if not text:return {}
            m=re.search(r"\{.*\}",text,re.S);data=json.loads(m.group(0) if m else text)
            out={}
            for x in data.get("items") or []:
                cid=str(x.get("candidate_id") or "")
                tm=str(x.get("thesis_match") or "")
                gj=str(x.get("gap_judgment") or "")
                if tm not in {"MATCH","MISMATCH","UNCERTAIN"}:continue
                if gj not in {"CONFIRMED_SUPPORT","CONFIRMED_REFUTE","RELATED_BUT_NOT_EVIDENCE","INSUFFICIENT"}:continue
                if tm!="MATCH" and gj=="CONFIRMED_SUPPORT":gj="RELATED_BUT_NOT_EVIDENCE"
                out[cid]={"thesis_match":tm,"gap_judgment":gj,"rationale":str(x.get("rationale") or "")[:500]}
            return out
        except Exception as e:
            return {"__error__":{"rationale":f"{type(e).__name__}: {e}"[:500]}}

def _apply(store:Store,g,item:dict,j:dict) -> str:
    tm=j["thesis_match"];gj=j["gap_judgment"]
    if tm!="MATCH":
        return "THESIS_MISMATCH" if tm=="MISMATCH" else "THESIS_UNCERTAIN"
    if gj=="CONFIRMED_SUPPORT":
        sg=str(item.get("source_group") or item.get("candidate_id"))
        if sg in g.confirmed_support_groups:
            g.dependent_duplicates+=1;return "DEPENDENT_DUPLICATE"
        g.confirmed_support_groups.append(sg);g.adjudicated+=1;return gj
    if gj=="CONFIRMED_REFUTE":
        g.confirmed_refute+=1;g.adjudicated+=1;return gj
    if gj in {"RELATED_BUT_NOT_EVIDENCE","INSUFFICIENT"}:
        g.related_or_insufficient+=1;g.adjudicated+=1;return gj
    return "INSUFFICIENT"

def _candidate_from_u17(item:dict) -> dict:
    return {
        "candidate_id":item["queue_id"],"evidence_id":item.get("evidence_id"),
        "source_group":item.get("source_group"),"source_ref":item.get("source_ref"),
        "text":item.get("text"),"meta":item.get("meta") or {},
    }

def adjudicate_valid_u17_pending(store:Store,verifier:ThesisVerifier) -> dict:
    if not U17_STATE.exists():return {"pending_before":0,"resolved":0,"pending_after":0,"calls":verifier.calls}
    d=json.loads(U17_STATE.read_text(encoding="utf-8"))
    pending=[x for x in (d.get("queue") or {}).values() if x.get("status")=="PENDING"]
    by_gap={}
    for x in pending:
        tid=x.get("thesis_id")
        if tid not in store.theses:continue
        ctx=build_thesis_context(store,tid)
        qc=query_contract(str(x.get("query") or ""),ctx)
        if not qc["pass"]:
            x["status"]="QUARANTINED_LINEAGE_CONTEXT_INSUFFICIENT";x["u18_query_contract"]=qc
            continue
        by_gap.setdefault((tid,x["gap_id"],x["gap"]),[]).append(x)
    resolved=0;errors=[]
    for (tid,gid,gap),items in by_gap.items():
        if verifier.calls>=verifier.max_calls:break
        ctx=build_thesis_context(store,tid)
        cands=[_candidate_from_u17(x) for x in items]
        result=verifier.adjudicate(gap,ctx,cands)
        if "__error__" in result:
            errors.append(result["__error__"]["rationale"]);continue
        for x,c in zip(items,cands):
            j=result.get(c["candidate_id"])
            if not j:continue
            final=_apply(store,store.gaps[gid],c,j)
            x["status"]=final;x["u18_thesis_match"]=j["thesis_match"];x["u18_gap_judgment"]=j["gap_judgment"]
            x["u18_rationale"]=j["rationale"];x["adjudicated_at"]=time.time();resolved+=1
    store._persist();_atomic(U17_STATE,d)
    pending_after=sum(1 for x in (d.get("queue") or {}).values() if x.get("status")=="PENDING")
    reconcile_u16_overlays(store)
    s=_load();s["adjudication_runs"].append({
        "kind":"U17_PENDING_RECONDITIONED","pending_before":len(pending),"resolved":resolved,
        "pending_after":pending_after,"calls":verifier.calls,"errors":errors,"at":time.time()
    });_atomic(STATE,s)
    return {"pending_before":len(pending),"resolved":resolved,"pending_after":pending_after,"calls":verifier.calls,"errors":errors}

def _strategy_for(gap:str,ctx:dict,state:dict) -> Optional[Tuple[str,str]]:
    tried=set(state["strategies_tried"].get(gap+":"+ctx["thesis_id"],[]))
    adapters={
        GapType.INDEPENDENT_NEED_RECURRENCE.value:["hackernews_relevance","stackexchange","github_issues"],
        GapType.CURRENT_SOLUTION_SUPPLY.value:["github_search"],
        GapType.PEER_ADOPTION_OR_DIFFUSION.value:["github_search","github_issues","hackernews_relevance"],
        GapType.PAYMENT_BEHAVIOR.value:["hackernews_relevance","stackexchange","github_issues"],
    }[gap]
    for q in query_family(gap,ctx):
        for a in adapters:
            key=q+"||"+a
            if key not in tried:return q,a
    return None

def _gap_priority(store:Store,tid:str,g,ctx:dict,state:dict) -> float:
    # Preserve U16 prospective logic but do not use stale pending counts.
    confirmed=g.confirmed
    target=u16.TARGET[g.gap_type]
    if confirmed>=target:return 0.0
    # Payment remains downstream but is allowed after recurrence and supply have direct support.
    ok,_=u16.prerequisites(store,tid,g.gap_type)
    if not ok:return 0.0
    base=u16.IMPACT[g.gap_type]*(1/(3+g.related_or_insufficient))*((1-confirmed/target)**2)
    return round(max(0.0,base-0.03),6)

def pending_u18() -> int:
    return sum(1 for x in _load()["candidate_queue"].values() if x.get("status")=="PENDING")

def _enqueue_u18(task:dict,cands:List[dict]) -> None:
    s=_load()
    for c in cands:
        cid=task["request_id"]+"::"+c["evidence_id"]
        s["candidate_queue"][cid]={
            "candidate_id":cid,"request_id":task["request_id"],"thesis_id":task["thesis_id"],
            "card_id":task["card_id"],"gap_id":task["gap_id"],"gap":task["gap"],
            "query":task["query"],"adapter":task["adapter"],"source_group":c.get("source_group"),
            "source_ref":c.get("source_ref"),"evidence_id":c.get("evidence_id"),"text":c.get("text"),
            "meta":c.get("meta") or {},"status":"PENDING","created_at":time.time(),
        }
    _atomic(STATE,s)

def adjudicate_u18_queue(store:Store,verifier:ThesisVerifier) -> dict:
    s=_load();pending=[x for x in s["candidate_queue"].values() if x.get("status")=="PENDING"]
    by_gap={}
    for x in pending:by_gap.setdefault((x["thesis_id"],x["gap_id"],x["gap"]),[]).append(x)
    resolved=0;errors=[]
    for (tid,gid,gap),items in by_gap.items():
        if verifier.calls>=verifier.max_calls:break
        ctx=build_thesis_context(store,tid)
        result=verifier.adjudicate(gap,ctx,items)
        if "__error__" in result:
            errors.append(result["__error__"]["rationale"]);continue
        for x in items:
            j=result.get(x["candidate_id"])
            if not j:continue
            final=_apply(store,store.gaps[gid],x,j)
            x["status"]=final;x["thesis_match"]=j["thesis_match"];x["gap_judgment"]=j["gap_judgment"];x["rationale"]=j["rationale"]
            x["adjudicated_at"]=time.time();resolved+=1
    store._persist();_atomic(STATE,s)
    return {"pending_before":len(pending),"resolved":resolved,"pending_after":pending_u18(),"errors":errors,"calls":verifier.calls}

def select_next(store:Store,verifier:ThesisVerifier) -> Optional[Tuple[str,str,object,dict,float,str,str]]:
    if not verifier.available or verifier.calls>=verifier.max_calls:return None
    if pending_u18()>0:return None
    s=_load();scored=[]
    # Also honor any U17 pending: no new retrieval until old backlog is cleared.
    if U17_STATE.exists():
        u17d=json.loads(U17_STATE.read_text(encoding="utf-8"))
        if any(x.get("status")=="PENDING" for x in (u17d.get("queue") or {}).values()):return None
    for card,tid in store.card_map.items():
        ctx=build_thesis_context(store,tid)
        if ctx["quality"]!="PASS":continue
        for gt in GapType:
            g=store.gap(tid,gt.value)
            strat=_strategy_for(g.gap_type,ctx,s)
            if not strat:continue
            v=_gap_priority(store,tid,g,ctx,s)
            if v>0:scored.append((v,card,tid,g,ctx,strat[0],strat[1]))
    if not scored:return None
    scored.sort(key=lambda x:x[0],reverse=True)
    v,card,tid,g,ctx,q,a=scored[0]
    return card,tid,g,ctx,v,q,a

def retrieve_one(store:Store,verifier:ThesisVerifier,fetch_fn:Callable=u16.fetch) -> Optional[dict]:
    sel=select_next(store,verifier)
    if not sel:return None
    card,tid,g,ctx,v,q,adapter=sel
    qc=query_contract(q,ctx)
    if not qc["pass"]:raise RuntimeError("U18_QUERY_CONTRACT_INTERNAL_FAILURE")
    started=time.time();error=None
    try:cands=fetch_fn(adapter,q,10)
    except Exception as e:cands=[];error=f"{type(e).__name__}: {e}"
    rid="u18req_"+str(int(time.time()*1000))
    task={
        "request_id":rid,"card_id":card,"thesis_id":tid,"gap_id":g.gap_id,"gap":g.gap_type,
        "thesis_context":ctx,"atomic_gap_question":gap_question(g.gap_type,ctx),
        "query":q,"query_contract":qc,"adapter":adapter,"candidate_ids":[c.get("evidence_id") for c in cands],
        "candidate_count":len(cands),"error":error,"seconds":round(time.time()-started,3),
        "marginal_priority_before":v,
    }
    s=_load();key=g.gap_type+":"+tid;s["strategies_tried"].setdefault(key,[]).append(q+"||"+adapter);s["requests"].append(task);_atomic(STATE,s)
    g.attempts+=1;g.retrieved_candidates+=len(cands);g.last_query=q;g.last_adapter=adapter;store._persist()
    if cands:
        _enqueue_u18(task,cands)
        adj=adjudicate_u18_queue(store,verifier)
        task["adjudication"]=adj
    else:
        task["adjudication"]={"pending_before":0,"resolved":0,"pending_after":0,"calls":verifier.calls}
    return task

def execute_cycle(store:Store,max_new_requests:int=2,max_verifier_calls:int=3,fetch_fn:Callable=u16.fetch,verifier:Optional[ThesisVerifier]=None) -> dict:
    provider_status()
    verifier=verifier or ThesisVerifier(max_calls=max_verifier_calls)
    quarantine=quarantine_context_invalid_u17(store)
    reconcile=reconcile_u16_overlays(store)
    old=adjudicate_valid_u17_pending(store,verifier)
    own=adjudicate_u18_queue(store,verifier)
    requests=[]
    # Every new LLM-verifiable request must reserve one verifier call. No "retrieve now, maybe judge later" pile-up.
    while len(requests)<max_new_requests and verifier.calls<verifier.max_calls and pending_u18()==0:
        if U17_STATE.exists():
            d=json.loads(U17_STATE.read_text(encoding="utf-8"))
            if any(x.get("status")=="PENDING" for x in (d.get("queue") or {}).values()):break
        row=retrieve_one(store,verifier,fetch_fn)
        if not row:break
        requests.append(row)
        if pending_u18()>0:break
    return {
        "quarantine":quarantine,"reconcile":reconcile,"u17_pending_adjudication":old,
        "u18_pending_adjudication":own,"new_requests":requests,"new_request_count":len(requests),
        "verifier_calls":verifier.calls,"verifier_available":verifier.available,
        "u18_pending_after":pending_u18(),
    }

def card_progress(store:Store,card_id:str) -> dict:
    s=_load();tid=store.card_map[card_id];ctx=build_thesis_context(store,tid)
    u17d=json.loads(U17_STATE.read_text(encoding="utf-8")) if U17_STATE.exists() else {"queue":{}}
    rows=[];eligible=[]
    for gt in GapType:
        g=store.gap(tid,gt.value)
        u17pending=sum(1 for x in (u17d.get("queue") or {}).values() if x.get("gap_id")==g.gap_id and x.get("status")=="PENDING")
        u18pending=sum(1 for x in s["candidate_queue"].values() if x.get("gap_id")==g.gap_id and x.get("status")=="PENDING")
        ok,why=u16.prerequisites(store,tid,g.gap_type)
        v=_gap_priority(store,tid,g,ctx,s) if ok and not (u17pending+u18pending) else 0.0
        if g.confirmed>=u16.TARGET[g.gap_type]:state="RESEARCH_SUFFICIENT"
        elif not ok:state="BLOCKED_"+why
        elif u17pending+u18pending:state="PENDING_THESIS_CONDITIONED_ADJUDICATION"
        elif ctx["quality"]!="PASS":state="BLOCKED_THESIS_CONTEXT_INSUFFICIENT"
        else:state="ACTIVE"
        row={
            "gap":g.gap_type,"gap_id":g.gap_id,"attempts":g.attempts,
            "retrieved_candidates":g.retrieved_candidates,"adjudicated":g.adjudicated,
            "confirmed_independent_support":g.confirmed,"confirmed_refute":g.confirmed_refute,
            "dependent_duplicates":g.dependent_duplicates,"pending_adjudication":u17pending+u18pending,
            "research_state":state,"marginal_priority":v,"prerequisite":why,
        }
        rows.append(row)
        if state=="ACTIVE" and v>0:eligible.append(row)
    eligible.sort(key=lambda x:x["marginal_priority"],reverse=True)
    if any(r["pending_adjudication"] for r in rows):
        best={"action":"ADJUDICATE_THESIS_CONDITIONED_PENDING_FIRST"}
    elif eligible:
        best={"action":"RESEARCH_NEXT_THESIS_CONDITIONED_GAP",**eligible[0]}
    else:best={"action":"NO_ELIGIBLE_RESEARCH"}
    return {
        "card_id":card_id,"thesis_id":tid,"thesis_context":ctx,
        "gap_progress":rows,"best_next_research":best,"truth_boundary":TRUTH_BOUNDARY
    }
