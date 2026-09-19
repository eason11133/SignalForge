from __future__ import annotations

import html
import json
import math
import os
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from processors.founder_thesis_research_control_u14 import Store, GapType
from processors.founder_directed_research_u15 import (
    search_hn, search_stackexchange, search_github, _http_json, _strip_html, _tokens
)

ENGINE_VERSION = "signalforge-research-resilience-u16-v1"
STATE = Path(".radar_runtime/founder_research_resilience_u16.json")
U15_STATE = Path(".radar_runtime/founder_directed_research_u15.json")

IMPACT = {
    GapType.INDEPENDENT_NEED_RECURRENCE.value: 1.00,
    GapType.CURRENT_SOLUTION_SUPPLY.value: 0.78,
    GapType.PEER_ADOPTION_OR_DIFFUSION.value: 0.72,
    GapType.PAYMENT_BEHAVIOR.value: 0.92,
}
TARGET = {
    GapType.INDEPENDENT_NEED_RECURRENCE.value: 3,
    GapType.CURRENT_SOLUTION_SUPPLY.value: 3,
    GapType.PEER_ADOPTION_OR_DIFFUSION.value: 3,
    GapType.PAYMENT_BEHAVIOR.value: 2,
}
TRUTH_BOUNDARY = (
    "RETRIEVAL_EMPTY_IS_NOT_NEGATIVE_EVIDENCE; UNADJUDICATED_CANDIDATES_ARE_NOT_NEGATIVE_EVIDENCE; "
    "ONLY GAP_SPECIFIC VERIFIED SUPPORT/REFUTE CHANGES EVIDENCE STATE; "
    "SUPPLY_DIFFUSION_RECURRENCE_PAYMENT_REMAIN DISTINCT; PRODUCT_IDEATION=0"
)

def _fresh_state() -> dict:
    base = {
        "engine_version": ENGINE_VERSION,
        "cycle": 0,
        "founder_tasks_total": 0,
        "exploration_requests_total": 0,
        "migrated_u15_request_ids": [],
        "gap_overlays": {},
        "tasks": [],
    }
    if U15_STATE.exists():
        try:
            u15=json.loads(U15_STATE.read_text(encoding="utf-8"))
            base["cycle"]=int(u15.get("cycle") or 0)
            base["founder_tasks_total"]=int(u15.get("founder_requests_total") or 0)
            base["exploration_requests_total"]=int(u15.get("exploration_requests_total") or 0)
        except Exception:
            pass
    return base

def _load_state() -> dict:
    if not STATE.exists():
        return _fresh_state()
    d=json.loads(STATE.read_text(encoding="utf-8"))
    if d.get("engine_version") != ENGINE_VERSION:
        raise RuntimeError("U16_STATE_VERSION_MISMATCH")
    return d

def _atomic_json(path: Path, payload: dict) -> None:
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

def _overlay(state: dict, gap_id: str) -> dict:
    return state["gap_overlays"].setdefault(gap_id,{
        "logical_tasks":0,
        "fetch_attempts":0,
        "retrieval_empty_count":0,
        "verified_no_support_count":0,
        "verification_pending_count":0,
        "confirmed_tasks":0,
        "queries_tried":[],
        "adapters_tried":[],
        "last_outcome":"UNSEEN",
        "research_state":"OPEN",
    })

