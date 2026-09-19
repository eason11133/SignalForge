from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from processors.founder_thesis_research_control_u14 import Store, GapType
import processors.founder_research_resilience_u16 as u16

ENGINE_VERSION = "signalforge-evidence-adjudication-u17-v1"
STATE = Path(".radar_runtime/evidence_adjudication_u17.json")
U16_STATE = Path(".radar_runtime/founder_research_resilience_u16.json")
TRUTH_BOUNDARY = (
    "PENDING_EVIDENCE_CREATES_BACKPRESSURE_NOT_NEGATIVE_EVIDENCE; "
    "VERIFIER_UNAVAILABLE_BLOCKS_MORE SAME-GAP RETRIEVAL INSTEAD OF FAKING A JUDGMENT; "
    "ONLY GAP_SPECIFIC ADJUDICATION UPDATES CONFIRMED/REFUTED EVIDENCE; PRODUCT_IDEATION=0"
)

FINAL_STATUSES = {
    "CONFIRMED_SUPPORT","CONFIRMED_REFUTE","RELATED_BUT_NOT_EVIDENCE",
    "INSUFFICIENT","DEPENDENT_DUPLICATE"
}

def load_project_env(repo: Optional[Path]=None) -> dict:
    repo=(repo or Path.cwd()).resolve()
    env_path=repo/".env"
    before=bool(os.getenv("OPENAI_API_KEY"))
    method="PROCESS_ENV"
    loaded=False
    if not before and env_path.exists():
        try:
            from dotenv import load_dotenv
            load_dotenv(dotenv_path=env_path,override=False)
            loaded=bool(os.getenv("OPENAI_API_KEY"))
            method="PYTHON_DOTENV"
        except Exception:
            # Conservative fallback for simple KEY=VALUE .env lines.
            try:
                for raw in env_path.read_text(encoding="utf-8").splitlines():
                    line=raw.strip()
                    if not line or line.startswith("#") or "=" not in line:continue
                    k,v=line.split("=",1)
                    k=k.strip();v=v.strip()
                    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*",k):continue
                    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                        v=v[1:-1]
                    os.environ.setdefault(k,v)
                loaded=bool(os.getenv("OPENAI_API_KEY"))
                method="FALLBACK_ENV_PARSER"
            except Exception:
                method="ENV_LOAD_FAILED"
    return {
        "env_file_exists":env_path.exists(),
        "openai_key_before":before,
        "openai_key_after":bool(os.getenv("OPENAI_API_KEY")),
        "loaded_from_file":loaded,
        "method":method,
    }

def _fresh_state() -> dict:
    return {
        "engine_version":ENGINE_VERSION,
        "provider":{"status":"UNKNOWN","checked_at":None},
        "queue":{},
        "migrated_u16_tasks":[],
        "adjudication_runs":[],
        "retrieval_tasks_started":0,
    }

def _load() -> dict:
    if not STATE.exists():return _fresh_state()
    d=json.loads(STATE.read_text(encoding="utf-8"))
    if d.get("engine_version")!=ENGINE_VERSION:raise RuntimeError("U17_STATE_VERSION_MISMATCH")
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

def provider_status(repo: Optional[Path]=None) -> dict:
    env=load_project_env(repo)
    status="AVAILABLE" if env["openai_key_after"] else "UNAVAILABLE"
    out={"status":status,"checked_at":time.time(),"env":env}
    s=_load();s["provider"]=out;_atomic(STATE,s)
    return out

def queue_key(task_id: str,evidence_id: str,gap_id: str) -> str:
    import hashlib
    raw=(task_id+"\x1f"+evidence_id+"\x1f"+gap_id).encode()
    return "qev_"+hashlib.sha256(raw).hexdigest()[:24]

def _u16_tasks() -> List[dict]:
    if not U16_STATE.exists():return []
    try:return list((json.loads(U16_STATE.read_text(encoding="utf-8")) or {}).get("tasks") or [])
    except Exception:return []

