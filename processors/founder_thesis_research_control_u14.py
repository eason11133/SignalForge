from __future__ import annotations
import ast, hashlib, json, math, os, tempfile, time
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional

ENGINE_VERSION = "signalforge-founder-thesis-control-u14-v1"
STATE_PATH = Path(".radar_runtime/founder_thesis_research_u14.json")
TRUTH_BOUNDARY = (
    "U14_RESEARCH_CONTROL_CHANGES_RESEARCH_PRIORITY_AND_STATE_ONLY; "
    "RETRIEVED_OR_LEGACY_CANDIDATES_DO_NOT_ESTABLISH_DEMAND_WTP_OR_GAP_CLOSURE; "
    "PRODUCT_IDEATION_REMAINS_DISABLED"
)

class GapType(str, Enum):
    INDEPENDENT_NEED_RECURRENCE="INDEPENDENT_NEED_RECURRENCE"
    CURRENT_SOLUTION_SUPPLY="CURRENT_SOLUTION_SUPPLY"
    PEER_ADOPTION_OR_DIFFUSION="PEER_ADOPTION_OR_DIFFUSION"
    PAYMENT_BEHAVIOR="PAYMENT_BEHAVIOR"

IMPACT={
    GapType.INDEPENDENT_NEED_RECURRENCE:1.0,
    GapType.CURRENT_SOLUTION_SUPPLY:0.78,
    GapType.PEER_ADOPTION_OR_DIFFUSION:0.72,
    GapType.PAYMENT_BEHAVIOR:0.92,
}
TARGET={
    GapType.INDEPENDENT_NEED_RECURRENCE:3,
    GapType.CURRENT_SOLUTION_SUPPLY:3,
    GapType.PEER_ADOPTION_OR_DIFFUSION:3,
    GapType.PAYMENT_BEHAVIOR:2,
}

def sid(prefix,*parts):
    raw="\x1f".join(str(x) for x in parts).encode()
    return prefix+"_"+hashlib.sha256(raw).hexdigest()[:20]

@dataclass
class Gap:
    thesis_id:str
    gap_id:str
    gap_type:str
    attempts:int=0
    retrieved_candidates:int=0
    adjudicated:int=0
    confirmed_support_groups:List[str]=field(default_factory=list)
    confirmed_refute:int=0
    related_or_insufficient:int=0
    dependent_duplicates:int=0
    zero_confirmed_yield_streak:int=0
    last_query:Optional[str]=None
    last_adapter:Optional[str]=None
    last_surface:Optional[str]=None
    state:str="OPEN"

    @property
    def confirmed(self): return len(set(self.confirmed_support_groups))

@dataclass
class Thesis:
    thesis_id:str
    card_id:str
    thesis_type:str
    title:str
    aliases:List[str]=field(default_factory=list)
    created_at:float=field(default_factory=time.time)
    active:bool=True