def migrate_u15_semantics(store: Store) -> dict:
    state=_load_state()
    migrated=set(state.get("migrated_u15_request_ids") or [])
    summary={"migrated":0,"retrieval_empty_reclassified":0,"verification_pending_reclassified":0,"kept_verified":0}
    if not U15_STATE.exists():
        _atomic_json(STATE,state)
        return summary
    try:
        u15=json.loads(U15_STATE.read_text(encoding="utf-8"))
    except Exception:
        _atomic_json(STATE,state)
        return summary
    for r in u15.get("requests") or []:
        rid=str(r.get("request_id") or "")
        if not rid or rid in migrated: continue
        gid=str(r.get("gap_id") or "")
        if not gid or gid not in store.gaps:
            migrated.add(rid); continue
        g=store.gaps[gid]
        ov=_overlay(state,gid)
        count=int(r.get("candidate_count") or 0)
        judgments=r.get("judgments") or {}
        confirmed=int(r.get("confirmed_count") or 0)

        # U15 incorrectly used zero-confirmed-yield for all three cases.
        # Repair the live U14 gap state only for cases that were not actually verified-negative.
        if count == 0:
            ov["retrieval_empty_count"] += 1
            ov["last_outcome"]="RETRIEVAL_EMPTY"
            summary["retrieval_empty_reclassified"] += 1
            if g.zero_confirmed_yield_streak > 0:
                g.zero_confirmed_yield_streak -= 1
            if g.state=="STOP_LOW_MARGINAL_VALUE": g.state="ACTIVE"
        elif not judgments:
            ov["verification_pending_count"] += 1
            ov["last_outcome"]="VERIFICATION_PENDING"
            summary["verification_pending_reclassified"] += 1
            if g.zero_confirmed_yield_streak > 0:
                g.zero_confirmed_yield_streak -= 1
            if g.state=="STOP_LOW_MARGINAL_VALUE": g.state="ACTIVE"
        else:
            summary["kept_verified"] += 1
            ov["last_outcome"]="CONFIRMED_SUPPORT" if confirmed else "VERIFIED_NO_SUPPORT"
            if not confirmed:
                ov["verified_no_support_count"] += 1
        ov["logical_tasks"] += 1
        ov["fetch_attempts"] += 1
        q=str(r.get("query") or "")
        a=str(r.get("adapter") or "")
        if q and q not in ov["queries_tried"]:ov["queries_tried"].append(q)
        if a and a not in ov["adapters_tried"]:ov["adapters_tried"].append(a)
        migrated.add(rid);summary["migrated"] += 1
    state["migrated_u15_request_ids"]=sorted(migrated)
    store._persist()
    _atomic_json(STATE,state)
    return summary

def search_hn_relevance(query: str, limit: int=10) -> List[dict]:
    url="https://hn.algolia.com/api/v1/search?"+urllib.parse.urlencode({"query":query,"hitsPerPage":limit})
    d=_http_json(url)
    out=[]
    for x in d.get("hits") or []:
        text=_strip_html(" ".join(str(x.get(k) or "") for k in ("title","story_title","story_text","comment_text")))
        if not text:continue
        oid=str(x.get("objectID") or "")
        author=str(x.get("author") or "unknown")
        out.append({
            "evidence_id":"hnr:"+oid,
            "source_ref":"https://news.ycombinator.com/item?id="+oid if oid else "hn:"+author,
            "source_group":"hn_author:"+author,
            "text":text[:5000],
            "meta":{"author":author,"created_at":x.get("created_at"),"retrieval":"relevance"},
        })
    return out

def search_github_issues(query: str, limit: int=10) -> List[dict]:
    q=query+" is:issue"
    headers={"Accept":"application/vnd.github+json"}
    tok=os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    if tok:headers["Authorization"]="Bearer "+tok
    d=_http_json("https://api.github.com/search/issues?"+urllib.parse.urlencode({
        "q":q,"sort":"updated","order":"desc","per_page":limit
    }),headers=headers)
    out=[]
    for x in d.get("items") or []:
        user=x.get("user") or {}
        login=str(user.get("login") or "unknown")
        text=_strip_html((x.get("title") or "")+" "+(x.get("body") or ""))
        if not text:continue
        out.append({
            "evidence_id":"ghi:"+str(x.get("id") or ""),
            "source_ref":x.get("html_url") or "",
            "source_group":"github_user:"+login,
            "text":text[:5000],
            "meta":{"comments":x.get("comments"),"state":x.get("state"),"updated_at":x.get("updated_at")},
        })
    return out