def _rehydrate_task(task: dict,fetch_fn: Callable=u16.fetch) -> Tuple[List[dict],dict]:
    target=set(str(x) for x in (task.get("candidate_ids") or []))
    found={}
    attempts_audit=[]
    for a in task.get("fetch_attempts") or []:
        q=str(a.get("query") or "")
        adapter=str(a.get("adapter") or "")
        error=None
        rows=[]
        try:rows=fetch_fn(adapter,q,20)
        except Exception as e:error=f"{type(e).__name__}: {e}"
        for c in rows or []:
            eid=str(c.get("evidence_id") or "")
            if eid in target:found[eid]=c
        attempts_audit.append({"query":q,"adapter":adapter,"error":error,"matched":len(found)})
        if target and target.issubset(found.keys()):break
    return [found[x] for x in target if x in found],{
        "target_count":len(target),"rehydrated_count":len(found),
        "missing_ids":sorted(target-set(found)),"attempts":attempts_audit
    }

def enqueue_from_task(task: dict,candidates: List[dict]) -> int:
    s=_load();added=0
    judgments=task.get("judgments") or {}
    by_id={str(c.get("evidence_id") or ""):c for c in candidates}
    for eid in task.get("candidate_ids") or []:
        eid=str(eid)
        existing_j=(judgments.get(eid) or {}).get("judgment")
        if existing_j in FINAL_STATUSES:continue
        c=by_id.get(eid)
        if not c:continue
        k=queue_key(str(task.get("task_id") or ""),eid,str(task.get("gap_id") or ""))
        if k in s["queue"]:continue
        last_attempt=(task.get("fetch_attempts") or [{}])[-1]
        s["queue"][k]={
            "queue_id":k,
            "status":"PENDING",
            "created_at":time.time(),
            "task_id":task.get("task_id"),
            "card_id":task.get("card_id"),
            "thesis_id":task.get("thesis_id"),
            "gap_id":task.get("gap_id"),
            "gap":task.get("gap"),
            "query":last_attempt.get("query"),
            "adapter":last_attempt.get("adapter"),
            "evidence_id":eid,
            "source_ref":c.get("source_ref"),
            "source_group":c.get("source_group"),
            "text":c.get("text"),
            "meta":c.get("meta") or {},
            "judgment":None,
            "rationale":None,
            "adjudicated_at":None,
        }
        added+=1
    _atomic(STATE,s)
    return added

def migrate_u16_pending(fetch_fn: Callable=u16.fetch) -> dict:
    s=_load()
    migrated=set(s.get("migrated_u16_tasks") or [])
    summary={"tasks_seen":0,"tasks_migrated":0,"queue_added":0,"rehydrated":0,"missing":0}
    for task in _u16_tasks():
        if task.get("outcome")!="VERIFICATION_PENDING":continue
        tid=str(task.get("task_id") or "")
        if not tid or tid in migrated:continue
        summary["tasks_seen"]+=1
        cands,audit=_rehydrate_task(task,fetch_fn)
        summary["rehydrated"]+=audit["rehydrated_count"]
        summary["missing"]+=len(audit["missing_ids"])
        added=enqueue_from_task(task,cands)
        summary["queue_added"]+=added
        migrated.add(tid);summary["tasks_migrated"]+=1
    s=_load();s["migrated_u16_tasks"]=sorted(migrated);_atomic(STATE,s)
    return summary

def pending_for_gap(gap_id: str) -> List[dict]:
    s=_load()
    return [x for x in s["queue"].values() if x.get("gap_id")==gap_id and x.get("status")=="PENDING"]

def pending_total() -> int:
    return sum(1 for x in _load()["queue"].values() if x.get("status")=="PENDING")

