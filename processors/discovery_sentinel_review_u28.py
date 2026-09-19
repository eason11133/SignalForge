from __future__ import annotations
import hashlib,json,os
from collections import Counter,defaultdict
from pathlib import Path
from processors.discovery_sentinel_review_contracts_u28 import ENGINE_VERSION,STATE,TRUTH_BOUNDARY,ASPECTS,canonical_json,sha256_text
from processors.discovery_sentinel_review_loader_u28 import load_sources,build_review_units,sha_file
from processors.discovery_sentinel_second_pass_u28 import SecondPassReviewer
from processors.discovery_sentinel_candidate_store_u28 import save

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

def run(root=Path("."),client_factory=None):
    root=Path(root);before_protected=_protected(root)
    data=load_sources(root);units,case_payloads=build_review_units(data)
    if not units or not case_payloads:
        return {"engine_version":ENGINE_VERSION,"status":"BLOCKED_NO_U27_REVIEW_UNITS","truth_boundary":TRUTH_BOUNDARY}
    u27_model=((data["u27_summary"].get("judge") or {}).get("model") or "UNKNOWN")
    reviewer=SecondPassReviewer(root,u27_model=u27_model,max_calls=int(os.getenv("SIGNALFORGE_U28_LLM_MAX_CALLS","2")),
        batch_size=int(os.getenv("SIGNALFORGE_U28_BATCH","8")),client_factory=client_factory)
    if not reviewer.available:
        result={"engine_version":ENGINE_VERSION,"status":"BLOCKED_REVIEW_PROVIDER_UNAVAILABLE","truth_boundary":TRUTH_BOUNDARY,"product_ideation":0}
        _atomic(root/STATE,result);return result
    reviews=reviewer.review(case_payloads)

    out=[];counts=Counter();aspect_counts=defaultdict(Counter);stable_info=agree=0
    for u in units:
        rev=reviews.get(u["case_id"]) or {}
        ro=((rev.get("aspects") or {}).get(u["aspect"]) or {})
        rv=ro.get("verdict") or "UNKNOWN"
        if not u["usable"]:status="UNUSABLE_CRITERION"
        elif not u["u27_stable"]:status="U27_ORDER_CHALLENGE"
        elif u["u27_consensus"]!="UNKNOWN":
            stable_info+=1
            if rv==u["u27_consensus"]:status="SEMANTIC_SENTINEL_CANDIDATE";agree+=1
            else:status="SECOND_PASS_DISAGREEMENT"
        else:
            status="UNKNOWN_REJECTION_CANDIDATE" if rv=="UNKNOWN" else "SECOND_PASS_DISAGREEMENT"
        x=dict(u);x["review_verdict"]=rv;x["candidate_status"]=status;x["review"]=ro
        out.append(x);counts[status]+=1;aspect_counts[u["aspect"]][status]+=1

    agreement=agree/max(1,stable_info)
    semantic=[x for x in out if x["candidate_status"]=="SEMANTIC_SENTINEL_CANDIDATE"]
    cases_covered=len({x["case_id"] for x in semantic});aspects_covered=len({x["aspect"] for x in semantic})
    critical={}
    for a in ("WORKFLOW","FRICTION"):
        denom=sum(1 for x in units if x["aspect"]==a and x["usable"] and x["u27_stable"] and x["u27_consensus"]!="UNKNOWN")
        num=sum(1 for x in semantic if x["aspect"]==a)
        critical[a]={"eligible":denom,"agreed":num,"agreement_rate":round(num/max(1,denom),6)}

    hashes=data["hashes"];source_integrity=(hashes["u26_before"]==hashes["u26_after"] and hashes["u27_before"]==hashes["u27_after"])
    after_protected=_protected(root);authority_ok=(before_protected==after_protected)
    gate=(len(semantic)>=20 and cases_covered>=8 and aspects_covered>=3 and agreement>=0.75 and
          all(critical[a]["agreement_rate"]>=0.75 for a in critical))
    independence=reviewer.independence_level
    if not source_integrity or not authority_ok:status="FAIL_SENTINEL_REVIEW_INTEGRITY"
    elif gate:status=("PASS_SENTINEL_V1_CANDIDATE_MODEL_DISTINCT" if independence=="MODEL_DISTINCT"
                      else "PASS_SENTINEL_V1_CANDIDATE_PROMPT_DISTINCT_ONLY")
    else:status="PASS_SECOND_REVIEW_SCREEN_NO_SENTINEL_CANDIDATE"

    manifest_rows=[{"case_id":x["case_id"],"aspect":x["aspect"],"criteria_hash":x["criteria_hash"],
                    "verdict":x["u27_consensus"],"left_text_sha256":x["left_text_sha256"],
                    "right_text_sha256":x["right_text_sha256"]} for x in semantic]
    manifest={"manifest_sha256":sha256_text(canonical_json(manifest_rows)),
              "source_snapshot_sha256":(data.get("snapshot") or {}).get("manifest_sha256"),
              "independence_level":independence,"candidate_count":len(semantic)}
    summary_seed={"u27_run_id":data["u27_run"]["run_id"],"counts":dict(counts),"agreement":agreement,
                  "manifest":manifest,"reviewer":reviewer.diagnostics()}
    run_id="u28_"+hashlib.sha256(canonical_json(summary_seed).encode()).hexdigest()[:20]
    result={
      "engine_version":ENGINE_VERSION,"status":status,
      "source":{"u27_run_id":data["u27_run"]["run_id"],"u26_run_id":data["u26_run_id"],
                "u26_db_unchanged":hashes["u26_before"]==hashes["u26_after"],
                "u27_db_unchanged":hashes["u27_before"]==hashes["u27_after"],
                "frozen_snapshot_manifest_sha256":manifest["source_snapshot_sha256"]},
      "review":{"cases":len(case_payloads),"aspect_units":len(units),"reviewed_cases":len(reviews),
                "stable_informative_units":stable_info,"stable_informative_exact_agreement":agree,
                "stable_informative_agreement_rate":round(agreement,6),"status_counts":dict(counts),
                "critical_aspect_agreement":critical,"semantic_candidate_cases":cases_covered,
                "semantic_candidate_aspects":aspects_covered},
      "aspect_status_counts":{a:dict(c) for a,c in aspect_counts.items()},
      "reviewer":reviewer.diagnostics(),"candidate_manifest":manifest,
      "authority":{"production_authority":0,"sentinel_v1_frozen":False,"sentinel_candidate_created":gate,
                   "representation_promotion_allowed_from_u28":False},
      "founder_protected_state_unchanged":authority_ok,
      "decision":{"winner":None,"representation_promotion":None,"candidate_gate_pass":gate,
                  "independence_level":independence,
                  "next_gate":("FREEZE_INTEGRITY_REPLAY_THEN_SENTINEL_V1" if gate and independence=="MODEL_DISTINCT"
                               else "FREEZE_INTEGRITY_REPLAY_WITH_PROMPT_DISTINCT_PROVENANCE; KEEP_MODEL_INDEPENDENCE_LIMITATION_EXPLICIT"
                               if gate else "DO_NOT_FREEZE; REVIEW_SECOND_PASS_DISAGREEMENTS_AND_EXPAND_SENTINEL_CANDIDATES")},
      "truth_boundary":TRUTH_BOUNDARY,"product_ideation":0}
    save(root,run_id,status,result,out,manifest);_atomic(root/STATE,result);return result
