from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import time
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

import processors.discovery_coverage_u19 as u19
import processors.discovery_family_rebase_u20 as u20

ENGINE_VERSION="signalforge-semantic-basis-contract-u21-v1"
STATE=Path(".radar_runtime/semantic_basis_contract_u21.json")
POLICY=Path(".radar_runtime/exploration_coverage_policy_u21.json")

TRUTH_BOUNDARY=(
    "SEMANTIC_BASIS_SELECTION_SEPARATES OBSERVATION CONTENT FROM SCHEMA_VERSION_SOURCE_AND_OTHER METADATA; "
    "FAMILY_AND_COVERAGE ANALYSIS MAY RUN ONLY AFTER BASIS_QUALITY AND FAMILY_QUALITY PASS; "
    "COVERAGE REMAINS A DISCOVERY_DIAGNOSTIC UNDER THE OBSERVED COLLECTION POLICY, NOT MARKET TRUTH; "
    "NO DEMAND_WTP_OPPORTUNITY_OR_BUILD CLAIM IS CREATED; PRODUCT_IDEATION=0"
)

# Exact terminal keys / path fragments that denote content-bearing fields.
EXPLICIT_SIGNATURE_TERMINALS={
    "problem_signature","need_signature","pain_signature","friction_signature",
    "primary_problem_signature","canonical_problem_signature","issue_signature",
}
STRONG_TEXT_TERMINALS={
    "problem_statement","need_statement","pain_statement","friction_statement",
    "problem_text","need_text","pain_text","friction_text","complaint_text",
    "canonical_problem","canonical_need","observed_problem","observed_need",
    "problem_summary","need_summary","pain_summary","friction_summary",
}
FRAME_CONTENT_TERMINALS={
    "problem","need","pain","friction","complaint","summary","text","statement",
    "description","issue","constraint","workflow_problem",
}
FALLBACK_TERMINALS={"title","summary","text","body","content","description"}

NEGATIVE_TERMINALS={
    "version","schema_version","format_version","parser_version","frame_version",
    "type","source_type","source_name","adapter","adapter_name","platform",
    "package","package_name","module","role","status","state","kind",
    "id","key","doc_key","cache_key","hash","url","link","uri",
    "created_at","updated_at","published_at","timestamp","date","time",
    "language","locale","parser","schema","format","provider",
}
NEGATIVE_PATH_PARTS={
    "metadata","meta","provenance","cache","parser","schema","telemetry",
    "source_portfolio","runtime","debug","audit","trace",
}
METADATA_VALUE_LITERALS={
    "source_type","source_name","package_name","need-frame-v1","problem-frame-v1",
    "need_frame_v1","problem_frame_v1","metadata","unknown","none","null",
}

SEMANTIC_STOP=set("""
the a an and or to of in on for from with without by is are was were be been being this that these those
it its as at into than then if but not no yes do does did doing can could would should may might will
research evidence source type package name version schema status role
""".split())

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

def _maybe_json(v):
    if isinstance(v,(bytes,bytearray)):
        try:v=v.decode("utf-8","replace")
        except Exception:return None
    if not isinstance(v,str):return None
    s=v.strip()
    if len(s)<2 or s[0] not in "[{":return None
    try:return json.loads(s)
    except Exception:return None

def _flatten(obj,prefix="",depth=0,out=None):
    if out is None:out=[]
    if depth>7:return out
    if isinstance(obj,dict):
        for k,v in obj.items():
            key=(prefix+"."+str(k)).strip(".")
            if isinstance(v,(dict,list)):_flatten(v,key,depth+1,out)
            elif isinstance(v,(str,int,float,bool)) or v is None:out.append((key,v))
    elif isinstance(obj,list):
        for i,v in enumerate(obj[:40]):_flatten(v,prefix+f"[{i}]",depth+1,out)
    return out

def _terminal(path:str)->str:
    p=re.sub(r"\[\d+\]","",path)
    return p.split(".")[-1].strip().lower()

def _parts(path:str)->List[str]:
    p=re.sub(r"\[\d+\]","",path.lower())
    return [x for x in p.split(".") if x]

def _norm_value(v)->str:
    return unicodedata.normalize("NFKC",str(v if v is not None else "")).strip()

