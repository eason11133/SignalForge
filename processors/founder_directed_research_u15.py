from __future__ import annotations

import html
import json
import os
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from processors.founder_thesis_research_control_u14 import Store, GapType, STATE_PATH

ENGINE_VERSION = "signalforge-founder-directed-acquisition-u15-v1"
STATE = Path(".radar_runtime/founder_directed_research_u15.json")
DEFAULT_FOUNDER_REQUESTS = 5
EXPLORATION_REFRESH_EVERY = 4
U13_EXPLORATION_REQUESTS_PER_REFRESH = 6
TRUTH_BOUNDARY = (
    "FOUNDER_DIRECTED_ACQUISITION_MAY_UPDATE_RESEARCH_ATTEMPTS_AND_VERIFIED_GAP_EVIDENCE_ONLY; "
    "RETRIEVAL_ALONE_NEVER_ESTABLISHES_DEMAND_WTP_OR_BUILD_RECOMMENDATION; "
    "LEGACY_U13_EXPLORATION_REMAINS_SEPARATE_FROM_FOUNDER_THESIS EVIDENCE"
)

STOPWORDS = {
    "research","the","a","an","and","or","to","from","for","of","in","on","with",
    "using","use","tool","tools","generate","generation","local","llm","llms"
}

def _load_state() -> dict:
    if not STATE.exists():
        return {
            "engine_version": ENGINE_VERSION,
            "cycle": 0,
            "founder_requests_total": 0,
            "exploration_requests_total": 0,
            "requests": [],
            "query_history": [],
        }
    d=json.loads(STATE.read_text(encoding="utf-8"))
    if d.get("engine_version") != ENGINE_VERSION:
        raise RuntimeError("U15_STATE_VERSION_MISMATCH")
    return d

def _atomic_json(path: Path, payload: dict) -> None:
    import tempfile
    path.parent.mkdir(parents=True, exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix=path.name+".",suffix=".tmp",dir=str(path.parent))
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as f:
            json.dump(payload,f,ensure_ascii=False,indent=2,sort_keys=True)
            f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)

def _strip_html(s: str) -> str:
    s=html.unescape(s or "")
    s=re.sub(r"<[^>]+>"," ",s)
    return re.sub(r"\s+"," ",s).strip()

def _tokens(q: str) -> List[str]:
    out=[]
    for x in re.findall(r"[A-Za-z0-9][A-Za-z0-9_+-]{2,}", (q or "").lower()):
        if x not in STOPWORDS and x not in out:
            out.append(x)
    return out

def _compact_query(q: str, max_terms: int = 7) -> str:
    toks=_tokens(q)
    if not toks:
        toks=re.findall(r"[A-Za-z0-9][A-Za-z0-9_+-]{2,}",(q or "").lower())
    return " ".join(toks[:max_terms]).strip()

def query_variant(base: str, gap: str, attempt: int) -> str:
    q=_compact_query(base)
    variants={
        GapType.INDEPENDENT_NEED_RECURRENCE.value:[
            q,
            _compact_query(q+" tedious manual annoying problem"),
            _compact_query(q+" privacy formatting citations workflow"),
        ],
        GapType.CURRENT_SOLUTION_SUPPLY.value:[
            q,
            _compact_query(q+" software app github"),
            _compact_query(q+" open source product"),
        ],
        GapType.PEER_ADOPTION_OR_DIFFUSION.value:[
            q,
            _compact_query(q+" adoption users forks stars"),
            _compact_query(q+" community use"),
        ],
        GapType.PAYMENT_BEHAVIOR.value:[
            q,
            _compact_query(q+" paid price subscription"),
            _compact_query(q+" willing pay"),
        ],
    }
    arr=variants.get(gap,[q])
    return arr[attempt % len(arr)] or q

