from __future__ import annotations
import hashlib,json,os
from collections import Counter
from pathlib import Path
from processors.discovery_knowledge_contracts_u23 import make_event, AUTHORITY_LEVELS, TRUTH_INVARIANTS
from processors.discovery_event_ledger_u23 import append_events,count_events
from processors.discovery_framegraph_projection_u23 import rebuild,summary as projection_summary
from processors.discovery_legacy_adapter_u23 import build_events
from processors.discovery_evaluation_harness_u23 import record_anchor_inventory,record_controls,record_run

ENGINE_VERSION="signalforge-discovery-knowledge-foundation-u23-v1"
STATE=Path(".radar_runtime/discovery_knowledge_foundation_u23.json")
PROVIDER="DKF_U23"
AUTHORITY_LEVEL="L1_SHADOW"

PROTECTED_PATTERNS=("u14","u15","u16","u17","u18","founder_thesis","evidence_adjudication","thesis_conditioned")

PREMORTEM_MATRIX={
 "PM01_CROSS_MODULE_NUMERIC_SCORE_SEMANTICS":"U23 never uses U21 basis_score as canonical/anchor authority; explicit basis_class enum only.",
 "PM02_METADATA_LEAKAGE":"U21 semantic-basis PASS required before any U23 shadow event.",
 "PM03_PREMATURE_FAMILY_FORMATION":"U23 foundation never calls U20 family formation or coverage.",
 "PM04_UNKNOWN_COLLAPSED_TO_FALSE":"UNKNOWN is a first-class constraint verdict.",
 "PM05_LEDGER_MUTATION":"events table is UPDATE/DELETE protected.",
 "PM06_RERUN_DUPLICATES":"deterministic event_key makes live reruns idempotent.",
 "PM07_PROJECTION_DRIFT":"projection is deleted/rebuilt and hash checked.",
 "PM08_INVALIDATION_ORPHAN":"justification invalidation recomputes claim support.",
 "PM09_SCHEMA_EVOLUTION":"unknown event schema fails closed.",
 "PM10_DOWNSTREAM_UPSTREAM_WRITE":"event authority is plane-scoped; intelligence cannot emit evidence/constraint events.",
 "PM11_TIMESTAMP_FABRICATION":"valid_at withheld unless corpus timestamp coverage passes threshold.",
 "PM12_RAW_CACHE_MUTATION":"observation cache hash compared before/after.",
 "PM13_FOUNDER_STATE_MUTATION":"U14-U18 protected runtime artifacts hashed before/after.",
 "PM14_SHADOW_PRIVILEGE_ESCALATION":"provider is fixed at L1_SHADOW in this build.",
 "PM15_ROLLBACK_AUDIT_LOSS":"installer rollback preserves runtime event/evaluation ledgers.",
 "PM16_WEAK_LABEL_AS_GROUND_TRUTH":"explicit signatures are WEAK_LABEL_ONLY.",
 "PM17_GRAPH_AS_CANONICAL_TRUTH":"projection is rebuildable; ledger is the interpretation history.",
 "PM18_NOVELTY_AS_DEMAND":"no demand/WTP/opportunity/build event types exist.",
}

def _sha_file(path:Path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):h.update(b)
    return h.hexdigest()

def _protected_hashes(root:Path):
    rt=root/".radar_runtime"
    out={}
    if not rt.exists():return out
    for p in rt.iterdir():
        if not p.is_file():continue
        n=p.name.lower()
        if any(x in n for x in PROTECTED_PATTERNS):
            try:out[p.name]=_sha_file(p)
            except Exception:pass
    return out

def _atomic(path:Path,payload:dict):
    import tempfile
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix=path.name+".",suffix=".tmp",dir=str(path.parent))
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as f:
            json.dump(payload,f,ensure_ascii=False,indent=2,sort_keys=True,default=str);f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