class QueueVerifier:
    def __init__(self,max_calls:int=3,client_factory=None):
        self.max_calls=max_calls;self.calls=0
        self.model=os.getenv("SIGNALFORGE_U17_VERIFY_MODEL","gpt-5-mini")
        self.client_factory=client_factory
        self.available=bool(os.getenv("OPENAI_API_KEY")) or client_factory is not None

    def _prompt(self,gap:str,items:List[dict]) -> str:
        if gap==GapType.INDEPENDENT_NEED_RECURRENCE.value:
            rule=(
                "CONFIRMED_SUPPORT requires an independent firsthand or clearly user-reported recurrence of materially "
                "the same workflow pain/constraint. Vendor/product announcements, jobs, generic advice, feature requests "
                "without the same pain, and adjacent topics are not recurrence."
            )
        elif gap==GapType.PEER_ADOPTION_OR_DIFFUSION.value:
            rule=(
                "CONFIRMED_SUPPORT requires direct peer adoption/diffusion evidence for a materially relevant solution "
                "or workaround: actual use, forks, stars with contextual relevance, adoption comments, integrations, or "
                "user requests. Mere repository existence is supply, not diffusion."
            )
        elif gap==GapType.PAYMENT_BEHAVIOR.value:
            rule=(
                "CONFIRMED_SUPPORT requires explicit payment/purchase/subscription/spend/budget or explicit willingness "
                "to pay for materially the same workflow. Popularity or pain alone is not payment behavior."
            )
        else:
            rule="Confirm only direct evidence for the named gap."
        compact=[{
            "queue_id":x["queue_id"],"evidence_id":x["evidence_id"],
            "source_group":x["source_group"],"text":(x.get("text") or "")[:1800]
        } for x in items[:10]]
        return (
            "Strict SignalForge evidence adjudication. Gap="+gap+". "+rule+
            " Return JSON only: {\"items\":[{\"queue_id\":\"...\",\"judgment\":\"CONFIRMED_SUPPORT|"
            "CONFIRMED_REFUTE|RELATED_BUT_NOT_EVIDENCE|INSUFFICIENT\",\"rationale\":\"...\"}]}. "
            "Do not infer market size, WTP unless the gap is PAYMENT_BEHAVIOR, opportunity quality, or build recommendation. "
            "Items="+json.dumps(compact,ensure_ascii=False)
        )

    def adjudicate_group(self,gap:str,items:List[dict]) -> Dict[str,dict]:
        if not self.available or self.calls>=self.max_calls or not items:return {}
        self.calls+=1
        try:
            if self.client_factory:
                client=self.client_factory()
            else:
                from openai import OpenAI
                client=OpenAI()
            prompt=self._prompt(gap,items)
            text=None
            if hasattr(client,"responses"):
                r=client.responses.create(model=self.model,input=prompt)
                text=getattr(r,"output_text",None)
            if not text and hasattr(client,"chat"):
                r=client.chat.completions.create(
                    model=self.model,messages=[{"role":"user","content":prompt}],temperature=0
                )
                text=r.choices[0].message.content
            if not text:return {}
            m=re.search(r"\{.*\}",text,re.S)
            data=json.loads(m.group(0) if m else text)
            out={}
            for x in data.get("items") or []:
                qid=str(x.get("queue_id") or "")
                j=str(x.get("judgment") or "")
                if j not in {"CONFIRMED_SUPPORT","CONFIRMED_REFUTE","RELATED_BUT_NOT_EVIDENCE","INSUFFICIENT"}:continue
                out[qid]={"judgment":j,"rationale":str(x.get("rationale") or "")[:500]}
            return out
        except Exception as e:
            return {"__error__":{"judgment":"ERROR","rationale":f"{type(e).__name__}: {e}"[:500]}}