def _http_json(url: str, headers: Optional[dict]=None, timeout: int=12) -> dict:
    h={"User-Agent":"SignalForge-U15/1.0"}
    if headers:h.update(headers)
    req=urllib.request.Request(url,headers=h)
    with urllib.request.urlopen(req,timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8","replace"))

def search_hn(query: str, limit: int=10) -> List[dict]:
    url="https://hn.algolia.com/api/v1/search_by_date?"+urllib.parse.urlencode({"query":query,"hitsPerPage":limit})
    d=_http_json(url)
    out=[]
    for x in d.get("hits") or []:
        text=_strip_html(" ".join(str(x.get(k) or "") for k in ("title","story_title","story_text","comment_text")))
        if not text: continue
        oid=str(x.get("objectID") or "")
        author=str(x.get("author") or "unknown")
        out.append({
            "evidence_id":"hn:"+oid,
            "source_ref":"https://news.ycombinator.com/item?id="+oid if oid else "hn:"+author,
            "source_group":"hn_author:"+author,
            "text":text[:5000],
            "meta":{"author":author,"created_at":x.get("created_at")},
        })
    return out

def _stack_site(query: str) -> str:
    t=set(_tokens(query))
    if {"paper","papers","academic","slides","presentation"} & t:
        return "academia"
    if {"code","programmer","api","python","javascript","software"} & t:
        return "stackoverflow"
    return "superuser"

def search_stackexchange(query: str, limit: int=10) -> List[dict]:
    params={
        "order":"desc","sort":"relevance","q":query,
        "site":_stack_site(query),"filter":"withbody","pagesize":limit,
    }
    url="https://api.stackexchange.com/2.3/search/advanced?"+urllib.parse.urlencode(params)
    d=_http_json(url)
    out=[]
    for x in d.get("items") or []:
        owner=x.get("owner") or {}
        uid=str(owner.get("user_id") or owner.get("display_name") or "unknown")
        qid=str(x.get("question_id") or "")
        text=_strip_html((x.get("title") or "")+" "+(x.get("body") or ""))
        if not text:continue
        out.append({
            "evidence_id":"se:"+qid,
            "source_ref":x.get("link") or "se:"+qid,
            "source_group":"se_user:"+uid,
            "text":text[:5000],
            "meta":{"score":x.get("score"),"answer_count":x.get("answer_count"),"site":_stack_site(query)},
        })
    return out

def search_github(query: str, limit: int=10) -> List[dict]:
    q=_compact_query(query,6)
    params={"q":q,"sort":"stars","order":"desc","per_page":limit}
    headers={"Accept":"application/vnd.github+json"}
    tok=os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    if tok: headers["Authorization"]="Bearer "+tok
    d=_http_json("https://api.github.com/search/repositories?"+urllib.parse.urlencode(params),headers=headers)
    out=[]
    for x in d.get("items") or []:
        full=str(x.get("full_name") or "")
        desc=str(x.get("description") or "")
        text=(full+" "+desc+" "+" ".join(x.get("topics") or [])).strip()
        out.append({
            "evidence_id":"gh:"+str(x.get("id") or full),
            "source_ref":x.get("html_url") or ("https://github.com/"+full),
            "source_group":"github_repo:"+full.lower(),
            "text":text[:5000],
            "meta":{
                "full_name":full,
                "stars":int(x.get("stargazers_count") or 0),
                "forks":int(x.get("forks_count") or 0),
                "archived":bool(x.get("archived")),
            },
        })
    return out

def default_fetch(adapter: str, query: str, limit: int=10) -> List[dict]:
    if adapter=="hackernews_search": return search_hn(query,limit)
    if adapter=="stackexchange": return search_stackexchange(query,limit)
    if adapter=="github_search": return search_github(query,limit)
    raise ValueError("UNKNOWN_U15_ADAPTER "+adapter)

def _gap_adapters(gap: str, attempt: int) -> List[str]:
    if gap==GapType.INDEPENDENT_NEED_RECURRENCE.value:
        return ["hackernews_search","stackexchange"][attempt % 2:] + ["hackernews_search","stackexchange"][:attempt % 2]
    if gap==GapType.CURRENT_SOLUTION_SUPPLY.value:
        return ["github_search"]
    if gap==GapType.PEER_ADOPTION_OR_DIFFUSION.value:
        return ["github_search","hackernews_search"]
    return ["hackernews_search","stackexchange"]

def _strict_overlap(query: str, text: str) -> int:
    q=set(_tokens(query))
    t=set(_tokens(text))
    return len(q & t)

class BoundedVerifier:
    def __init__(self, max_calls: int=2):
        self.max_calls=max_calls
        self.calls=0
        self.enabled=bool(os.getenv("OPENAI_API_KEY")) and os.getenv("SIGNALFORGE_U15_ENABLE_LLM_VERIFY","1")!="0"
        self.model=os.getenv("SIGNALFORGE_U15_VERIFY_MODEL","gpt-5-mini")

    def verify_recurrence(self, query: str, candidates: List[dict]) -> Dict[str,dict]:
        if not self.enabled or self.calls>=self.max_calls or not candidates:
            return {}
        self.calls+=1
        try:
            from openai import OpenAI
            client=OpenAI()
            items=[{
                "evidence_id":c["evidence_id"],
                "source_group":c["source_group"],
                "text":c["text"][:1800],
            } for c in candidates[:10]]
            prompt=(
                "You are a strict evidence verifier for an opportunity-research system. "
                "Gap: INDEPENDENT_NEED_RECURRENCE. Query/problem frame: "+query+"\n"
                "For each item, return JSON only as {\"items\":[...]}. Each item must contain "
                "evidence_id, judgment, rationale. judgment must be one of "
                "CONFIRMED_SUPPORT, RELATED_BUT_NOT_EVIDENCE, INSUFFICIENT. "
                "CONFIRMED_SUPPORT requires an independent firsthand or clearly user-reported instance "
                "of materially the same workflow pain/constraint. Product announcements, vendor promotion, "
                "generic opinion, solution existence, jobs, copied reports, and merely adjacent topics are NOT recurrence. "
                "Do not infer WTP or market size. Items:\n"+json.dumps(items,ensure_ascii=False)
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
                eid=str(x.get("evidence_id") or "")
                j=str(x.get("judgment") or "")
                if j not in {"CONFIRMED_SUPPORT","RELATED_BUT_NOT_EVIDENCE","INSUFFICIENT"}:continue
                out[eid]={"judgment":j,"rationale":str(x.get("rationale") or "")[:500]}
            return out
        except Exception as e:
            return {"__verifier_error__":{"judgment":"ERROR","rationale":f"{type(e).__name__}: {e}"[:500]}}

def _deterministic_supply_judgment(query: str, c: dict) -> Tuple[str,str]:
    if not c["evidence_id"].startswith("gh:"):
        return "RETRIEVED_CANDIDATE","non-GitHub candidate remains unverified"
    overlap=_strict_overlap(query,c.get("text") or "")
    if overlap>=2 and not (c.get("meta") or {}).get("archived"):
        return "CONFIRMED_SUPPORT",f"relevant live repository confirms current solution supply; token_overlap={overlap}"
    return "RELATED_BUT_NOT_EVIDENCE",f"repository relevance insufficient; token_overlap={overlap}"

def _eligible(store: Store, thesis_id: str, run_counts: Dict[str,int], max_per_gap: int=3) -> List[Tuple[float,object]]:
    rec=store.gap(thesis_id,GapType.INDEPENDENT_NEED_RECURRENCE.value)
    sup=store.gap(thesis_id,GapType.CURRENT_SOLUTION_SUPPLY.value)
    out=[]
    for gt in GapType:
        g=store.gap(thesis_id,gt.value)
        if run_counts.get(g.gap_id,0)>=max_per_gap:continue
        # WTP is downstream: do not spend on it while recurrence/supply are still both unconfirmed.
        if gt==GapType.PAYMENT_BEHAVIOR and not (rec.confirmed>=1 and sup.confirmed>=1):
            continue
        v=store.mvoi(g,0.08)
        if v>0: out.append((v,g))
    out.sort(key=lambda x:x[0],reverse=True)
    return out

class FounderDirectedExecutor:
    def __init__(self, fetch_fn: Optional[Callable]=None, verifier: Optional[BoundedVerifier]=None):
        self.fetch_fn=fetch_fn or default_fetch
        self.verifier=verifier or BoundedVerifier()

    def execute(self, store: Store, founder_requests: int=DEFAULT_FOUNDER_REQUESTS) -> dict:
        state=_load_state()
        run_counts={}
        request_rows=[]
        cards=list(store.card_map.keys())
        if not cards:
            return {"status":"NO_FOUNDER_THESIS","requests":[],"founder_requests":0}

        for _ in range(founder_requests):
            best=None
            for card_id in cards:
                tid=store.card_map[card_id]
                eligible=_eligible(store,tid,run_counts)
                if eligible and (best is None or eligible[0][0]>best[0]):
                    best=(eligible[0][0],card_id,tid,eligible[0][1])
            if best is None: break
            _,card_id,tid,g=best
            attempt=g.attempts
            base=g.last_query or card_id
            query=query_variant(base,g.gap_type,attempt)
            adapters=_gap_adapters(g.gap_type,attempt)
            adapter=adapters[0]

            req_id="u15req_"+str(int(time.time()*1000))+"_"+str(len(request_rows))
            started=time.time()
            error=None
            try:
                candidates=self.fetch_fn(adapter,query,10)
            except Exception as e:
                candidates=[];error=f"{type(e).__name__}: {e}"

            # request owns exact candidate IDs; no global-batch credit is allowed.
            candidate_ids=[str(c.get("evidence_id")) for c in candidates]
            g.attempts+=1
            g.last_query=query
            g.last_adapter=adapter
            g.last_surface={"hackernews_search":"community","stackexchange":"community_qna","github_search":"github_repositories"}.get(adapter,adapter)
            g.retrieved_candidates+=len(candidates)

            judgments={}
            confirmed_groups=[]
            if g.gap_type==GapType.CURRENT_SOLUTION_SUPPLY.value:
                for c in candidates:
                    j,reason=_deterministic_supply_judgment(query,c)
                    judgments[c["evidence_id"]]={"judgment":j,"rationale":reason}
            elif g.gap_type==GapType.INDEPENDENT_NEED_RECURRENCE.value:
                judgments=self.verifier.verify_recurrence(query,candidates)
            # diffusion/payment remain candidates until a stricter verifier exists.

            confirmed_this_request=0
            for c in candidates:
                j=(judgments.get(c["evidence_id"]) or {}).get("judgment","RETRIEVED_CANDIDATE")
                if j=="CONFIRMED_SUPPORT":
                    g.adjudicated+=1
                    if c["source_group"] in g.confirmed_support_groups:
                        g.dependent_duplicates+=1
                        judgments[c["evidence_id"]]["judgment"]="DEPENDENT_DUPLICATE"
                    else:
                        g.confirmed_support_groups.append(c["source_group"])
                        confirmed_groups.append(c["source_group"])
                        confirmed_this_request+=1
                elif j in {"RELATED_BUT_NOT_EVIDENCE","INSUFFICIENT"}:
                    g.adjudicated+=1
                    g.related_or_insufficient+=1

            if confirmed_this_request:
                g.zero_confirmed_yield_streak=0
                g.state="ACTIVE"
            else:
                g.zero_confirmed_yield_streak+=1
                post=store.mvoi(g,0.08)
                if post<=0:g.state="STOP_LOW_MARGINAL_VALUE"
                elif g.zero_confirmed_yield_streak>=2:g.state="SWITCH_QUERY_OR_SOURCE"
                else:g.state="ACTIVE"

            store._persist()
            run_counts[g.gap_id]=run_counts.get(g.gap_id,0)+1
            row={
                "request_id":req_id,
                "card_id":card_id,
                "thesis_id":tid,
                "gap_id":g.gap_id,
                "gap":g.gap_type,
                "query":query,
                "adapter":adapter,
                "surface":g.last_surface,
                "started_at":started,
                "seconds":round(time.time()-started,3),
                "error":error,
                "candidate_ids":candidate_ids,
                "candidate_count":len(candidate_ids),
                "judgments":judgments,
                "confirmed_source_groups":confirmed_groups,
                "confirmed_count":confirmed_this_request,
                "marginal_voi_after":store.mvoi(g,0.08),
            }
            request_rows.append(row)
            state["requests"].append(row)
            state["query_history"].append({"gap_id":g.gap_id,"query":query,"adapter":adapter,"at":started})
            state["founder_requests_total"]+=1
            _atomic_json(STATE,state)

        return {
            "status":"PASS",
            "requests":request_rows,
            "founder_requests":len(request_rows),
            "verifier_calls":self.verifier.calls,
            "cards":[store.card_progress(cid,0.08) for cid in store.card_map],
        }

def cycle_accounting(exploration_refreshed: bool, founder_requests: int) -> dict:
    state=_load_state()
    state["cycle"]+=1
    if exploration_refreshed:
        state["exploration_requests_total"]+=U13_EXPLORATION_REQUESTS_PER_REFRESH
    # founder requests were already incremented by executor
    _atomic_json(STATE,state)
    f=state["founder_requests_total"];e=state["exploration_requests_total"]
    total=f+e
    return {
        "cycle":state["cycle"],
        "founder_requests_total":f,
        "exploration_requests_total":e,
        "founder_share":round(f/total,4) if total else None,
        "exploration_share":round(e/total,4) if total else None,
        "next_periodic_exploration_due":((state["cycle"]+1)%EXPLORATION_REFRESH_EVERY==0),
    }

def exploration_due() -> bool:
    s=_load_state()
    # cycles 4,8,12... perform one U13 exploration refresh.
    return ((s["cycle"]+1) % EXPLORATION_REFRESH_EVERY)==0