def fetch(adapter: str, query: str, limit: int=10) -> List[dict]:
    if adapter=="hackernews_recent":return search_hn(query,limit)
    if adapter=="hackernews_relevance":return search_hn_relevance(query,limit)
    if adapter=="stackexchange":return search_stackexchange(query,limit)
    if adapter=="github_search":return search_github(query,limit)
    if adapter=="github_issues":return search_github_issues(query,limit)
    raise ValueError("U16_UNKNOWN_ADAPTER "+adapter)

def compact(q: str, max_terms: int=7) -> str:
    toks=_tokens(q)
    return " ".join(toks[:max_terms]) if toks else (q or "").strip()

def query_family(base: str, gap: str) -> List[str]:
    toks=_tokens(base)
    # keep the core objects; deliberately remove generic "research" and over-constraining phrasing.
    core=[x for x in toks if x not in {"constraint","format","formatting","privacy"}]
    coreq=" ".join(core[:5]) or compact(base)
    if gap==GapType.INDEPENDENT_NEED_RECURRENCE.value:
        candidates=[
            compact(base),
            compact(coreq+" tedious presentation"),
            compact(coreq+" manual presentation workflow"),
            compact("research paper presentation tedious"),
            compact("paper slides privacy formatting"),
        ]
    elif gap==GapType.CURRENT_SOLUTION_SUPPLY.value:
        candidates=[
            compact(base),
            compact(coreq+" software github"),
            compact(coreq+" open source slides"),
        ]
    elif gap==GapType.PEER_ADOPTION_OR_DIFFUSION.value:
        candidates=[
            compact(base),
            compact(coreq+" github adoption"),
            compact(coreq+" users forks stars"),
        ]
    else:
        candidates=[
            compact(base),
            compact(coreq+" paid price subscription"),
            compact(coreq+" spent budget purchase"),
        ]
    out=[]
    for q in candidates:
        if q and q not in out:out.append(q)
    return out

def adapter_family(gap: str) -> List[str]:
    if gap==GapType.INDEPENDENT_NEED_RECURRENCE.value:
        return ["hackernews_relevance","stackexchange","github_issues","hackernews_recent"]
    if gap==GapType.CURRENT_SOLUTION_SUPPLY.value:
        return ["github_search"]
    if gap==GapType.PEER_ADOPTION_OR_DIFFUSION.value:
        return ["github_search","github_issues","hackernews_relevance"]
    return ["hackernews_relevance","stackexchange","github_issues"]

def prerequisites(store: Store, thesis_id: str, gap: str) -> Tuple[bool,str]:
    rec=store.gap(thesis_id,GapType.INDEPENDENT_NEED_RECURRENCE.value)
    sup=store.gap(thesis_id,GapType.CURRENT_SOLUTION_SUPPLY.value)
    if gap==GapType.PEER_ADOPTION_OR_DIFFUSION.value and sup.confirmed < 1:
        return False,"WAITING_FOR_SOLUTION_SUPPLY_CONTEXT"
    if gap==GapType.PAYMENT_BEHAVIOR.value:
        if rec.confirmed < 1:return False,"WAITING_FOR_INDEPENDENT_NEED_RECURRENCE"
        if sup.confirmed < 1:return False,"WAITING_FOR_SOLUTION_SUPPLY_CONTEXT"
    return True,"READY"

def remaining(g) -> float:
    target=TARGET[g.gap_type]
    return max(0.0,1.0-min(g.confirmed,target)/target)

def resilient_voi(store: Store, g, state: dict, cost: float=0.035) -> float:
    ov=_overlay(state,g.gap_id)
    if g.confirmed >= TARGET[g.gap_type]:
        return 0.0
    # Only verified-negative outcomes reduce evidence-yield belief.
    p_confirm=(1+g.confirmed)/(3+g.confirmed+ov["verified_no_support_count"])
    # Empty retrieval affects source/query coverage belief mildly, never claim truth.
    retrieval_factor=1/(1+0.12*ov["retrieval_empty_count"])
    pending_penalty=1/(1+0.08*ov["verification_pending_count"])
    task_decay=1/math.sqrt(1+0.25*ov["logical_tasks"])
    gain=IMPACT[g.gap_type]*p_confirm*(remaining(g)**2)*retrieval_factor*pending_penalty*task_decay
    return round(max(0.0,gain-cost),6)

