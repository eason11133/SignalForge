from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import processors.discovery_coverage_u19 as u19

ENGINE_VERSION="signalforge-discovery-family-rebase-u20-v1"
STATE=Path(".radar_runtime/discovery_family_catalog_u20.json")
POLICY=Path(".radar_runtime/exploration_coverage_policy_u20.json")
TRUTH_BOUNDARY=(
    "DISCOVERY_FAMILY_FORMATION_IS_A RETRIEVAL/COVERAGE INSTRUMENT, NOT MARKET TRUTH; "
    "STRUCTURED_SIGNATURES, NATURAL_TEXT, AND MULTILINGUAL TEXT ARE HANDLED SEPARATELY; "
    "COVERAGE MAY CONTROL EXPLORATION ONLY AFTER FAMILY-QUALITY GATES AND HISTORICAL CALIBRATION PASS; "
    "NO DEMAND_WTP_OPPORTUNITY_OR_BUILD_CLAIM IS CREATED; PRODUCT_IDEATION=0"
)

STOP=set("""
the a an and or to of in on for from with without by is are was were be been being this that these those
it its as at into than then if but not no yes do does did doing can could would should may might will
research current solution supply independent need recurrence peer adoption diffusion payment behavior
evidence gap user users use using used tool tools app apps software system systems local llm llms
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

def _camel_space(s:str)->str:
    s=re.sub(r"([a-z0-9])([A-Z])",r"\1 \2",s)
    s=re.sub(r"([A-Z]+)([A-Z][a-z])",r"\1 \2",s)
    return s

def normalize_basis(text:str)->dict:
    raw=unicodedata.normalize("NFKC",str(text or "")).strip()
    if not raw:return {"eligible":False,"reason":"EMPTY","features":[],"normalized":""}

    # reject hashes/opaque IDs
    compact=re.sub(r"\s+","",raw)
    if re.fullmatch(r"[a-fA-F0-9]{20,}",compact):
        return {"eligible":False,"reason":"OPAQUE_ID","features":[],"normalized":raw}
    # Reject long token-like IDs only when they look high-entropy/digit-heavy.
    # Long structured semantic labels such as PRIVACY_CONSTRAINED_WORKFLOW are valid.
    if re.fullmatch(r"[A-Za-z0-9]{28,}",compact):
        digits=sum(ch.isdigit() for ch in compact)
        transitions=sum(1 for i in range(1,len(compact)) if compact[i].isdigit()!=compact[i-1].isdigit())
        if digits/max(len(compact),1)>=0.20 or transitions>=6:
            return {"eligible":False,"reason":"OPAQUE_ID","features":[],"normalized":raw}

    structured=bool(re.search(r"[_/\-]",raw)) or bool(re.search(r"[a-z0-9][A-Z]",raw))
    s=_camel_space(raw)
    s=re.sub(r"[_/\-]+"," ",s)
    s=re.sub(r"[^\w\u3400-\u4dbf\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]+"," ",s,flags=re.UNICODE)
    s=re.sub(r"\s+"," ",s).strip().lower()

    latin=[x for x in re.findall(r"[a-z0-9][a-z0-9+]{1,}",s) if x not in STOP]
    cjk_runs=re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]{2,}",s)
    cjk=[]
    for run in cjk_runs:
        if len(run)<=4:
            cjk.append(run)
        else:
            cjk.extend(run[i:i+2] for i in range(len(run)-1))
    feats=[]
    for x in latin+cjk:
        if x not in feats:feats.append(x)

    # A structured canonical label is allowed to be one semantic unit.
    if not feats:
        return {"eligible":False,"reason":"NO_SEMANTIC_FEATURES","features":[],"normalized":s}
    if len(feats)==1 and not structured and len(raw)<8:
        return {"eligible":False,"reason":"TOO_SHORT_UNSTRUCTURED","features":feats,"normalized":s}
    return {
        "eligible":True,"reason":"OK","features":feats[:48],"normalized":s,
        "structured":structured,"feature_count":len(feats)
    }

def _simhash(features:List[str])->int:
    if not features:return 0
    grams=list(features)
    grams += [features[i]+"_"+features[i+1] for i in range(len(features)-1)]
    v=[0]*64
    for token in grams:
        h=int.from_bytes(hashlib.blake2b(token.encode("utf-8"),digest_size=8).digest(),"big")
        for i in range(64):v[i]+=1 if (h>>i)&1 else -1
    out=0
    for i,x in enumerate(v):
        if x>=0:out|=1<<i
    return out

def _ham(a:int,b:int)->int:return (a^b).bit_count()

def form_families(records:List[dict])->Tuple[List[dict],dict]:
    accepted=[];reasons=Counter();methods=Counter();examples=defaultdict(list)
    buckets=defaultdict(list);centroids={};next_id=0
    family_counts=Counter()

    for r in records:
        norm=normalize_basis(r.get("basis",""))
        if not norm["eligible"]:
            reasons[norm["reason"]]+=1
            continue
        feats=norm["features"]
        score=int(r.get("basis_score") or 0)

        # Canonical/signature fields should remain exact semantic families if reasonably concise.
        if score>=9 and (norm.get("structured") or len(feats)<=10):
            key=" ".join(feats)
            fid="sig_"+hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
            method="canonical_signature"
        else:
            sh=_simhash(feats)
            keys=[(sh>>(16*i))&0xffff for i in range(4)]
            candidates=set()
            for i,k in enumerate(keys):candidates.update(buckets[(i,k)])
            best=None;bestd=65
            for c in candidates:
                d=_ham(sh,centroids[c])
                if d<bestd and d<=10:
                    best=c;bestd=d
            if best is None:
                fid=f"sem_{next_id:07d}";next_id+=1;centroids[fid]=sh
                for i,k in enumerate(keys):buckets[(i,k)].append(fid)
            else:
                fid=best
            method="multilingual_simhash_proxy"

        rr=dict(r)
        rr["family_id"]=fid
        rr["family_method"]=method
        rr["family_features"]=feats
        rr["basis_normalized"]=norm["normalized"]
        accepted.append(rr)
        methods[method]+=1
        family_counts[fid]+=1
        if len(examples[fid])<2:examples[fid].append(str(r.get("basis",""))[:240])

    total=len(records)
    yield_rate=len(accepted)/total if total else 0
    fam_n=len(family_counts)
    singleton=sum(1 for v in family_counts.values() if v==1)
    largest=max(family_counts.values()) if family_counts else 0
    singleton_ratio=singleton/max(fam_n,1)
    largest_share=largest/max(len(accepted),1)

    if len(accepted)<300:
        quality="INSUFFICIENT_FAMILY_RECORDS"
    elif yield_rate<0.30:
        quality="LOW_FAMILY_YIELD"
    elif fam_n<5:
        quality="OVERMERGED"
    elif largest_share>0.45:
        quality="OVERMERGED"
    elif fam_n>=50 and singleton_ratio>0.92:
        quality="OVERFRAGMENTED"
    else:
        quality="PASS"

    diag={
        "status":quality,
        "input_records":total,
        "family_records":len(accepted),
        "family_record_yield":round(yield_rate,6),
        "families":fam_n,
        "singletons":singleton,
        "singleton_family_ratio":round(singleton_ratio,6),
        "largest_family_records":largest,
        "largest_family_share":round(largest_share,6),
        "rejection_reasons":dict(reasons),
        "methods":dict(methods),
        "top_families":[
            {"family_id":fid,"records":n,"examples":examples.get(fid,[])}
            for fid,n in family_counts.most_common(15)
        ],
    }
    return accepted,diag

def _ordered(raw:List[dict],timestamp_yield:float)->Tuple[List[dict],str]:
    rows=list(raw)
    if timestamp_yield>=0.60:
        rows.sort(key=lambda x:(x["timestamp"] if x.get("timestamp") is not None else float("inf"),x.get("row_index",0)))
        return rows,"TIMESTAMP"
    rows.sort(key=lambda x:x.get("row_index",0))
    return rows,"SQLITE_ROW_ORDER_PROXY"

def stability_probe(records:List[dict])->dict:
    if len(records)<300:return {"status":"INSUFFICIENT_RECORDS"}
    # Formation must be deterministic for canonical labels; for semantic proxy, use same data and verify family fingerprint repeatability.
    a,da=form_families(records[:min(len(records),2000)])
    b,db=form_families(records[:min(len(records),2000)])
    fa=[x["family_id"] for x in a]
    fb=[x["family_id"] for x in b]
    same=(fa==fb)
    return {
        "status":"PASS" if same else "FAIL",
        "records_tested":len(fa),
        "deterministic_repeatability":same,
        "families_first":da.get("families"),
        "families_second":db.get("families"),
    }

def calibration_gate(family_diag:dict,bt:dict,stability:dict)->dict:
    formation_ok=family_diag.get("status")=="PASS"
    stable=stability.get("status")=="PASS"
    calibration=bt.get("calibration")
    directional=calibration=="DIRECTIONALLY_SUPPORTED"
    eligible=formation_ok and stable and directional
    blockers=[]
    if not formation_ok:blockers.append("FAMILY_FORMATION_"+str(family_diag.get("status")))
    if not stable:blockers.append("FAMILY_STABILITY_FAIL")
    if not directional:blockers.append("HISTORICAL_CALIBRATION_"+str(calibration))
    return {
        "eligible_for_exploration_budget_control":eligible,
        "blockers":blockers,
        "family_formation_gate":formation_ok,
        "family_stability_gate":stable,
        "historical_calibration_gate":directional,
        "calibration":calibration,
        "truth_boundary":TRUTH_BOUNDARY,
    }

def analyze(root:Path=Path("."),limit:int=15000)->dict:
    loc=u19.locate_observation_table(root)
    if loc.get("status")!="FOUND":
        return {"engine_version":ENGINE_VERSION,"status":"NO_OBSERVATION_SQLITE","locator":loc,"truth_boundary":TRUTH_BOUNDARY}

    raw,extract=u19.read_records(loc["selected"],limit)
    raw,ordering=_ordered(raw,extract.get("timestamp_yield",0))
    families,diag=form_families(raw)

    base={
        "engine_version":ENGINE_VERSION,
        "locator":{"selected":loc.get("selected"),"alternatives":loc.get("candidates",[None])[1:5]},
        "extraction_quality":extract,
        "ordering":ordering,
        "family_formation":diag,
        "truth_boundary":TRUTH_BOUNDARY,
    }
    if diag["status"]!="PASS":
        base["status"]=diag["status"]
        _atomic(root/STATE,base)
        return base

    stability=stability_probe(raw)
    global_cov=u19.coverage_metrics(families)
    bt=u19.backtest(families)
    source_cov=u19.source_metrics(families)
    gate=calibration_gate(diag,bt,stability)

    # Use U19 policy wording only if all gates pass; otherwise diagnostic-only.
    policy={
        "action":"DIAGNOSTIC_ONLY_DO_NOT_CONTROL_BUDGET",
        "eligible_for_exploration_budget_control":False,
        "source_priority":[],
        "truth_boundary":TRUTH_BOUNDARY,
    }
    if gate["eligible_for_exploration_budget_control"]:
        p=u19.decision(global_cov,bt,source_cov)
        policy.update(p)
        policy["eligible_for_exploration_budget_control"]=True
    else:
        policy["blockers"]=gate["blockers"]
        policy["source_priority"]=[
            {"source":x.get("source"),"records":x.get("records"),
             "unseen_mass_proxy":(x.get("coverage") or {}).get("good_turing_unseen_mass_proxy"),
             "calibration":(x.get("backtest") or {}).get("calibration")}
            for x in source_cov[:8]
        ]

    result={**base,
        "status":"PASS",
        "family_stability":stability,
        "global_coverage":global_cov,
        "historical_backtest":bt,
        "source_coverage":source_cov,
        "calibration_gate":gate,
        "exploration_policy":policy,
    }
    _atomic(root/STATE,result)
    _atomic(root/POLICY,policy)
    return result
