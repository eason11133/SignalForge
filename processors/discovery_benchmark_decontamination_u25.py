from __future__ import annotations
import hashlib,json,os
from collections import Counter,defaultdict
from pathlib import Path

from processors.discovery_benchmark_contracts_u25 import ENGINE_VERSION,STATE,TRUTH_BOUNDARY,canonical_json
from processors.discovery_anchor_content_recovery_u25 import recover
from processors.discovery_anchor_audit_u24 import audit_groups,balanced_group_partitions
from processors.discovery_representation_arms_u24 import build_r0,salient_codes,vectorize_short,fixed_atom_text,FrameExtractor,frame_serialization,frame_description
from processors.discovery_representation_metrics_u24 import weak_label_proxy,cross_arm_table
from processors.discovery_benchmark_store_u25 import save
from processors.discovery_framegraph_projection_u23 import DB as PROJ_DB

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

def _sample(rows,max_items=34):
    by=defaultdict(list)
    for r in rows:by[r["signature"]].append(r)
    out=[]
    for sig in sorted(by):
        out.extend(by[sig][:2])
        if len(out)>=max_items:break
    return out[:max_items]

def run(root=Path("."),client_factory=None,raw_selection=None):
    root=Path(root)
    if not (root/PROJ_DB).exists():
        return {"engine_version":ENGINE_VERSION,"status":"BLOCKED_U23_PROJECTION_MISSING","truth_boundary":TRUTH_BOUNDARY}
    before=_protected(root)
    rows,recovery=recover(root,raw_selection)
    if recovery["legacy_label_leak_observations"]==0:
        legacy_status="NO_LEAK_DETECTED"
    else:
        legacy_status="LEAK_CONFIRMED"
    if recovery["recovered_content"]<20:
        result={"engine_version":ENGINE_VERSION,"status":"BLOCKED_INSUFFICIENT_DECONTAMINATED_ANCHORS",
                "recovery":recovery,"truth_boundary":TRUTH_BOUNDARY}
        _atomic(root/STATE,result);return result
    if recovery["recovered_label_leak_observations"]!=0:
        result={"engine_version":ENGINE_VERSION,"status":"BLOCKED_LABEL_LEAK_REMAINS",
                "recovery":recovery,"truth_boundary":TRUTH_BOUNDARY}
        _atomic(root/STATE,result);return result

    texts=[r["text"] for r in rows]
    X0,d0,word,Xw=build_r0(texts)
    audit=audit_groups(rows,X=X0)

    metrics={}
    metrics["R0_RAW_CONTENT"]={"status":"READY_DECONTAMINATED","proxy":weak_label_proxy(rows,X0),
      "sample_size":len(rows),"comparable_scope":"RECOVERED_NONLABEL_ANCHOR_CONTENT","diagnostics":d0}
    codes=salient_codes(word,Xw)
    X1,_=vectorize_short(codes)
    metrics["R1_SALIENT_CODE"]={"status":"READY_DECONTAMINATED","proxy":weak_label_proxy(rows,X1),
      "sample_size":len(rows),"comparable_scope":"RECOVERED_NONLABEL_ANCHOR_CONTENT"}
    atoms=[fixed_atom_text(t) for t in texts]
    X2,_=vectorize_short(atoms)
    metrics["R2_FIXED_ATOMS"]={"status":"READY_DECONTAMINATED","proxy":weak_label_proxy(rows,X2),
      "sample_size":len(rows),"comparable_scope":"RECOVERED_NONLABEL_ANCHOR_CONTENT",
      "all_unknown_atom_rate":round(sum(x=="ACTION=UNKNOWN FRICTION=UNKNOWN CONSTRAINT=UNKNOWN CONSEQUENCE=UNKNOWN" for x in atoms)/len(atoms),6)}

    llm_rows=_sample(rows)
    extractor=FrameExtractor(root,max_calls=int(os.getenv("SIGNALFORGE_U25_LLM_MAX_CALLS","2")),
                             batch_size=int(os.getenv("SIGNALFORGE_U25_LLM_BATCH","18")),
                             client_factory=client_factory)
    frames=extractor.extract(llm_rows) if extractor.available else {}
    framed=[r for r in llm_rows if r["observation_key"] in frames]
    if len(framed)>=8 and len({x["signature"] for x in framed})>=3:
        X3,_=vectorize_short([frame_serialization(frames[x["observation_key"]]) for x in framed])
        metrics["R3_HYBRID_FRAME"]={"status":"READY_DECONTAMINATED_SHADOW_SAMPLE","proxy":weak_label_proxy(framed,X3),
          "sample_size":len(framed),"comparable_scope":"DECONTAMINATED_LLM_ANCHOR_SUBSET"}
        X4,_=vectorize_short([frame_description(frames[x["observation_key"]]) for x in framed])
        metrics["R4_FRAME_DESCRIPTION"]={"status":"READY_DECONTAMINATED_SHADOW_SAMPLE","proxy":weak_label_proxy(framed,X4),
          "sample_size":len(framed),"comparable_scope":"SAME_DECONTAMINATED_LLM_ANCHOR_SUBSET"}
    else:
        st="PROVIDER_UNAVAILABLE" if not extractor.available else "INSUFFICIENT_VALID_FRAME_SAMPLE"
        metrics["R3_HYBRID_FRAME"]={"status":st,"proxy":None,"sample_size":len(framed),"comparable_scope":"NOT_COMPARABLE"}
        metrics["R4_FRAME_DESCRIPTION"]={"status":st,"proxy":None,"sample_size":len(framed),"comparable_scope":"NOT_COMPARABLE"}

    after=_protected(root)
    run_payload={"recovery":recovery,"audit":audit,"metrics":metrics,"llm":extractor.diag()}
    run_id="u25_"+hashlib.sha256(canonical_json(run_payload).encode()).hexdigest()[:20]
    status="PASS_BENCHMARK_DECONTAMINATION" if before==after else "FAIL_FOUNDER_PROTECTED_STATE_MUTATED"
    result={
      "engine_version":ENGINE_VERSION,"status":status,
      "benchmark_lineage":{"U24_WEAK_LABEL_PROXY":"INVALIDATED_FOR_MODEL_COMPARISON",
        "reason":"219 weak-anchor representation inputs came from explicit signature label fields"},
      "recovery":recovery,
      "anchor_audit":audit,
      "arm_metrics":metrics,
      "arm_comparison":cross_arm_table(metrics),
      "llm_shadow":{"sample_requested":len(llm_rows),"frames_returned":len(frames),"diagnostics":extractor.diag()},
      "authority":{"production_authority":0,"promotion_allowed_from_u25":False},
      "founder_protected_state_unchanged":before==after,
      "decision":{"winner":None,"promotion":None,
        "reason":"DECONTAMINATION_REBUILDS_THE_BENCHMARK_INPUT_CONTRACT; WEAK_LABELS_REMAIN_UNAUDITED",
        "next_gate":"USE_RECOVERED_CONTENT_TO_BUILD_REAL_BOUNDARY_CASES_AND_A_FROZEN_SENTINEL_BEFORE_PROMOTION"},
      "truth_boundary":TRUTH_BOUNDARY,"product_ideation":0,
    }
    save(root,run_id,status,result,rows)
    _atomic(root/STATE,result)
    return result