def next_untried_strategy(g, state: dict) -> Optional[Tuple[str,str]]:
    ov=_overlay(state,g.gap_id)
    qs=query_family(g.last_query or g.gap_type,g.gap_type)
    ads=adapter_family(g.gap_type)
    # Prefer never-tried query+adapter combinations.
    for q in qs:
        for a in ads:
            marker=q+"||"+a
            if marker not in ov.setdefault("strategies_tried",[]):
                return q,a
    return None

class GapVerifier:
    def __init__(self,max_calls:int=3):
        self.max_calls=max_calls
        self.calls=0
        self.enabled=bool(os.getenv("OPENAI_API_KEY")) and os.getenv("SIGNALFORGE_U16_ENABLE_LLM_VERIFY","1")!="0"
        self.model=os.getenv("SIGNALFORGE_U16_VERIFY_MODEL","gpt-5-mini")

    def _llm(self,gap:str,query:str,candidates:List[dict]) -> Dict[str,dict]:
        if not self.enabled or self.calls>=self.max_calls or not candidates:return {}
        self.calls+=1
        try:
            from openai import OpenAI
            client=OpenAI()
            items=[{"evidence_id":c["evidence_id"],"source_group":c["source_group"],"text":c["text"][:1800]} for c in candidates[:10]]
            if gap==GapType.INDEPENDENT_NEED_RECURRENCE.value:
                rule=(
                    "CONFIRMED_SUPPORT requires an independent firsthand or clearly user-reported instance of materially "
                    "the same workflow pain/constraint. Product announcements, vendor promotion, jobs, generic opinion, "
                    "and merely adjacent topics are not recurrence."
                )
            elif gap==GapType.PAYMENT_BEHAVIOR.value:
                rule=(
                    "CONFIRMED_SUPPORT requires explicit payment, purchase, subscription, spend/budget, or an explicit "
                    "price acceptance/willingness-to-pay statement for materially the same workflow. Popularity alone is not WTP."
                )
            else:
                rule="Be conservative and confirm only direct evidence for the named gap."
            prompt=(
                "Strict SignalForge evidence adjudication. Gap="+gap+". Problem/query frame="+query+". "
                +rule+
                " Return JSON only: {\"items\":[{\"evidence_id\":\"...\",\"judgment\":\"CONFIRMED_SUPPORT|"
                "CONFIRMED_REFUTE|RELATED_BUT_NOT_EVIDENCE|INSUFFICIENT\",\"rationale\":\"...\"}]}. "
                "Do not infer market size, opportunity quality, or build recommendation. Items="
                +json.dumps(items,ensure_ascii=False)
            )
            text=None
            if hasattr(client,"responses"):
                r=client.responses.create(model=self.model,input=prompt)
                text=getattr(r,"output_text",None)
            if not text and hasattr(client,"chat"):
                r=client.chat.completions.create(model=self.model,messages=[{"role":"user","content":prompt}],temperature=0)
                text=r.choices[0].message.content
            if not text:return {}
            m=re.search(r"\{.*\}",text,re.S)
            data=json.loads(m.group(0) if m else text)
            out={}
            for x in data.get("items") or []:
                j=str(x.get("judgment") or "")
                if j not in {"CONFIRMED_SUPPORT","CONFIRMED_REFUTE","RELATED_BUT_NOT_EVIDENCE","INSUFFICIENT"}:continue
                out[str(x.get("evidence_id") or "")]={"judgment":j,"rationale":str(x.get("rationale") or "")[:500]}
            return out
        except Exception as e:
            return {"__error__":{"judgment":"ERROR","rationale":f"{type(e).__name__}: {e}"[:500]}}

    def verify(self,gap:str,query:str,candidates:List[dict]) -> Dict[str,dict]:
        if gap in {GapType.INDEPENDENT_NEED_RECURRENCE.value,GapType.PAYMENT_BEHAVIOR.value}:
            return self._llm(gap,query,candidates)
        if gap==GapType.CURRENT_SOLUTION_SUPPLY.value:
            out={}
            q=set(_tokens(query))
            for c in candidates:
                if not c["evidence_id"].startswith("gh:"):continue
                overlap=len(q & set(_tokens(c.get("text") or "")))
                if overlap>=2 and not (c.get("meta") or {}).get("archived"):
                    j="CONFIRMED_SUPPORT";reason=f"relevant live repository establishes current solution supply; overlap={overlap}"
                else:
                    j="RELATED_BUT_NOT_EVIDENCE";reason=f"supply relevance insufficient; overlap={overlap}"
                out[c["evidence_id"]]={"judgment":j,"rationale":reason}
            return out
        if gap==GapType.PEER_ADOPTION_OR_DIFFUSION.value:
            out={}
            q=set(_tokens(query))
            for c in candidates:
                if c["evidence_id"].startswith("gh:"):
                    meta=c.get("meta") or {}
                    overlap=len(q & set(_tokens(c.get("text") or "")))
                    stars=int(meta.get("stars") or 0);forks=int(meta.get("forks") or 0)
                    if overlap>=2 and (forks>=1 or stars>=3):
                        out[c["evidence_id"]]={"judgment":"CONFIRMED_SUPPORT",
                            "rationale":f"gap-specific weak diffusion signal: relevant repo has stars={stars}, forks={forks}; not demand/WTP"}
                    elif overlap>=2:
                        out[c["evidence_id"]]={"judgment":"RELATED_BUT_NOT_EVIDENCE",
                            "rationale":f"relevant repo but insufficient peer diffusion signal; stars={stars}, forks={forks}"}
            return out
        return {}