def _apply_to_store(store:Store,item:dict,judgment:str) -> str:
    gid=str(item["gap_id"]);g=store.gaps[gid]
    if judgment=="CONFIRMED_SUPPORT":
        sg=str(item.get("source_group") or item.get("evidence_id"))
        if sg in g.confirmed_support_groups:
            g.dependent_duplicates+=1
            return "DEPENDENT_DUPLICATE"
        g.confirmed_support_groups.append(sg);g.adjudicated+=1
    elif judgment=="CONFIRMED_REFUTE":
        g.confirmed_refute+=1;g.adjudicated+=1
    elif judgment in {"RELATED_BUT_NOT_EVIDENCE","INSUFFICIENT"}:
        g.related_or_insufficient+=1;g.adjudicated+=1
    store._persist()
    return judgment

def adjudicate_pending(store:Store,verifier:Optional[QueueVerifier]=None,max_groups:int=3) -> dict:
    verifier=verifier or QueueVerifier(max_groups)
    s=_load()
    pending=[x for x in s["queue"].values() if x.get("status")=="PENDING"]
    by_gap={}
    for x in pending:by_gap.setdefault(x["gap"],[]).append(x)
    summary={"pending_before":len(pending),"groups_attempted":0,"verifier_calls":0,"resolved":0,"pending_after":0,"error":None}
    for gap,items in sorted(by_gap.items(),key=lambda kv:len(kv[1]),reverse=True):
        if summary["groups_attempted"]>=max_groups:break
        summary["groups_attempted"]+=1
        result=verifier.adjudicate_group(gap,items)
        if "__error__" in result:
            summary["error"]=result["__error__"]["rationale"]
            continue
        for qid,r in result.items():
            if qid not in s["queue"] or s["queue"][qid]["status"]!="PENDING":continue
            final=_apply_to_store(store,s["queue"][qid],r["judgment"])
            s["queue"][qid]["status"]=final
            s["queue"][qid]["judgment"]=final
            s["queue"][qid]["rationale"]=r.get("rationale")
            s["queue"][qid]["adjudicated_at"]=time.time()
            summary["resolved"]+=1
    summary["verifier_calls"]=verifier.calls
    summary["pending_after"]=sum(1 for x in s["queue"].values() if x.get("status")=="PENDING")
    s["provider"]={
        "status":"AVAILABLE" if verifier.available else "UNAVAILABLE",
        "checked_at":time.time(),
        "last_calls":verifier.calls,
        "last_error":summary["error"],
    }
    s["adjudication_runs"].append({**summary,"at":time.time()})
    _atomic(STATE,s)
    return summary

def _gap_blocked_by_pending(store:Store,g,provider_available:bool) -> Tuple[bool,str]:
    p=len(pending_for_gap(g.gap_id))
    if p<=0:return False,"NO_PENDING_BACKLOG"
    if not provider_available:return True,"BLOCKED_VERIFIER_UNAVAILABLE"
    return True,"PENDING_FIRST"

def select_new_retrieval(store:Store,provider_available:bool) -> Optional[Tuple[str,str,object,float]]:
    # Use U16 decision semantics, but enforce adjudication backpressure.
    state16=u16._load_state()
    scored=[]
    for card_id,tid in store.card_map.items():
        for gt in GapType:
            g=store.gap(tid,gt.value)
            ok,_=u16.prerequisites(store,tid,g.gap_type)
            if not ok:continue
            blocked,_=_gap_blocked_by_pending(store,g,provider_available)
            if blocked:continue
            # Recurrence/payment need verifier. Don't create new candidates if adjudication is unavailable.
            if g.gap_type in {GapType.INDEPENDENT_NEED_RECURRENCE.value,GapType.PAYMENT_BEHAVIOR.value} and not provider_available:
                continue
            if not u16.next_untried_strategy(g,state16):continue
            v=u16.resilient_voi(store,g,state16)
            if v>0:scored.append((v,card_id,tid,g))
    if not scored:return None
    scored.sort(key=lambda x:x[0],reverse=True)
    v,card,tid,g=scored[0]
    return card,tid,g,v

class NoopGapVerifier:
    calls=0
    def verify(self,gap,q,cands):return {}

