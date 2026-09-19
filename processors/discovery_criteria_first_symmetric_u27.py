from __future__ import annotations
import hashlib,json,os
from collections import Counter,defaultdict
from pathlib import Path

from processors.discovery_symmetric_contracts_u27 import ENGINE_VERSION,STATE,TRUTH_BOUNDARY,ASPECTS,canonical_json
from processors.discovery_symmetric_loader_u27 import load_latest_u26,pointwise_payload,canonical_pair,baseline_instability,sha_file
from processors.discovery_symmetric_judge_u27 import SymmetricJudge
from processors.discovery_symmetric_store_u27 import save

PROTECTED_PATTERNS=("u14","u15","u16","u17","u18","founder_thesis","evidence_adjudication","thesis_conditioned")

def _protected(root):
    rt=root/".radar_runtime";out={}
    if rt.exists():
        for p in rt.iterdir():
            if p.is_file() and any(x in p.name.lower() for x in PROTECTED_PATTERNS):
                try:out[p.name]=sha_file(p)
                except Exception:pass
    return out

def _atomic(path,payload):
    import tempfile
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix=path.name+".",suffix=".tmp",dir=str(path.parent))
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as f:
            json.dump(payload,f,ensure_ascii=False,indent=2,sort_keys=True,default=str);f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

def _summarize(cases,criteria,fwd,rev):
    per_aspect={a:Counter() for a in ASPECTS}
    per_kind=defaultdict(Counter)
    case_rows=[]
    for c in cases:
        cid=c["case_id"];cf=fwd.get(cid);cr=rev.get(cid);crit=criteria.get(cid)
        aspects={};unstable=0;stable_info=0;stable_unknown=0
        for a in ASPECTS:
            usable=bool((((crit or {}).get("aspects") or {}).get(a) or {}).get("usable"))
            fv=(((cf or {}).get("aspects") or {}).get(a) or {}).get("verdict","UNKNOWN")
            rv=(((cr or {}).get("aspects") or {}).get(a) or {}).get("verdict","UNKNOWN")
            if fv==rv:
                cls="STABLE_UNKNOWN" if fv=="UNKNOWN" else "STABLE_INFORMATIVE"
                stable_unknown += (cls=="STABLE_UNKNOWN")
                stable_info += (cls=="STABLE_INFORMATIVE")
            else:
                cls="ORDER_INSTABILITY";unstable+=1
            per_aspect[a][cls]+=1;per_kind[c["candidate_kind"]][cls]+=1
            aspects[a]={"usable":usable,"forward":fv,"reverse":rv,"class":cls,
                        "consensus":fv if fv==rv else "UNKNOWN"}
        if not cf or not cr or not crit:
            status="INCOMPLETE"
        elif unstable:
            status="CHALLENGE_ONLY"
        elif stable_info:
            status="SYMMETRIC_PROVISIONAL_SEED"
        else:
            status="TRUE_INFORMATION_GAP"
        case_rows.append({"case_id":cid,"candidate_kind":c["candidate_kind"],"status":status,
                          "stable_informative_aspects":stable_info,"stable_unknown_aspects":stable_unknown,
                          "unstable_aspects":unstable,"criteria_hash":(crit or {}).get("criteria_hash"),"aspects":aspects})
    n=max(1,len(cases))
    asp={a:{
      "stable_informative":c["STABLE_INFORMATIVE"],"stable_unknown":c["STABLE_UNKNOWN"],
      "order_instability":c["ORDER_INSTABILITY"],
      "order_instability_rate":round(c["ORDER_INSTABILITY"]/n,6),
      "symmetry_rate":round((c["STABLE_INFORMATIVE"]+c["STABLE_UNKNOWN"])/n,6),
    } for a,c in per_aspect.items()}
    kinds={}
    for k,c in per_kind.items():
        total=sum(c.values())
        kinds[k]={"aspect_judgments":total,"stable_informative":c["STABLE_INFORMATIVE"],
                  "stable_unknown":c["STABLE_UNKNOWN"],"order_instability":c["ORDER_INSTABILITY"],
                  "order_instability_rate":round(c["ORDER_INSTABILITY"]/max(1,total),6)}
    return case_rows,asp,kinds

