from __future__ import annotations
import os
for _k in ("OPENBLAS_NUM_THREADS","OMP_NUM_THREADS","MKL_NUM_THREADS","NUMEXPR_NUM_THREADS","VECLIB_MAXIMUM_THREADS","BLIS_NUM_THREADS"):
    os.environ.setdefault(_k,"1")
import hashlib,json,os,sqlite3
from collections import defaultdict
from pathlib import Path

from processors.discovery_representation_contracts_u24 import ENGINE_VERSION,STATE,TRUTH_BOUNDARY,ARMS,canonical_json
from processors.discovery_anchor_audit_u24 import load_anchor_rows,load_all_rows,audit_groups
from processors.discovery_representation_arms_u24 import build_r0,salient_codes,vectorize_short,fixed_atom_text,FrameExtractor,frame_serialization,frame_description
from processors.discovery_representation_metrics_u24 import weak_label_proxy,cross_arm_table
from processors.discovery_representation_store_u24 import save
from processors.discovery_knowledge_contracts_u23 import make_event
from processors.discovery_event_ledger_u23 import append_events
from processors.discovery_framegraph_projection_u23 import rebuild

PROTECTED_PATTERNS=("u14","u15","u16","u17","u18","founder_thesis","evidence_adjudication","thesis_conditioned")
PROVIDER_PREFIX="DKF_U24_"

def _sha_file(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):h.update(b)
    return h.hexdigest()
def _protected(root):
    rt=root/".radar_runtime";out={}
    if rt.exists():
        for p in rt.iterdir():
            if p.is_file() and any(x in p.name.lower() for x in PROTECTED_PATTERNS):
                try:out[p.name]=_sha_file(p)
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

def _subset_for_llm(all_rows,anchor_rows,max_items=44):
    amap={x["observation_key"]:x for x in anchor_rows}
    by=defaultdict(list)
    for r in anchor_rows:by[r["signature"]].append(r)
    selected=[]
    # diversity first: up to 2 examples per weak signature group
    for sig in sorted(by):
        selected.extend(by[sig][:2])
    seen={x["observation_key"] for x in selected}
    # then add composite cases, which are exactly where deeper decomposition is most justified
    for r in all_rows:
        if len(selected)>=max_items:break
        if r["route"]=="COMPOSITE_CANDIDATE" and r["observation_key"] not in seen:
            selected.append(r);seen.add(r["observation_key"])
    return selected[:max_items]

def _anchor_subset_with_frames(anchor_rows,frames):
    return [r for r in anchor_rows if r["observation_key"] in frames]

def _register_shadow_arms(root):
    events=[]
    for arm in ARMS:
        provider=PROVIDER_PREFIX+arm
        events.append(make_event(
          event_type="INTERPRETATION_PROVIDER_ELIGIBILITY_CHANGED",stream_type="provider",stream_id=provider,
          producer="U24_REPRESENTATION_LAB",producer_version="u24-v1",producer_plane="CONTROL",
          payload={"provider":provider,"level":"L1_SHADOW",
                   "truth_boundary":"REPRESENTATION_ARM_HAS_ZERO_PRODUCTION_AUTHORITY"}))
    return append_events(root,events)