def _looks_version_marker(s:str)->bool:
    x=s.strip().lower()
    if re.fullmatch(r"v\d+(?:\.\d+){0,3}",x):return True
    if re.fullmatch(r"[a-z][a-z0-9_-]{1,50}[-_]v\d+(?:\.\d+){0,3}",x):return True
    if re.fullmatch(r"(?:need|problem|pain|friction)[-_ ]frame[-_ ]?v\d+",x):return True
    return False

def _looks_opaque(s:str)->bool:
    x=re.sub(r"\s+","",s)
    if re.fullmatch(r"[a-fA-F0-9]{20,}",x):return True
    if re.fullmatch(r"[A-Za-z0-9]{28,}",x):
        digits=sum(ch.isdigit() for ch in x)
        trans=sum(1 for i in range(1,len(x)) if x[i].isdigit()!=x[i-1].isdigit())
        return digits/max(len(x),1)>=0.20 or trans>=6
    return False

def _semantic_units(s:str)->List[str]:
    x=unicodedata.normalize("NFKC",s).strip()
    x=re.sub(r"([a-z0-9])([A-Z])",r"\1 \2",x)
    x=re.sub(r"[_/\-]+"," ",x)
    latin=[t for t in re.findall(r"[a-z0-9][a-z0-9+]{1,}",x.lower()) if t not in SEMANTIC_STOP]
    cjk_runs=re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]{2,}",x)
    cjk=[]
    for run in cjk_runs:
        if len(run)<=4:cjk.append(run)
        else:cjk.extend(run[i:i+2] for i in range(len(run)-1))
    out=[]
    for t in latin+cjk:
        if t not in out:out.append(t)
    return out

def _path_class(path:str)->Tuple[str,int]:
    term=_terminal(path);parts=set(_parts(path))
    if term in NEGATIVE_TERMINALS or parts & NEGATIVE_PATH_PARTS:
        return "NEGATIVE_METADATA",-100
    if term in EXPLICIT_SIGNATURE_TERMINALS:
        return "EXPLICIT_SIGNATURE",100
    if term in STRONG_TEXT_TERMINALS:
        return "STRONG_TEXT",90
    # A generic "problem"/"summary"/"text" is strong only inside a semantically named frame/object.
    semantic_parent=any(
        any(tok in p for tok in ("problem","need","pain","friction","complaint","constraint","workflow"))
        for p in _parts(path)[:-1]
    )
    if term in FRAME_CONTENT_TERMINALS and semantic_parent:
        return "FRAME_CONTENT",82
    if term in FALLBACK_TERMINALS:
        return "FALLBACK_TEXT",45
    return "UNCLASSIFIED",0

def classify_leaf(path:str,val)->dict:
    cls,base=_path_class(path)
    s=_norm_value(val)
    term=_terminal(path)
    if cls=="NEGATIVE_METADATA":
        return {"eligible":False,"reason":"NEGATIVE_METADATA_PATH","path_class":cls,"score":-100}
    if not s:
        return {"eligible":False,"reason":"EMPTY","path_class":cls,"score":-100}
    if len(s)>12000:
        return {"eligible":False,"reason":"TOO_LONG","path_class":cls,"score":-100}
    low=s.lower().strip()
    if low in METADATA_VALUE_LITERALS:
        return {"eligible":False,"reason":"METADATA_LITERAL","path_class":cls,"score":-100}
    if _looks_version_marker(s):
        return {"eligible":False,"reason":"VERSION_MARKER","path_class":cls,"score":-100}
    if _looks_opaque(s):
        return {"eligible":False,"reason":"OPAQUE_ID","path_class":cls,"score":-100}
    # Values that simply echo a field name are placeholders, not semantics.
    normalized_echo=re.sub(r"[\s\-]+","_",low)
    if normalized_echo==term or normalized_echo in NEGATIVE_TERMINALS:
        return {"eligible":False,"reason":"FIELD_NAME_PLACEHOLDER","path_class":cls,"score":-100}
    if cls=="UNCLASSIFIED":
        return {"eligible":False,"reason":"UNCLASSIFIED_PATH","path_class":cls,"score":0}

    units=_semantic_units(s)
    structured=bool(re.search(r"[_/\-]",s)) or bool(re.search(r"[a-z0-9][A-Z]",s))
    if not units:
        return {"eligible":False,"reason":"NO_SEMANTIC_UNITS","path_class":cls,"score":-100}
    if len(units)==1 and cls!="EXPLICIT_SIGNATURE" and not structured and len(s)<8:
        return {"eligible":False,"reason":"TOO_SHORT_UNSTRUCTURED","path_class":cls,"score":-100}

    score=base
    score+=min(12,len(units)*2)
    if 12<=len(s)<=500:score+=6
    if cls=="EXPLICIT_SIGNATURE" and structured:score+=5
    # Penalize suspiciously generic values even when they occur on fallback fields.
    if low in {"productivity","compliance","coordination","javascript","linkedin","deepseek","openrouter"}:
        score-=18
    return {
        "eligible":True,"reason":"OK","path_class":cls,"score":score,
        "units":units[:48],"structured":structured,"value":s,
    }

