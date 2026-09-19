from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import statistics
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse

ENGINE_VERSION="signalforge-discovery-coverage-u19-v1"
STATE=Path(".radar_runtime/discovery_coverage_u19.json")
POLICY=Path(".radar_runtime/exploration_coverage_policy_u19.json")
TRUTH_BOUNDARY=(
    "COVERAGE_METRICS_DESCRIBE_DISCOVERY_COMPLETENESS_UNDER_THE_OBSERVED_COLLECTION_POLICY_ONLY; "
    "GOOD_TURING_AND_CHAO2_VALUES_ARE_EMPIRICALLY_CALIBRATED_PROXIES_NOT_MARKET_PROBABILITIES; "
    "COVERAGE_CANNOT_ESTABLISH_DEMAND_WTP_OPPORTUNITY_QUALITY_OR_BUILD_RECOMMENDATION; PRODUCT_IDEATION=0"
)

STOP=set("""
the a an and or to of in on for from with without by is are was were be been being this that these those
it its as at into than then if but not no yes do does did doing can could would should may might will
research current solution supply independent need recurrence peer adoption diffusion payment behavior
evidence gap user users use using used tool tools app apps software system systems local llm llms
""".split())

KEY_PRIORITY=[
    (10,("problem_signature","need_signature","pain_signature","primary_signature")),
    (9,("problem_statement","need_statement","pain_statement","friction_statement")),
    (8,("canonical_problem","canonical_need","problem_frame","need_frame")),
    (7,("problem","need","pain","friction","complaint")),
    (5,("summary","title","canonical_text","text","body","content","description")),
]
BAD_SIGNATURE_KEYS=("parser_signature","schema_signature","observation_signature","version_signature","cache_signature")

def _atomic(path:Path,payload:dict)->None:
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

def _flatten(obj,prefix="",depth=0,out=None):
    if out is None:out=[]
    if depth>5:return out
    if isinstance(obj,dict):
        for k,v in obj.items():
            key=(prefix+"."+str(k)).strip(".")
            if isinstance(v,(dict,list)):_flatten(v,key,depth+1,out)
            elif isinstance(v,(str,int,float,bool)) or v is None:out.append((key,v))
    elif isinstance(obj,list):
        for i,v in enumerate(obj[:20]):_flatten(v,prefix+f"[{i}]",depth+1,out)
    return out

def _maybe_json(v):
    if isinstance(v,(bytes,bytearray)):
        try:v=v.decode("utf-8","replace")
        except Exception:return None
    if not isinstance(v,str):return None
    s=v.strip()
    if len(s)<2 or s[0] not in "[{":return None
    try:return json.loads(s)
    except Exception:return None