def apply_judgments(g,candidates:List[dict],judgments:Dict[str,dict]) -> dict:
    confirmed=0;refuted=0;negative=0;dupes=0
    for c in candidates:
        j=(judgments.get(c["evidence_id"]) or {}).get("judgment")
        if j=="CONFIRMED_SUPPORT":
            g.adjudicated+=1
            sg=c["source_group"]
            if sg in g.confirmed_support_groups:
                g.dependent_duplicates+=1;dupes+=1
                judgments[c["evidence_id"]]["judgment"]="DEPENDENT_DUPLICATE"
            else:
                g.confirmed_support_groups.append(sg);confirmed+=1
        elif j=="CONFIRMED_REFUTE":
            g.adjudicated+=1;g.confirmed_refute+=1;refuted+=1
        elif j in {"RELATED_BUT_NOT_EVIDENCE","INSUFFICIENT"}:
            g.adjudicated+=1;g.related_or_insufficient+=1;negative+=1
    return {"confirmed":confirmed,"refuted":refuted,"verified_negative":negative,"duplicates":dupes}

class ResilientExecutor:
    def __init__(self,fetch_fn:Callable=fetch,verifier:Optional[GapVerifier]=None):
        self.fetch_fn=fetch_fn
        self.verifier=verifier or GapVerifier()

    def select(self,store:Store,state:dict,run_counts:Dict[str,int]) -> Optional[Tuple[str,str,object,float]]:
        scored=[]
        for card_id,tid in store.card_map.items():
            for gt in GapType:
                g=store.gap(tid,gt.value)
                if run_counts.get(g.gap_id,0)>=2:continue
                ok,_=prerequisites(store,tid,g.gap_type)
                if not ok:continue
                if not next_untried_strategy(g,state):continue
                v=resilient_voi(store,g,state)
                if v>0:scored.append((v,card_id,tid,g))
        if not scored:return None
        scored.sort(key=lambda x:x[0],reverse=True)
        v,card,tid,g=scored[0]
        return card,tid,g,v

    def run_task(self,store:Store,state:dict,card_id:str,tid:str,g,max_fetch_attempts:int=2) -> dict:
        ov=_overlay(state,g.gap_id)
        ov["logical_tasks"]+=1
        task_id="u16task_"+str(int(time.time()*1000))+"_"+str(ov["logical_tasks"])
        attempts=[]
        all_candidates=[]
        seen_eids=set()
        outcome="RETRIEVAL_EMPTY"

        for _ in range(max_fetch_attempts):
            strategy=next_untried_strategy(g,state)
            if not strategy:break
            q,adapter=strategy
            marker=q+"||"+adapter
            ov.setdefault("strategies_tried",[]).append(marker)
            if q not in ov["queries_tried"]:ov["queries_tried"].append(q)
            if adapter not in ov["adapters_tried"]:ov["adapters_tried"].append(adapter)
            ov["fetch_attempts"]+=1
            started=time.time()
            error=None
            try:cands=self.fetch_fn(adapter,q,10)
            except Exception as e:
                cands=[];error=f"{type(e).__name__}: {e}"
            # exact per-attempt candidate ownership
            unique=[]
            for c in cands:
                eid=str(c.get("evidence_id") or "")
                if eid and eid not in seen_eids:
                    seen_eids.add(eid);unique.append(c)
            cands=unique
            attempts.append({
                "query":q,"adapter":adapter,"seconds":round(time.time()-started,3),
                "error":error,"candidate_ids":[c["evidence_id"] for c in cands]
            })
            if cands:
                all_candidates.extend(cands)
                g.last_query=q;g.last_adapter=adapter
                break
            ov["retrieval_empty_count"]+=1

        g.attempts+=1
        g.retrieved_candidates+=len(all_candidates)

        judgments={}
        stats={"confirmed":0,"refuted":0,"verified_negative":0,"duplicates":0}
        if all_candidates:
            q=attempts[-1]["query"]
            judgments=self.verifier.verify(g.gap_type,q,all_candidates)
            usable={k:v for k,v in judgments.items() if not k.startswith("__")}
            if usable:
                stats=apply_judgments(g,all_candidates,judgments)
                if stats["confirmed"]>0:
                    outcome="CONFIRMED_SUPPORT";ov["confirmed_tasks"]+=1;g.zero_confirmed_yield_streak=0
                elif stats["refuted"]>0 or stats["verified_negative"]>0:
                    outcome="VERIFIED_NO_SUPPORT";ov["verified_no_support_count"]+=1
                    g.zero_confirmed_yield_streak+=1
                else:
                    outcome="VERIFICATION_PENDING";ov["verification_pending_count"]+=1
            else:
                outcome="VERIFICATION_PENDING";ov["verification_pending_count"]+=1
        else:
            outcome="RETRIEVAL_EMPTY"
            # retrieval failure is not evidence failure.
        ov["last_outcome"]=outcome

        if g.confirmed>=TARGET[g.gap_type]:
            ov["research_state"]="RESEARCH_SUFFICIENT"
        elif outcome=="VERIFICATION_PENDING":
            ov["research_state"]="WAITING_FOR_VERIFICATION"
        elif outcome=="RETRIEVAL_EMPTY":
            ov["research_state"]="SWITCH_QUERY_OR_SOURCE" if next_untried_strategy(g,state) else "RETRIEVAL_SPACE_EXHAUSTED"
        elif resilient_voi(store,g,state)<=0:
            ov["research_state"]="STOP_LOW_MARGINAL_VALUE"
        else:
            ov["research_state"]="ACTIVE"

        store._persist()
        row={
            "task_id":task_id,"card_id":card_id,"thesis_id":tid,"gap_id":g.gap_id,"gap":g.gap_type,
            "fetch_attempts":attempts,
            "candidate_ids":[c["evidence_id"] for c in all_candidates],
            "candidate_count":len(all_candidates),
            "judgments":judgments,
            "stats":stats,
            "outcome":outcome,
            "research_state":ov["research_state"],
            "marginal_voi_after":resilient_voi(store,g,state),
        }
        state["tasks"].append(row)
        state["founder_tasks_total"]+=1
        _atomic_json(STATE,state)
        return row

    def execute(self,store:Store,max_tasks:int=5) -> dict:
        state=_load_state()
        rows=[];run_counts={}
        for _ in range(max_tasks):
            sel=self.select(store,state,run_counts)
            if not sel:break
            card,tid,g,v=sel
            row=self.run_task(store,state,card,tid,g,2)
            rows.append(row)
            run_counts[g.gap_id]=run_counts.get(g.gap_id,0)+1
            state=_load_state()
        return {"tasks":rows,"task_count":len(rows),"verifier_calls":self.verifier.calls}