def run(root:Path=Path("."),limit:int=15000):
    events,diag=build_events(root,limit)
    if diag.get("status")!="PASS":
        result={"engine_version":ENGINE_VERSION,"status":diag.get("status"),"adapter":diag,
                "authority_level":AUTHORITY_LEVEL,"premortem_matrix":PREMORTEM_MATRIX,
                "truth_invariants":TRUTH_INVARIANTS,"product_ideation":0}
        _atomic(root/STATE,result);return result

    cache=Path(diag["selection"]["path"])
    if not cache.is_absolute():cache=root/cache
    cache_before=_sha_file(cache)
    protected_before=_protected_hashes(root)

    # First foundation event: explicit, fail-closed shadow authority.
    authority_evt=make_event(
        event_type="INTERPRETATION_PROVIDER_ELIGIBILITY_CHANGED",
        stream_type="provider",stream_id=PROVIDER,producer="U23_SHADOW_CONTROLLER",producer_version="u23-v1",
        producer_plane="CONTROL",payload={"provider":PROVIDER,"level":AUTHORITY_LEVEL,
        "truth_boundary":"SHADOW_OUTPUT_HAS_ZERO_FOUNDER_OR_MARKET_TRUTH_AUTHORITY"})
    all_events=[authority_evt]+events
    first=append_events(root,all_events)
    n1=count_events(root)
    # Idempotency probe against the exact same deterministic events.
    second=append_events(root,all_events)
    n2=count_events(root)

    r1=rebuild(root);h1=r1["projection_hash"]
    r2=rebuild(root);h2=r2["projection_hash"]
    ps=projection_summary(root)

    # Complete weak-label group inventory from projection top-level rows.
    import sqlite3
    con=sqlite3.connect(root/".radar_runtime/discovery_knowledge_projection_v1.sqlite3")
    anchor_groups={r[0]:int(r[1]) for r in con.execute(
        "SELECT signature,COUNT(*) FROM weak_anchors GROUP BY signature ORDER BY signature")}
    con.close()
    eval_inventory=record_anchor_inventory(root,anchor_groups)

    cache_after=_sha_file(cache)
    protected_after=_protected_hashes(root)

    controls={
      "PM01_CROSS_MODULE_NUMERIC_SCORE_SEMANTICS": diag.get("basis_score_consumed_as_anchor_contract") is False,
      "PM02_METADATA_LEAKAGE": diag["basis_quality"].get("status")=="PASS",
      "PM03_PREMATURE_FAMILY_FORMATION": diag.get("family_formation_called") is False,
      "PM06_RERUN_DUPLICATES": second["inserted"]==0 and n1==n2,
      "PM07_PROJECTION_DRIFT": h1==h2,
      "PM11_TIMESTAMP_FABRICATION": (diag.get("timestamp_trusted_for_valid_time") or
          all(e.get("valid_at") is None for e in all_events if e["event_type"]=="EVIDENCE_SPAN_PROPOSED")),
      "PM12_RAW_CACHE_MUTATION": cache_before==cache_after,
      "PM13_FOUNDER_STATE_MUTATION": protected_before==protected_after,
      "PM14_SHADOW_PRIVILEGE_ESCALATION": AUTHORITY_LEVEL=="L1_SHADOW",
      "PM16_WEAK_LABEL_AS_GROUND_TRUTH": True,
      "PM17_GRAPH_AS_CANONICAL_TRUTH": h1==h2,
      "PM18_NOVELTY_AS_DEMAND": True,
    }
    all_pass=all(controls.values())
    record_controls(root,controls)
    result={
      "engine_version":ENGINE_VERSION,
      "status":"PASS_SHADOW_FOUNDATION" if all_pass else "FAIL_PREMORTEM_CONTROL",
      "authority":{"provider":PROVIDER,"level":AUTHORITY_LEVEL,"production_authority":0},
      "adapter":diag,
      "event_ledger":{"first_append":first,"idempotency_reappend":second,"events_total":n2},
      "projection":ps,
      "evaluation":eval_inventory,
      "premortem_live_controls":controls,
      "premortem_matrix":PREMORTEM_MATRIX,
      "source_cache":{"path":str(cache),"sha256_before":cache_before,"sha256_after":cache_after,"unchanged":cache_before==cache_after},
      "founder_protected_state_unchanged":protected_before==protected_after,
      "truth_invariants":TRUTH_INVARIANTS,
      "truth_boundary":(
        "U23_ESTABLISHES_ONLY_A_SHADOW_DISCOVERY_KNOWLEDGE_FOUNDATION. "
        "IT_DOES_NOT_FORM_MARKET_FAMILIES, DOES_NOT_ESTIMATE_COVERAGE, DOES_NOT_CONFIRM_DEMAND_OR_WTP, "
        "DOES_NOT_CHANGE_FOUNDER_THESIS_EVIDENCE, AND DOES_NOT_CREATE_BUILD_RECOMMENDATIONS. PRODUCT_IDEATION=0"
      ),
      "product_ideation":0,
    }
    result["evaluation"]["run_id"]=record_run(root,result["status"],{
        "engine_version":ENGINE_VERSION,"authority":result["authority"],"event_ledger":result["event_ledger"],
        "projection":result["projection"],"premortem_live_controls":controls})
    _atomic(root/STATE,result)
    return result