class Store:
    def __init__(self,path=STATE_PATH):
        self.path=Path(path)
        self.theses:Dict[str,Thesis]={}
        self.card_map:Dict[str,str]={}
        self.gaps:Dict[str,Gap]={}
        self.legacy_orphans:List[dict]=[]
        if self.path.exists(): self.load()

    def _persist(self):
        p={
          "engine_version":ENGINE_VERSION,
          "truth_boundary":TRUTH_BOUNDARY,
          "theses":{k:asdict(v) for k,v in self.theses.items()},
          "card_map":self.card_map,
          "gaps":{k:asdict(v) for k,v in self.gaps.items()},
          "legacy_orphans":self.legacy_orphans[-500:],
        }
        self.path.parent.mkdir(parents=True,exist_ok=True)
        fd,tmp=tempfile.mkstemp(prefix=self.path.name+".",suffix=".tmp",dir=str(self.path.parent))
        try:
            with os.fdopen(fd,"w",encoding="utf-8") as f:
                json.dump(p,f,ensure_ascii=False,indent=2,sort_keys=True)
                f.flush();os.fsync(f.fileno())
            os.replace(tmp,self.path)
        finally:
            if os.path.exists(tmp): os.unlink(tmp)

    def load(self):
        p=json.loads(self.path.read_text(encoding="utf-8"))
        if p.get("engine_version")!=ENGINE_VERSION:
            raise RuntimeError("U14_STATE_VERSION_MISMATCH")
        self.theses={k:Thesis(**v) for k,v in (p.get("theses") or {}).items()}
        self.card_map=dict(p.get("card_map") or {})
        self.gaps={k:Gap(**v) for k,v in (p.get("gaps") or {}).items()}
        self.legacy_orphans=list(p.get("legacy_orphans") or [])

    def register_card(self,card:dict):
        cid=str(card.get("id") or "")
        ctype=str(card.get("type") or "UNKNOWN")
        if not cid: raise ValueError("FOUNDER_CARD_ID_MISSING")
        tid=self.card_map.get(cid) or sid("thesis",ctype,cid)
        if tid not in self.theses:
            self.theses[tid]=Thesis(tid,cid,ctype,cid,[cid])
        self.card_map[cid]=tid
        for gt in GapType:
            gid=sid("gap",tid,gt.value)
            self.gaps.setdefault(gid,Gap(tid,gid,gt.value))
        self._persist()
        return self.theses[tid]

    def gap(self,tid,gt):
        return self.gaps[sid("gap",tid,GapType(gt).value)]

    def _p_confirm(self,g):
        # Conservative prior. Retrieved-but-unverified documents are NOT successes.
        failures=g.related_or_insufficient+g.dependent_duplicates
        return (1+g.confirmed)/(3+g.confirmed+failures)

    def _remaining(self,g):
        t=TARGET[GapType(g.gap_type)]
        return max(0.0,1.0-min(g.confirmed,t)/t)

    def mvoi(self,g,cost=0.08):
        impact=IMPACT[GapType(g.gap_type)]
        p=self._p_confirm(g)
        remaining=self._remaining(g)
        independent=(1+g.confirmed)/(2+g.confirmed+g.dependent_duplicates)
        attempt_decay=1/math.sqrt(1+0.6*g.attempts)
        streak=1/(1+0.8*g.zero_confirmed_yield_streak)
        gain=impact*p*(remaining**2)*independent*attempt_decay*streak
        return round(max(0.0,gain-cost),6)

    def attach_plan(self,tid,plan:dict):
        for step in plan.get("next_steps") or []:
            ev=step.get("evidence")
            if ev not in {x.value for x in GapType}: continue
            g=self.gap(tid,ev)
            if step.get("query"): g.last_query=str(step["query"])
        self._persist()

    def ingest_legacy_u13_rows_as_unverified(self,rows:list,known_cards:list):
        # Critical U14 migration rule:
        # U13 frag_* rows cannot be attached to Founder cards without explicit lineage.
        # Preserve as orphan telemetry only.
        seen={(x.get("anchor_key"),x.get("evidence_gap"),x.get("last_attempt")) for x in self.legacy_orphans}
        added=0
        for r in rows or []:
            key=(r.get("anchor_key"),r.get("evidence_gap"),r.get("last_attempt"))
            if key in seen: continue
            self.legacy_orphans.append({
              "anchor_key":r.get("anchor_key"),
              "evidence_gap":r.get("evidence_gap"),
              "attempts":r.get("attempts",0),
              "retrieved_candidates":r.get("downstream_evidence_docs",0),
              "legacy_voi":((r.get("voi") or {}).get("expected_information_value")),
              "migration_state":"U13_UNVERIFIED_ORPHAN_NOT_ATTACHED_TO_FOUNDER_THESIS",
            })
            seen.add(key);added+=1
        if added:self._persist()
        return added

    def card_progress(self,card_id,cost=0.08):
        tid=self.card_map[card_id]
        gs=[g for g in self.gaps.values() if g.thesis_id==tid]
        order=[x.value for x in GapType]
        gs.sort(key=lambda g:order.index(g.gap_type))
        rows=[]
        for g in gs:
            v=self.mvoi(g,cost)
            if g.confirmed>=TARGET[GapType(g.gap_type)]: state="SATURATED"
            elif v<=0: state="STOP_LOW_MARGINAL_VALUE"
            elif g.zero_confirmed_yield_streak>=2: state="SWITCH_QUERY_OR_SOURCE"
            else: state=g.state
            rows.append({
              "gap":g.gap_type,"gap_id":g.gap_id,"attempts":g.attempts,
              "retrieved_candidates":g.retrieved_candidates,
              "adjudicated":g.adjudicated,
              "confirmed_independent_support":g.confirmed,
              "confirmed_refute":g.confirmed_refute,
              "dependent_duplicates":g.dependent_duplicates,
              "zero_confirmed_yield_streak":g.zero_confirmed_yield_streak,
              "state":state,"marginal_voi":v,"last_query":g.last_query,
            })
        positive=[x for x in rows if x["marginal_voi"]>0 and x["state"]!="SATURATED"]
        positive.sort(key=lambda x:x["marginal_voi"],reverse=True)
        next_action=(
          {"action":"CONTINUE_HIGHEST_MARGINAL_VALUE_GAP",**positive[0]} if positive else
          {"action":"STOP_THESIS_RESEARCH_AND_RETURN_BUDGET_TO_EXPLORATION","marginal_voi":0.0}
        )
        return {"card_id":card_id,"thesis_id":tid,"gap_progress":rows,"best_next_research":next_action}

    def budget(self,total=6,cost=0.08):
        active=False
        for cid in self.card_map:
            p=self.card_progress(cid,cost)
            if p["best_next_research"].get("marginal_voi",0)>0: active=True;break
        if not active:return {"founder_directed":0,"exploration":total}
        founder=max(1,math.ceil(total*0.75))
        return {"founder_directed":min(total,founder),"exploration":max(0,total-founder)}

def parse_labeled_literal(stdout:str,label:str,default):
    prefix=label+" "
    for line in stdout.splitlines():
        if line.startswith(prefix):
            raw=line[len(prefix):].strip()
            try:return ast.literal_eval(raw)
            except Exception:return default
    return default

def assimilate_u13_stdout(stdout:str,cost=0.08):
    cards=parse_labeled_literal(stdout,"U13_FOUNDER_CARD_PROGRESS",[])
    gaps=parse_labeled_literal(stdout,"U13_EVIDENCE_GAPS",{})
    if isinstance(gaps,dict):gap_rows=gaps.get("rows") or []
    else:gap_rows=[]
    store=Store()
    mapped=[]
    for card in cards or []:
        t=store.register_card(card)
        store.attach_plan(t.thesis_id,card.get("best_next_evidence") or {})
        mapped.append(store.card_progress(card["id"],cost))
    orphan_added=store.ingest_legacy_u13_rows_as_unverified(gap_rows,cards or [])
    return {
      "engine_version":ENGINE_VERSION,
      "founder_cards":mapped,
      "budget":store.budget(6,cost),
      "legacy_u13_orphans_added":orphan_added,
      "legacy_u13_orphans_total":len(store.legacy_orphans),
      "truth_boundary":TRUTH_BOUNDARY,
    }