def dependency_aware_card_progress(store:Store,card_id:str) -> dict:
    state=_load_state()
    tid=store.card_map[card_id]
    rows=[];eligible=[]
    for gt in GapType:
        g=store.gap(tid,gt.value)
        ov=_overlay(state,g.gap_id)
        ok,why=prerequisites(store,tid,g.gap_type)
        v=resilient_voi(store,g,state) if ok else 0.0
        if g.confirmed>=TARGET[g.gap_type]:
            rs="RESEARCH_SUFFICIENT"
        elif not ok:
            rs="BLOCKED_"+why
        else:
            rs=ov.get("research_state") or "OPEN"
        row={
            "gap":g.gap_type,"gap_id":g.gap_id,
            "attempts":g.attempts,"retrieved_candidates":g.retrieved_candidates,
            "adjudicated":g.adjudicated,"confirmed_independent_support":g.confirmed,
            "confirmed_refute":g.confirmed_refute,"dependent_duplicates":g.dependent_duplicates,
            "research_outcome":ov.get("last_outcome"),"research_state":rs,
            "retrieval_empty_count":ov.get("retrieval_empty_count",0),
            "verification_pending_count":ov.get("verification_pending_count",0),
            "verified_no_support_count":ov.get("verified_no_support_count",0),
            "marginal_voi":v,"prerequisite":why,
        }
        rows.append(row)
        if ok and v>0 and rs!="RESEARCH_SUFFICIENT" and next_untried_strategy(g,state):
            eligible.append(row)
    eligible.sort(key=lambda x:x["marginal_voi"],reverse=True)
    best=(
        {"action":"CONTINUE_OR_SWITCH_RESEARCH_STRATEGY",**eligible[0]} if eligible else
        {"action":"NO_ELIGIBLE_POSITIVE_VALUE_RESEARCH","marginal_voi":0.0}
    )
    return {"card_id":card_id,"thesis_id":tid,"gap_progress":rows,"best_next_research":best,"truth_boundary":TRUTH_BOUNDARY}

def exploration_due() -> bool:
    s=_load_state()
    return ((int(s.get("cycle") or 0)+1)%4)==0

def finish_cycle(exploration_refreshed:bool) -> dict:
    s=_load_state()
    s["cycle"]=int(s.get("cycle") or 0)+1
    if exploration_refreshed:s["exploration_requests_total"]=int(s.get("exploration_requests_total") or 0)+6
    _atomic_json(STATE,s)
    f=int(s.get("founder_tasks_total") or 0);e=int(s.get("exploration_requests_total") or 0);total=f+e
    return {
        "cycle":s["cycle"],"founder_tasks_total":f,"exploration_requests_total":e,
        "founder_share":round(f/total,4) if total else None,
        "exploration_share":round(e/total,4) if total else None,
        "next_periodic_exploration_due":((s["cycle"]+1)%4)==0,
    }