def run_one_retrieval(store:Store,fetch_fn:Callable=u16.fetch) -> Optional[dict]:
    status=_load().get("provider") or {}
    provider_available=status.get("status")=="AVAILABLE"
    sel=select_new_retrieval(store,provider_available)
    if not sel:return None
    card,tid,g,v=sel
    ex=u16.ResilientExecutor(fetch_fn=fetch_fn,verifier=NoopGapVerifier())
    state16=u16._load_state()
    row=ex.run_task(store,state16,card,tid,g,max_fetch_attempts=2)
    s=_load();s["retrieval_tasks_started"]+=1;_atomic(STATE,s)
    # If U16 deterministic verifier could not judge the candidates, persist the full evidence now.
    if row.get("outcome")=="VERIFICATION_PENDING":
        cands,audit=_rehydrate_task(row,fetch_fn)
        enqueue_from_task(row,cands)
        row["u17_queue_rehydration"]=audit
    return row

def card_progress(store:Store,card_id:str) -> dict:
    base=u16.dependency_aware_card_progress(store,card_id)
    s=_load();provider=(s.get("provider") or {}).get("status","UNKNOWN")
    for row in base["gap_progress"]:
        p=[x for x in s["queue"].values() if x.get("gap_id")==row["gap_id"] and x.get("status")=="PENDING"]
        row["pending_adjudication"]=len(p)
        if p:
            row["research_state"]="PENDING_FIRST" if provider=="AVAILABLE" else "BLOCKED_VERIFIER_UNAVAILABLE"
            row["marginal_voi_for_new_retrieval"]=0.0
        elif row["gap"] in {GapType.INDEPENDENT_NEED_RECURRENCE.value,GapType.PAYMENT_BEHAVIOR.value} and provider!="AVAILABLE":
            row["research_state"]="BLOCKED_VERIFIER_UNAVAILABLE"
            row["marginal_voi_for_new_retrieval"]=0.0
        else:
            row["marginal_voi_for_new_retrieval"]=row.get("marginal_voi",0.0)
    eligible=[r for r in base["gap_progress"] if r.get("marginal_voi_for_new_retrieval",0)>0 and not str(r["research_state"]).startswith("BLOCKED")]
    eligible.sort(key=lambda x:x["marginal_voi_for_new_retrieval"],reverse=True)
    if pending_total()>0 and provider=="AVAILABLE":
        best={"action":"ADJUDICATE_PENDING_EVIDENCE_FIRST","pending_total":pending_total()}
    elif eligible:
        best={"action":"RETRIEVE_NEXT_GAP",**eligible[0]}
    elif pending_total()>0:
        best={"action":"BLOCKED_VERIFIER_UNAVAILABLE","pending_total":pending_total()}
    else:
        best={"action":"NO_ELIGIBLE_RESEARCH","pending_total":0}
    base["best_next_research"]=best
    base["provider_status"]=provider
    base["truth_boundary"]=TRUTH_BOUNDARY
    return base

def execute_cycle(store:Store,max_new_tasks:int=2,verifier:Optional[QueueVerifier]=None,fetch_fn:Callable=u16.fetch) -> dict:
    verifier=verifier or QueueVerifier(max_calls=3)
    before=adjudicate_pending(store,verifier,max_groups=3)
    retrieval=[]
    # Backpressure: only retrieve when there is no pending adjudication left for the selected path.
    for _ in range(max_new_tasks):
        if pending_total()>0:
            more=adjudicate_pending(store,verifier,max_groups=3)
            if more["resolved"]==0:break
        row=run_one_retrieval(store,fetch_fn)
        if not row:break
        retrieval.append(row)
        if row.get("outcome")=="VERIFICATION_PENDING":
            adjudicate_pending(store,verifier,max_groups=3)
    return {
        "pre_adjudication":before,
        "retrieval_tasks":retrieval,
        "retrieval_task_count":len(retrieval),
        "pending_after":pending_total(),
        "provider_status":(_load().get("provider") or {}).get("status"),
        "verifier_calls":verifier.calls,
    }