def run(root=Path("."),client_factory=None):
    root=Path(root)
    protected_before=_protected(root)
    # U23 foundation must already exist and be L1 shadow.
    proj=root/".radar_runtime/discovery_knowledge_projection_v1.sqlite3"
    if not proj.exists():
        return {"engine_version":ENGINE_VERSION,"status":"BLOCKED_U23_PROJECTION_MISSING","truth_boundary":TRUTH_BOUNDARY}

    anchor_rows=load_anchor_rows(root);all_rows=load_all_rows(root)
    texts=[r["text"] for r in anchor_rows]
    if len(anchor_rows)<20:
        return {"engine_version":ENGINE_VERSION,"status":"BLOCKED_INSUFFICIENT_WEAK_ANCHOR_OBSERVATIONS",
                "anchor_observations":len(anchor_rows),"truth_boundary":TRUTH_BOUNDARY}

    X0,diag0,word,Xw=build_r0(texts)
    audit=audit_groups(anchor_rows,X=X0)
    metrics={}
    metrics["R0_RAW_TEXT"]={"status":"READY","proxy":weak_label_proxy(anchor_rows,X0),
                            "sample_size":len(anchor_rows),"comparable_scope":"ALL_WEAK_ANCHORS","diagnostics":diag0}

    codes=salient_codes(word,Xw)
    X1,_=vectorize_short(codes)
    metrics["R1_SALIENT_CODE"]={"status":"READY","proxy":weak_label_proxy(anchor_rows,X1),
                                "sample_size":len(anchor_rows),"comparable_scope":"ALL_WEAK_ANCHORS",
                                "truth_boundary":"CHEAP_INDUCTIVE_CODE_BASELINE_NOT_CANONICAL_CODING"}

    atoms=[fixed_atom_text(t) for t in texts]
    X2,_=vectorize_short(atoms)
    metrics["R2_FIXED_ATOMS"]={"status":"READY","proxy":weak_label_proxy(anchor_rows,X2),
                               "sample_size":len(anchor_rows),"comparable_scope":"ALL_WEAK_ANCHORS",
                               "unknown_atom_rate":round(sum("UNKNOWN" in x for x in atoms)/len(atoms),6),
                               "truth_boundary":"RULE_BASED_FIXED_ATOMS_ARE_BASELINE_FEATURES_NOT_SEMANTIC_TRUTH"}

    llm_sample=_subset_for_llm(all_rows,anchor_rows)
    extractor=FrameExtractor(root,max_calls=int(os.getenv("SIGNALFORGE_U24_LLM_MAX_CALLS","2")),
                             batch_size=int(os.getenv("SIGNALFORGE_U24_LLM_BATCH","24")),
                             client_factory=client_factory)
    frames={}
    if extractor.available:
        frames=extractor.extract(llm_sample)
    framed_anchors=_anchor_subset_with_frames(anchor_rows,frames)
    if len(framed_anchors)>=8 and len({x["signature"] for x in framed_anchors})>=3:
        r3texts=[frame_serialization(frames[x["observation_key"]]) for x in framed_anchors]
        X3,_=vectorize_short(r3texts)
        metrics["R3_HYBRID_FRAME"]={"status":"READY_SHADOW_SAMPLE","proxy":weak_label_proxy(framed_anchors,X3),
                                   "sample_size":len(framed_anchors),"comparable_scope":"LLM_SHADOW_ANCHOR_SUBSET"}
        r4texts=[frame_description(frames[x["observation_key"]]) for x in framed_anchors]
        X4,_=vectorize_short(r4texts)
        metrics["R4_FRAME_DESCRIPTION"]={"status":"READY_SHADOW_SAMPLE","proxy":weak_label_proxy(framed_anchors,X4),
                                         "sample_size":len(framed_anchors),"comparable_scope":"SAME_LLM_SHADOW_ANCHOR_SUBSET",
                                         "truth_boundary":"R4_ADDS_DESCRIPTION_ALIGNMENT_WITHOUT_EXTRA_LLM_CALLS"}
    else:
        status="PROVIDER_UNAVAILABLE" if not extractor.available else "INSUFFICIENT_VALID_FRAME_SAMPLE"
        metrics["R3_HYBRID_FRAME"]={"status":status,"proxy":None,"sample_size":len(framed_anchors),
                                   "comparable_scope":"NOT_COMPARABLE"}
        metrics["R4_FRAME_DESCRIPTION"]={"status":status,"proxy":None,"sample_size":len(framed_anchors),
                                         "comparable_scope":"NOT_COMPARABLE"}

    provider_append=_register_shadow_arms(root);rebuild(root)
    protected_after=_protected(root)
    authority_ok=(protected_before==protected_after)

    run_payload={"engine_version":ENGINE_VERSION,"anchor_groups":len(audit["groups"]),
                 "anchor_observations":len(anchor_rows),"arm_metrics":metrics,
                 "llm":extractor.diag(),"llm_sample_requested":len(llm_sample),"llm_frames_returned":len(frames)}
    run_id="u24_"+hashlib.sha256(canonical_json(run_payload).encode()).hexdigest()[:20]
    status="PASS_SHADOW_REPRESENTATION_AUDIT" if authority_ok else "FAIL_FOUNDER_PROTECTED_STATE_MUTATED"
    result={
      "engine_version":ENGINE_VERSION,"status":status,
      "authority":{"all_arms":"L1_SHADOW","production_authority":0,"promotion_allowed_from_u24":False},
      "corpus":{"all_semantic_rows":len(all_rows),"weak_anchor_observations":len(anchor_rows),
                "distinct_weak_signature_groups":len(audit["groups"]),
                "granularity_routes":dict(__import__("collections").Counter(x["route"] for x in all_rows))},
      "anchor_audit":audit,
      "arm_metrics":metrics,
      "arm_comparison":cross_arm_table(metrics),
      "llm_shadow":{"sample_requested":len(llm_sample),"frames_returned":len(frames),"diagnostics":extractor.diag()},
      "provider_events":provider_append,
      "founder_protected_state_unchanged":authority_ok,
      "decision":{
        "winner":None,"promotion":None,
        "reason":"WEAK_SIGNATURE_GROUPS_REQUIRE_ANCHOR_AUDIT_AND_R3_R4_USE_A_BOUNDED_SUBSET; U24_IS_SCREENING_ONLY",
        "next_gate":"BUILD_FROZEN_SENTINEL_FROM_AUDITED_CASES_PLUS_REAL_BOUNDARIES_BEFORE_ANY_ARM_PROMOTION",
      },
      "truth_boundary":TRUTH_BOUNDARY,"product_ideation":0,
    }
    save(root,run_id,status,result,audit,metrics,frames)
    _atomic(root/STATE,result)
    return result
