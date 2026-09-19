from __future__ import annotations
import hashlib,json,os
from collections import Counter
from pathlib import Path

from processors.discovery_boundary_contracts_u26 import ENGINE_VERSION,STATE,TRUTH_BOUNDARY,ASPECTS,canonical_json
from processors.discovery_boundary_candidates_u26 import load_latest_decontaminated_rows,generate_candidates,freeze_snapshot
from processors.discovery_boundary_judge_u26 import BoundaryJudge
from processors.discovery_boundary_store_u26 import save

PROTECTED_PATTERNS=("u14","u15","u16","u17","u18","founder_thesis","evidence_adjudication","thesis_conditioned")

def _sha(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):h.update(b)
    return h.hexdigest()
def _protected(root):
    rt=root/".radar_runtime";out={}
    if rt.exists():
        for p in rt.iterdir():
            if p.is_file() and any(x in p.name.lower() for x in PROTECTED_PATTERNS):
                try:out[p.name]=_sha(p)
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

def _adjudicate_case(c,pw,fwd,rev):
    fid=fwd.get(c["case_id"]);rid=rev.get(c["case_id"])
    left_pw=pw.get(c["left"]["observation_key"]);right_pw=pw.get(c["right"]["observation_key"])
    grounding=bool(left_pw and right_pw and left_pw.get("all_evidence_grounded") and right_pw.get("all_evidence_grounded"))
    aspects={}
    consistent=True;informative=0
    for a in ASPECTS:
        fv=((fid or {}).get("aspects") or {}).get(a,{}).get("verdict","UNKNOWN")
        rv=((rid or {}).get("aspects") or {}).get(a,{}).get("verdict","UNKNOWN")
        same=(fv==rv)
        if not same:consistent=False
        if same and fv!="UNKNOWN":informative+=1
        aspects[a]={
          "forward":fv,"reverse":rv,"consistent":same,
          "criteria_forward":((fid or {}).get("aspects") or {}).get(a,{}).get("criteria",""),
          "criteria_reverse":((rid or {}).get("aspects") or {}).get(a,{}).get("criteria",""),
          "consensus":fv if same else "UNKNOWN",
        }
    if not fid or not rid or not grounding or informative==0:
        status="INSUFFICIENT"
    elif consistent:
        status="PROVISIONAL_SENTINEL_SEED"
    else:
        status="CHALLENGE_ONLY"
    return status,{
      "pointwise_grounding_pass":grounding,"bidirectional_consistency_pass":consistent,
      "informative_consensus_aspects":informative,"aspects":aspects,
      "truth_boundary":"CONSISTENT_LLM_ADJUDICATION_IS_PROVISIONAL_BENCHMARK_SEED_NOT_GROUND_TRUTH",
    }