def choose_basis(flat:List[Tuple[str,object]])->Tuple[Optional[dict],Counter]:
    rejects=Counter();cands=[]
    for path,val in flat:
        c=classify_leaf(path,val)
        if not c["eligible"]:
            rejects[c["reason"]]+=1
            continue
        c=dict(c);c["path"]=path
        cands.append(c)
    if not cands:return None,rejects
    cands.sort(key=lambda x:(x["score"],len(x.get("units") or []),-len(x["value"])),reverse=True)
    return cands[0],rejects

def _parse_time(v)->Optional[float]:
    if v is None:return None
    if isinstance(v,(int,float)):
        x=float(v)
        if x>1e12:x/=1000
        if 946684800<=x<=4102444800:return x
        return None
    s=str(v).strip()
    try:
        if re.fullmatch(r"\d+(?:\.\d+)?",s):return _parse_time(float(s))
        return datetime.fromisoformat(s.replace("Z","+00:00")).timestamp()
    except Exception:return None

def _domain(url:str)->Optional[str]:
    try:
        d=urlparse(url).netloc.lower()
        if d.startswith("www."):d=d[4:]
        return d or None
    except Exception:return None

def _extract_source_time(flat:List[Tuple[str,object]])->Tuple[str,Optional[float]]:
    source=None;ts=None
    # Source extraction intentionally uses metadata, but never as semantic basis.
    for path,val in flat:
        if val is None:continue
        term=_terminal(path);s=str(val).strip()
        if term in {"adapter","adapter_name","platform","source_name","source_type"} and 1<=len(s)<=100:
            source=s.lower();break
    if not source:
        for path,val in flat:
            if val is None:continue
            if _terminal(path) in {"url","link","uri"}:
                d=_domain(str(val))
                if d:source=d;break
    for path,val in flat:
        term=_terminal(path)
        if term in {"created_at","updated_at","published_at","observed_at","timestamp","date","time"}:
            ts=_parse_time(val)
            if ts is not None:break
    return source or "unknown",ts