def locate_observation_table(root:Path=Path("."))->dict:
    runtime=root/".radar_runtime"
    files=[]
    for pat in ("**/*.sqlite","**/*.sqlite3","**/*.db"):
        files.extend(runtime.glob(pat))
    candidates=[]
    for p in files:
        try:
            size=p.stat().st_size
            if size<100_000:continue
            con=sqlite3.connect(str(p))
            for (table,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
                cols=con.execute(f'PRAGMA table_info("{table}")').fetchall()
                if not cols:continue
                n=con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                names=[str(c[1]) for c in cols]
                types=[str(c[2] or "").upper() for c in cols]
                textish=sum(1 for t in types if any(x in t for x in ("TEXT","CHAR","CLOB","BLOB")) or not t)
                name_score=sum(3 for x in names if re.search(r"observ|payload|json|document|data|record",x,re.I))
                table_score=(math.log10(max(n,1))*5)+(math.log10(max(size,1)))+textish+name_score
                if n>=100 and textish:
                    candidates.append({"path":str(p),"table":table,"rows":n,"columns":names,"score":table_score,"bytes":size})
            con.close()
        except Exception:
            continue
    if not candidates:
        return {"status":"NOT_FOUND","candidates":[]}
    candidates.sort(key=lambda x:(x["score"],x["rows"],x["bytes"]),reverse=True)
    return {"status":"FOUND","selected":candidates[0],"candidates":candidates[:10]}

def _parse_time(v)->Optional[float]:
    if v is None:return None
    if isinstance(v,(int,float)):
        x=float(v)
        if x>1e12:x/=1000
        if 946684800<=x<=4102444800:return x
        return None
    s=str(v).strip()
    if not s:return None
    try:
        if re.fullmatch(r"\d+(?:\.\d+)?",s):return _parse_time(float(s))
        return datetime.fromisoformat(s.replace("Z","+00:00")).timestamp()
    except Exception:return None

def _domain(url:str)->Optional[str]:
    try:
        d=urlparse(url).netloc.lower()
        return d[4:] if d.startswith("www.") else (d or None)
    except Exception:return None

def extract_record(row:dict,row_index:int)->Optional[dict]:
    objects=[]
    # Preserve direct columns and recursively inspect JSON payloads.
    direct={k:v for k,v in row.items()}
    objects.append(direct)
    for v in row.values():
        j=_maybe_json(v)
        if j is not None:objects.append(j)
    flat=[]
    for o in objects:flat.extend(_flatten(o))
    if not flat:return None

    # Semantic family basis: prefer explicit need/problem signatures/frames.
    best=None
    for key,val in flat:
        if val is None:continue
        text=str(val).strip()
        if len(text)<8 or len(text)>12000:continue
        kl=key.lower()
        if any(b in kl for b in BAD_SIGNATURE_KEYS):continue
        score=0
        for pri,patterns in KEY_PRIORITY:
            if any(p in kl for p in patterns):
                score=max(score,pri)
        # URL / IDs / logs should not become semantic basis.
        if re.match(r"^https?://",text) or re.fullmatch(r"[a-f0-9_-]{16,}",text.lower()):score=0
        if score and (best is None or score>best[0] or (score==best[0] and len(text)<len(best[2]))):
            best=(score,key,text)
    if best is None:return None

    source=None
    for key,val in flat:
        if val is None:continue
        kl=key.lower();sv=str(val).strip()
        if any(x in kl for x in ("adapter","source_type","source_name","platform")) and 1<=len(sv)<=80:
            source=sv.lower();break
    if not source:
        for key,val in flat:
            if val is None:continue
            if "url" in key.lower() or "link" in key.lower():
                d=_domain(str(val))
                if d:source=d;break
    source=source or "unknown"

    ts=None
    for key,val in flat:
        kl=key.lower()
        if any(x in kl for x in ("created_at","published_at","observed_at","timestamp","date","time")):
            ts=_parse_time(val)
            if ts is not None:break

    return {
        "row_index":row_index,"basis_key":best[1],"basis_score":best[0],"basis":best[2],
        "source":source,"timestamp":ts
    }

def read_records(selection:dict,limit:int=15000)->Tuple[List[dict],dict]:
    p=Path(selection["path"]);table=selection["table"]
    con=sqlite3.connect(str(p))
    con.row_factory=sqlite3.Row
    rows=con.execute(f'SELECT * FROM "{table}" LIMIT ?', (limit,)).fetchall()
    con.close()
    out=[];scores=Counter()
    for i,r in enumerate(rows):
        x=extract_record(dict(r),i)
        if x:
            out.append(x);scores[x["basis_score"]]+=1
    ts=sum(1 for x in out if x["timestamp"] is not None)
    return out,{
        "rows_read":len(rows),"semantic_records":len(out),
        "semantic_yield":round(len(out)/len(rows),4) if rows else 0.0,
        "timestamp_yield":round(ts/len(out),4) if out else 0.0,
        "basis_score_distribution":dict(scores),
    }

def _semantic_tokens(text:str)->List[str]:
    toks=[]
    for t in re.findall(r"[a-z0-9][a-z0-9_+-]{2,}",(text or "").lower()):
        if t in STOP:continue
        if t not in toks:toks.append(t)
    return toks[:40]

def _simhash(tokens:List[str])->int:
    if not tokens:return 0
    v=[0]*64
    grams=tokens+[tokens[i]+"_"+tokens[i+1] for i in range(len(tokens)-1)]
    for token in grams:
        h=int(hashlib.blake2b(token.encode(),digest_size=8).hexdigest(),16)
        for i in range(64):v[i]+=1 if (h>>i)&1 else -1
    out=0
    for i,x in enumerate(v):
        if x>=0:out|=1<<i
    return out

def _ham(a:int,b:int)->int:return (a^b).bit_count()

def assign_families(records:List[dict])->Tuple[List[dict],dict]:
    # High-quality explicit signatures are exact-normalized; free text uses conservative SimHash near-duplicate clustering.
    buckets=defaultdict(list);centroids={};family_meta={};next_id=0
    for r in records:
        toks=_semantic_tokens(r["basis"])
        if len(toks)<2:continue
        if r["basis_score"]>=9:
            norm=" ".join(toks[:16])
            fid="sig_"+hashlib.sha1(norm.encode()).hexdigest()[:14]
            method="explicit_signature"
        else:
            sh=_simhash(toks)
            keys=[(sh>>(16*i))&0xffff for i in range(4)]
            choices=set()
            for i,k in enumerate(keys):choices.update(buckets[(i,k)])
            fid=None;bestd=99
            for c in choices:
                d=_ham(sh,centroids[c])
                if d<bestd and d<=8:fid=c;bestd=d
            if fid is None:
                fid=f"sem_{next_id:06d}";next_id+=1;centroids[fid]=sh
                for i,k in enumerate(keys):buckets[(i,k)].append(fid)
            method="simhash_proxy"
        rr=dict(r);rr["family_id"]=fid;rr["family_method"]=method;rr["tokens"]=toks
        family_meta.setdefault(fid,{"method":method,"examples":[]})
        if len(family_meta[fid]["examples"])<2:family_meta[fid]["examples"].append(r["basis"][:300])
        yield_rec=rr
        # avoid generator complexity in callers
        if "_tmp" not in family_meta: family_meta["_tmp"]=[]
        family_meta["_tmp"].append(yield_rec)
    assigned=family_meta.pop("_tmp",[])
    methods=Counter(x["family_method"] for x in assigned)
    return assigned,{"families":len({x["family_id"] for x in assigned}),"methods":dict(methods),"family_examples":family_meta}

def coverage_metrics(records:List[dict],unit_size:int=100)->dict:
    n=len(records)
    if n==0:return {"status":"EMPTY"}
    counts=Counter(x["family_id"] for x in records)
    s_obs=len(counts);f1=sum(1 for v in counts.values() if v==1);f2=sum(1 for v in counts.values() if v==2)
    gt=f1/n

    # Replicated incidence units: fixed-size consecutive blocks under the observed collection policy.
    units=[records[i:i+unit_size] for i in range(0,n,unit_size) if len(records[i:i+unit_size])>=max(20,unit_size//2)]
    inc=Counter()
    for u in units:
        for f in {x["family_id"] for x in u}:inc[f]+=1
    q1=sum(1 for v in inc.values() if v==1);q2=sum(1 for v in inc.values() if v==2)
    t=len(units)
    chao2=None
    if t>=2:
        chao2=s_obs+((t-1)/t)*(q1*(q1-1)/(2*(q2+1)))
    unseen_lb=max(0.0,(chao2 or s_obs)-s_obs)
    return {
        "status":"PASS","records":n,"observed_families":s_obs,
        "singletons_f1":f1,"doubletons_f2":f2,
        "good_turing_unseen_mass_proxy":round(gt,6),
        "sample_coverage_proxy":round(1-gt,6),
        "incidence_units":t,"incidence_uniques_q1":q1,"incidence_duplicates_q2":q2,
        "chao2_lower_bound_proxy":round(chao2,3) if chao2 is not None else None,
        "unseen_family_lower_bound_proxy":round(unseen_lb,3),
        "unseen_lower_bound_ratio":round(unseen_lb/max(s_obs,1),6),
        "truth_boundary":"EMPIRICAL_PROXY_UNDER_OBSERVED_COLLECTION_POLICY_NOT_STATISTICAL_MARKET_GUARANTEE"
    }

def _corr(xs:List[float],ys:List[float])->Optional[float]:
    if len(xs)<2:return None
    mx=sum(xs)/len(xs);my=sum(ys)/len(ys)
    a=sum((x-mx)*(y-my) for x,y in zip(xs,ys))
    b=sum((x-mx)**2 for x in xs);c=sum((y-my)**2 for y in ys)
    if b<=0 or c<=0:return 0.0
    return a/math.sqrt(b*c)

def backtest(records:List[dict],horizon:int=200)->dict:
    n=len(records)
    if n<500:return {"status":"INSUFFICIENT_RECORDS","points":[]}
    points=[]
    for frac in (0.45,0.55,0.65,0.75,0.85):
        cut=int(n*frac)
        if n-cut<50:continue
        prefix=records[:cut]
        h=min(horizon,n-cut)
        future=records[cut:cut+h]
        seen={x["family_id"] for x in prefix}
        pred=coverage_metrics(prefix)["good_turing_unseen_mass_proxy"]
        actual=sum(1 for x in future if x["family_id"] not in seen)/h
        points.append({"prefix_records":cut,"horizon":h,"predicted_unseen_mass_proxy":round(pred,6),
                       "realized_new_family_record_rate":round(actual,6),"abs_error":round(abs(pred-actual),6)})
    if len(points)<3:return {"status":"INSUFFICIENT_POINTS","points":points}
    xs=[p["predicted_unseen_mass_proxy"] for p in points]
    ys=[p["realized_new_family_record_rate"] for p in points]
    mae=sum(p["abs_error"] for p in points)/len(points)
    corr=_corr(xs,ys)
    # Deliberately conservative. Directional support is enough for ranking/priority, not probability claims.
    if mae<=0.10 and (corr is not None and corr>=0.35):cal="DIRECTIONALLY_SUPPORTED"
    elif mae<=0.16:cal="WEAKLY_SUPPORTED"
    else:cal="NOT_SUPPORTED"
    return {"status":"PASS","calibration":cal,"mae":round(mae,6),"correlation":round(corr,6) if corr is not None else None,"points":points}

def source_metrics(records:List[dict])->List[dict]:
    groups=defaultdict(list)
    for x in records:groups[x["source"]].append(x)
    out=[]
    for src,rows in groups.items():
        if len(rows)<80:continue
        m=coverage_metrics(rows,unit_size=max(40,min(100,len(rows)//5)))
        bt=backtest(rows,horizon=min(100,max(50,len(rows)//5))) if len(rows)>=500 else {"status":"INSUFFICIENT_RECORDS"}
        out.append({"source":src,"records":len(rows),"coverage":m,"backtest":bt})
    out.sort(key=lambda x:(x["coverage"].get("good_turing_unseen_mass_proxy",0),x["records"]),reverse=True)
    return out

def decision(global_metrics:dict,bt:dict,sources:List[dict])->dict:
    p0=global_metrics.get("good_turing_unseen_mass_proxy",0.0)
    gap=global_metrics.get("unseen_lower_bound_ratio",0.0)
    cal=bt.get("calibration","NOT_SUPPORTED")
    calibrated=cal=="DIRECTIONALLY_SUPPORTED"
    if not calibrated:
        action="DIAGNOSTIC_ONLY_DO_NOT_CONTROL_BUDGET"
        eligible=False
    elif p0>=0.12 or gap>=0.35:
        action="EXPAND_OR_DIVERSIFY_EXPLORATION"
        eligible=True
    elif p0>=0.05 or gap>=0.15:
        action="CONTINUE_EXPLORATION_WITH_SOURCE_PRIORITIZATION"
        eligible=True
    else:
        action="REDUCE_OR_SWITCH_BROAD_EXPLORATION"
        eligible=True
    source_priority=[]
    for x in sources[:8]:
        cb=x["backtest"].get("calibration") if isinstance(x.get("backtest"),dict) else None
        source_priority.append({
            "source":x["source"],"records":x["records"],
            "unseen_mass_proxy":x["coverage"].get("good_turing_unseen_mass_proxy"),
            "unseen_lower_bound_ratio":x["coverage"].get("unseen_lower_bound_ratio"),
            "calibration":cb,
        })
    return {
        "action":action,"eligible_for_exploration_budget_control":eligible,
        "calibration_required":True,"global_calibration":cal,
        "source_priority":source_priority,
        "does_not_modify_founder_thesis_research":True,
        "truth_boundary":TRUTH_BOUNDARY
    }

def analyze(root:Path=Path("."),limit:int=15000)->dict:
    loc=locate_observation_table(root)
    if loc["status"]!="FOUND":
        return {"engine_version":ENGINE_VERSION,"status":"NO_OBSERVATION_SQLITE","locator":loc,"truth_boundary":TRUTH_BOUNDARY}
    raw,quality=read_records(loc["selected"],limit)
    if len(raw)<300 or quality["semantic_yield"]<0.20:
        return {"engine_version":ENGINE_VERSION,"status":"INSUFFICIENT_SEMANTIC_EXTRACTION",
                "locator":loc,"quality":quality,"truth_boundary":TRUTH_BOUNDARY}
    # Chronology when sufficiently available; otherwise stable DB row order.
    if quality["timestamp_yield"]>=0.60:
        raw.sort(key=lambda x:(x["timestamp"] if x["timestamp"] is not None else float("inf"),x["row_index"]))
        order="TIMESTAMP"
    else:
        raw.sort(key=lambda x:x["row_index"]);order="SQLITE_ROW_ORDER_PROXY"
    records,fam=assign_families(raw)
    if len(records)<300:
        return {"engine_version":ENGINE_VERSION,"status":"INSUFFICIENT_FAMILY_RECORDS","quality":quality,"family":fam,"truth_boundary":TRUTH_BOUNDARY}
    gm=coverage_metrics(records)
    bt=backtest(records)
    sm=source_metrics(records)
    dec=decision(gm,bt,sm)
    result={
        "engine_version":ENGINE_VERSION,"status":"PASS","generated_at":time.time(),
        "locator":{"selected":loc["selected"],"alternatives":loc["candidates"][1:5]},
        "extraction_quality":quality,"ordering":order,
        "family_model":{"records":len(records),"families":fam["families"],"methods":fam["methods"],
                        "examples":dict(list(fam["family_examples"].items())[:20])},
        "global_coverage":gm,"historical_backtest":bt,"source_coverage":sm,
        "exploration_policy":dec,"truth_boundary":TRUTH_BOUNDARY
    }
    _atomic(root/STATE,result);_atomic(root/POLICY,dec)
    return result