def run(root=Path("."),client_factory=None):
    root=Path(root);before=_protected(root)
    rows,lineage=load_latest_decontaminated_rows(root)
    snapshot=freeze_snapshot(root,rows,lineage)
    candidates,cand_diag=generate_candidates(rows,max_cases=int(os.getenv("SIGNALFORGE_U26_MAX_CASES","16")))

    # Unique frozen observations; weak labels are not included in any judge prompt.
    obs={}
    for c in candidates:
        obs[c["left"]["observation_key"]]=c["left"]
        obs[c["right"]["observation_key"]]=c["right"]
    observations=list(obs.values())

    judge=BoundaryJudge(root,max_calls=int(os.getenv("SIGNALFORGE_U26_LLM_MAX_CALLS","6")),
                        point_batch=int(os.getenv("SIGNALFORGE_U26_POINT_BATCH","16")),
                        pair_batch=int(os.getenv("SIGNALFORGE_U26_PAIR_BATCH","8")),
                        client_factory=client_factory)
    if not judge.available:
        result={"engine_version":ENGINE_VERSION,"status":"BLOCKED_JUDGE_PROVIDER_UNAVAILABLE",
                "snapshot":snapshot,"candidate_count":len(candidates),"truth_boundary":TRUTH_BOUNDARY}
        _atomic(root/STATE,result);return result

    pw=judge.pointwise_extract(observations)
    # attach hash for persistence
    for oid,x in pw.items():
        x["text_sha256"]=obs[oid]["text_sha256"]
    fwd=judge.pairwise(candidates,pw,reverse=False)
    rev=judge.pairwise(candidates,pw,reverse=True)

    finals=[];counts=Counter();aspect_consistency=Counter()
    for c in candidates:
        status,adj=_adjudicate_case(c,pw,fwd,rev)
        cc=dict(c);cc["status"]=status;cc["adjudication"]=adj;finals.append(cc);counts[status]+=1
        for a,z in adj["aspects"].items():
            aspect_consistency[a]+=1 if z["consistent"] else 0

    after=_protected(root)
    authority_ok=(before==after)
    provisional=[c for c in finals if c["status"]=="PROVISIONAL_SENTINEL_SEED"]
    status="PASS_PROVISIONAL_SENTINEL_SEED" if authority_ok and provisional else (
      "PASS_BOUNDARY_CHALLENGE_ONLY" if authority_ok else "FAIL_FOUNDER_PROTECTED_STATE_MUTATED")
    summary_seed={
      "engine_version":ENGINE_VERSION,"snapshot":snapshot,"candidate_count":len(candidates),
      "case_status_counts":dict(counts),"judge":judge.diagnostics(),
      "provisional_seed_cases":len(provisional)
    }
    run_id="u26_"+hashlib.sha256(canonical_json(summary_seed).encode()).hexdigest()[:20]

    result={
      "engine_version":ENGINE_VERSION,"status":status,
      "source_snapshot":snapshot,
      "candidate_generation":{
        "cases":len(candidates),"unique_observations":len(observations),
        "kind_counts":dict(Counter(c["candidate_kind"] for c in candidates)),
        "tfidf_diagnostics":cand_diag,
        "truth_boundary":"WEAK_SIGNATURES_ARE_USED_ONLY_FOR_CASE_MINING_AND_ARE_HIDDEN_FROM_JUDGE"
      },
      "pointwise":{"requested":len(observations),"returned":len(pw),
                   "fully_grounded":sum(1 for x in pw.values() if x.get("all_evidence_grounded"))},
      "adjudication":{
        "forward_cases":len(fwd),"reverse_cases":len(rev),"case_status_counts":dict(counts),
        "aspect_bidirectional_consistency":{
          a:round(aspect_consistency[a]/max(1,len(candidates)),6) for a in ASPECTS},
        "cases":[{
          "case_id":c["case_id"],"candidate_kind":c["candidate_kind"],
          "candidate_similarity_proxy":c["candidate_similarity_proxy"],
          "weak_labels":[c["left"]["signature"],c["right"]["signature"]],
          "status":c["status"],"informative_consensus_aspects":c["adjudication"]["informative_consensus_aspects"],
          "consensus":{a:z["consensus"] for a,z in c["adjudication"]["aspects"].items()}
        } for c in finals]
      },
      "judge":judge.diagnostics(),
      "authority":{"production_authority":0,"representation_promotion_allowed_from_u26":False,
                   "sentinel_status":"PROVISIONAL_SEED_ONLY"},
      "founder_protected_state_unchanged":authority_ok,
      "decision":{
        "winner":None,"promotion":None,
        "next_gate":"MANUAL_OR_SECOND_JUDGE_REVIEW_OF_CHALLENGE_CASES_THEN_FREEZE_SENTINEL_V1_AND_RUN_REAL_ARM_RACE",
        "reason":"U26_CREATES_A_PROVISIONAL_EVIDENCE_GROUNDED_BIDIRECTIONALLY_CHECKED_SENTINEL_SEED_NOT_GOLD_TRUTH"
      },
      "truth_boundary":TRUTH_BOUNDARY,"product_ideation":0,
    }
    save(root,run_id,status,result,snapshot,finals,pw)
    _atomic(root/STATE,result)
    return result