def run(root=Path("."),client_factory=None):
    root=Path(root);before_protected=_protected(root)
    data=load_latest_u26(root);cases=data["cases"]
    u26_path=root/Path(".radar_runtime/discovery_boundary_sentinel_v1.sqlite3")
    u26_hash_before=sha_file(u26_path)
    pws={oid:pointwise_payload(x) for oid,x in data["pointwise"].items()}
    cp={c["case_id"]:canonical_pair(c) for c in cases}
    baseline=baseline_instability(cases)

    judge=SymmetricJudge(root,max_calls=int(os.getenv("SIGNALFORGE_U27_LLM_MAX_CALLS","6")),
                         criteria_batch=int(os.getenv("SIGNALFORGE_U27_CRITERIA_BATCH","8")),
                         judge_batch=int(os.getenv("SIGNALFORGE_U27_JUDGE_BATCH","8")),
                         client_factory=client_factory)
    if not judge.available:
        result={"engine_version":ENGINE_VERSION,"status":"BLOCKED_JUDGE_PROVIDER_UNAVAILABLE",
                "truth_boundary":TRUTH_BOUNDARY,"product_ideation":0}
        _atomic(root/STATE,result);return result

    criteria=judge.build_criteria(cases,pws,cp)
    forward=judge.judge(cases,pws,criteria,reverse=False)
    reverse=judge.judge(cases,pws,criteria,reverse=True)
    case_rows,after_aspects,kind_summary=_summarize(cases,criteria,forward,reverse)

    u26_hash_after=sha_file(u26_path)
    protected_after=_protected(root)
    readonly_ok=(u26_hash_before==u26_hash_after)
    authority_ok=(before_protected==protected_after)

    comparison={}
    critical=("WORKFLOW","FRICTION")
    rel_improvements=[]
    for a in ASPECTS:
        b=baseline[a]["order_instability_rate"];n=after_aspects[a]["order_instability_rate"]
        imp=(b-n)
        rel=(imp/b) if b>0 else (1.0 if n==0 else 0.0)
        comparison[a]={"u26_instability":b,"u27_instability":n,
                       "absolute_improvement":round(imp,6),"relative_improvement":round(rel,6)}
        if a in critical:rel_improvements.append(rel)

    baseline_overall=sum(x["order_instability_rate"] for x in baseline.values())/len(ASPECTS)
    new_overall=sum(x["order_instability_rate"] for x in after_aspects.values())/len(ASPECTS)
    overall_rel=(baseline_overall-new_overall)/baseline_overall if baseline_overall>0 else 0.0

    case_status=Counter(x["status"] for x in case_rows)
    criteria_reuse_ok=all(
        cid in forward and cid in reverse and forward[cid]["criteria_hash"]==reverse[cid]["criteria_hash"]==criteria[cid]["criteria_hash"]
        for cid in criteria
    )
    critical_ok=all(after_aspects[a]["order_instability_rate"]<=0.25 for a in critical)
    materially_improved=(overall_rel>=0.35 and critical_ok)

    if not readonly_ok or not authority_ok or not criteria_reuse_ok:
        status="FAIL_PROTOCOL_INTEGRITY"
    elif materially_improved:
        status="PASS_SYMMETRIC_PROTOCOL_IMPROVED"
    else:
        status="PASS_SYMMETRIC_PROTOCOL_SCREEN_NO_PROMOTION"

    summary_seed={"baseline":baseline,"after":after_aspects,"comparison":comparison,"judge":judge.diagnostics(),
                  "case_status_counts":dict(case_status),"u26_run_id":data["run"]["run_id"]}
    run_id="u27_"+hashlib.sha256(canonical_json(summary_seed).encode()).hexdigest()[:20]
    result={
      "engine_version":ENGINE_VERSION,"status":status,
      "source":{"u26_run_id":data["run"]["run_id"],"u26_status":data["run"]["status"],
                "u26_db_sha256_before":u26_hash_before,"u26_db_sha256_after":u26_hash_after,
                "u26_db_unchanged":readonly_ok,
                "frozen_snapshot_manifest_sha256":(data.get("snapshot") or {}).get("manifest_sha256")},
      "protocol":{
        "cases":len(cases),"criteria_built":len(criteria),"forward_cases":len(forward),"reverse_cases":len(reverse),
        "same_criteria_reused_bidirectionally":criteria_reuse_ok,
        "weak_labels_visible_to_judge":False,"candidate_kind_visible_to_judge":False
      },
      "baseline_u26":baseline,
      "u27_aspect_summary":after_aspects,
      "comparison":comparison,
      "candidate_kind_summary":kind_summary,
      "case_status_counts":dict(case_status),
      "judge":judge.diagnostics(),
      "authority":{"production_authority":0,"sentinel_promotion_allowed_from_u27":False,
                   "representation_promotion_allowed_from_u27":False},
      "founder_protected_state_unchanged":authority_ok,
      "decision":{
        "winner":None,"promotion":None,
        "materially_improved":materially_improved,
        "overall_relative_order_instability_reduction":round(overall_rel,6),
        "critical_workflow_friction_under_25pct":critical_ok,
        "next_gate":(
          "SECOND_JUDGE_REVIEW_THEN_SENTINEL_V1_FREEZE_CANDIDATE" if materially_improved
          else "DO_NOT_FREEZE_SENTINEL; REVISE_PAIRWISE_PROTOCOL_OR_CASE_SEMANTICS_BEFORE_SECOND_JUDGE"
        )
      },
      "truth_boundary":TRUTH_BOUNDARY,"product_ideation":0
    }
    save(root,run_id,status,result,criteria,forward,reverse)
    _atomic(root/STATE,result)
    return result