def read_semantic_records(selection:dict,limit:int=15000)->Tuple[List[dict],dict]:
    con=sqlite3.connect(selection["path"]);con.row_factory=sqlite3.Row
    rows=con.execute(f'SELECT * FROM "{selection["table"]}" LIMIT ?', (limit,)).fetchall()
    con.close()
    out=[];rejects=Counter();pathdist=Counter();classdist=Counter();values=Counter();fallback=0
    for i,row in enumerate(rows):
        d=dict(row);objects=[d]
        for v in d.values():
            j=_maybe_json(v)
            if j is not None:objects.append(j)
        flat=[]
        for o in objects:flat.extend(_flatten(o))
        chosen,rj=choose_basis(flat);rejects.update(rj)
        if chosen is None:continue
        source,ts=_extract_source_time(flat)
        pathdist[chosen["path"]]+=1;classdist[chosen["path_class"]]+=1;values[chosen["value"]]+=1
        if chosen["path_class"]=="FALLBACK_TEXT":fallback+=1
        out.append({
            "row_index":i,"basis":chosen["value"],"basis_path":chosen["path"],
            "basis_class":chosen["path_class"],"basis_score":chosen["score"],
            "source":source,"timestamp":ts,
        })
    n=len(rows);m=len(out)
    topval=values.most_common(15)
    dominant_share=(topval[0][1]/m) if m and topval else 0.0
    top_path=pathdist.most_common(15)
    quality={
        "rows_read":n,"semantic_records":m,"semantic_yield":round(m/n,6) if n else 0.0,
        "timestamp_yield":round(sum(1 for x in out if x["timestamp"] is not None)/m,6) if m else 0.0,
        "selected_path_distribution":top_path,
        "selected_class_distribution":dict(classdist),
        "top_selected_values":topval,
        "dominant_value_share":round(dominant_share,6),
        "fallback_rate":round(fallback/m,6) if m else 0.0,
        "rejection_reasons":dict(rejects),
    }
    # Basis quality gate: high yield but metadata domination is still a failure.
    suspicious_top = bool(topval and (
        _looks_version_marker(topval[0][0]) or topval[0][0].lower() in METADATA_VALUE_LITERALS
    ))
    if m<300:
        status="INSUFFICIENT_SEMANTIC_RECORDS"
    elif m/n<0.25:
        status="LOW_SEMANTIC_YIELD"
    elif suspicious_top and dominant_share>0.20:
        status="METADATA_DOMINATED"
    elif dominant_share>0.65 and classdist.get("FALLBACK_TEXT",0)>m*0.50:
        status="GENERIC_FALLBACK_DOMINATED"
    else:
        status="PASS"
    quality["status"]=status
    return out,quality

def _order(rows:List[dict],timestamp_yield:float)->Tuple[List[dict],str]:
    r=list(rows)
    if timestamp_yield>=0.60:
        r.sort(key=lambda x:(x["timestamp"] if x["timestamp"] is not None else float("inf"),x["row_index"]))
        return r,"TIMESTAMP"
    r.sort(key=lambda x:x["row_index"]);return r,"SQLITE_ROW_ORDER_PROXY"

def analyze(root:Path=Path("."),limit:int=15000)->dict:
    loc=u19.locate_observation_table(root)
    if loc.get("status")!="FOUND":
        return {"engine_version":ENGINE_VERSION,"status":"NO_OBSERVATION_SQLITE","locator":loc,"truth_boundary":TRUTH_BOUNDARY}
    rows,bq=read_semantic_records(loc["selected"],limit)
    rows,ordering=_order(rows,bq.get("timestamp_yield",0))
    base={
        "engine_version":ENGINE_VERSION,
        "locator":{"selected":loc["selected"],"alternatives":loc.get("candidates",[])[1:5]},
        "basis_quality":bq,"ordering":ordering,"truth_boundary":TRUTH_BOUNDARY,
    }
    if bq["status"]!="PASS":
        base["status"]=bq["status"];_atomic(root/STATE,base);return base

    families,fd=u20.form_families(rows)
    base["family_formation"]=fd
    if fd["status"]!="PASS":
        base["status"]=fd["status"];_atomic(root/STATE,base);return base

    st=u20.stability_probe(rows)
    cov=u19.coverage_metrics(families)
    bt=u19.backtest(families)
    src=u19.source_metrics(families)
    gate=u20.calibration_gate(fd,bt,st)
    # Budget control remains strictly gated.
    if gate["eligible_for_exploration_budget_control"]:
        policy=u19.decision(cov,bt,src)
        policy["eligible_for_exploration_budget_control"]=True
    else:
        policy={
            "action":"DIAGNOSTIC_ONLY_DO_NOT_CONTROL_BUDGET",
            "eligible_for_exploration_budget_control":False,
            "blockers":gate["blockers"],
            "source_priority":[
                {"source":x.get("source"),"records":x.get("records"),
                 "unseen_mass_proxy":(x.get("coverage") or {}).get("good_turing_unseen_mass_proxy"),
                 "calibration":(x.get("backtest") or {}).get("calibration")}
                for x in src[:8]
            ],
            "truth_boundary":TRUTH_BOUNDARY,
        }
    result={**base,
        "status":"PASS","family_stability":st,"global_coverage":cov,
        "historical_backtest":bt,"source_coverage":src,
        "calibration_gate":gate,"exploration_policy":policy,
    }
    _atomic(root/STATE,result);_atomic(root/POLICY,policy)
    return result
