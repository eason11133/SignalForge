from __future__ import annotations
import os
for _k in ("OPENBLAS_NUM_THREADS","OMP_NUM_THREADS","MKL_NUM_THREADS","NUMEXPR_NUM_THREADS","VECLIB_MAXIMUM_THREADS","BLIS_NUM_THREADS"):
    os.environ[_k]="1"
import json,sqlite3,tempfile
from pathlib import Path

import processors.discovery_knowledge_contracts_u23 as c23
import processors.discovery_event_ledger_u23 as l23
import processors.discovery_framegraph_projection_u23 as p23
import processors.discovery_anchor_content_recovery_u25 as rec
import processors.discovery_benchmark_decontamination_u25 as lab

def ck(n,x,d=""):
    if not x:raise AssertionError(n+" "+d)
    print(n+": PASS"+(" | "+d if d else ""))

class MockResponses:
    def create(self,model,input):
        import re,json
        m=re.search(r"Items=(\[.*\])$",input,re.S);items=json.loads(m.group(1));out=[]
        for x in items:
            t=x["text"].lower()
            if "wait" in t or "slow" in t:f,mech="DELAY","LATENCY"
            elif "crash" in t:f,mech="CRASH_FREEZE","RUNTIME_INSTABILITY"
            elif "state" in t:f,mech="STATE_LOSS","STATE_PERSISTENCE_FAILURE"
            else:f,mech="WORKFLOW_FRICTION","UNKNOWN"
            out.append({"id":x["id"],"workflow":"software workflow","friction":f,"mechanism":mech,
              "constraint":"UNKNOWN","consequence":"time loss","response":"UNKNOWN","emergent_frame":f})
        return type("R",(),{"output_text":json.dumps({"items":out})})()
class MockClient:
    def __init__(self):self.responses=MockResponses()

class BrokenSchemaIntrospection:
    def execute(self,sql,*args,**kwargs):
        if sql.strip().upper().startswith("SELECT *") and "LIMIT 0" in sql.upper():
            raise sqlite3.DatabaseError("simulated cursor failure")
        if sql.strip().upper().startswith("PRAGMA"):
            raise sqlite3.DatabaseError("simulated pragma failure")
        raise sqlite3.DatabaseError("unexpected query")

rk,rd=rec._resolve_key_column(BrokenSchemaIntrospection(),
    {"table":"items","columns":["doc_key","payload"]})
ck("U25_1_LOCATOR_COLUMN_FALLBACK",rk=="doc_key" and rd["resolved_from"]=="LOCATOR_COLUMNS",str(rd))

with tempfile.TemporaryDirectory() as td:
    root=Path(td);rt=root/".radar_runtime";rt.mkdir()
    raw=rt/"opportunity_observation_cache_v3.sqlite3"
    con=sqlite3.connect(raw);con.execute("CREATE TABLE items(doc_key TEXT PRIMARY KEY,payload TEXT)")
    events=[];sigs=["SLOW_DELAY","CRASH_FREEZE","STATE_LOSS","ACCESS_UNAVAILABLE","PROCESSING_DELAY","SYNC_FAILURE"]
    for sig in sigs:
      for j in range(5):
        oid=f"{sig}-{j}"
        content={
          "SLOW_DELAY":f"Users wait too long for the application response during normal work case {j}",
          "PROCESSING_DELAY":f"Batch processing finishes late and delays downstream work case {j}",
          "CRASH_FREEZE":f"The application crashes during editing and the session stops case {j}",
          "STATE_LOSS":f"Restarting loses unsaved state and prior context case {j}",
          "ACCESS_UNAVAILABLE":f"Users cannot open a permission protected workspace case {j}",
          "SYNC_FAILURE":f"Device synchronization fails and recent changes do not arrive case {j}",
        }[sig]
        payload={"primary_problem_signature":sig,"need_frame":{"problem":content,"version":"need-frame-v1"},
                 "source_type":"fixture","metadata":{"package_name":"package_name","padding":"x"*100}}
        con.execute("INSERT INTO items VALUES(?,?)",(oid,json.dumps(payload)))
        span=f"span-{oid}"
        # Reproduce U23 leakage: selected evidence span is explicit signature label.
        events.append(c23.make_event(event_type="EVIDENCE_SPAN_PROPOSED",stream_type="evidence_span",stream_id=span,
          producer="fixture",producer_version="1",producer_plane="INTERPRETATION",source_observation_key=oid,
          payload={"span_id":span,"text":sig,"basis_path":"primary_problem_signature","basis_class":"EXPLICIT_SIGNATURE",
                   "source":"fixture","locator":{},"valid_time_status":"UNKNOWN"}))
        events.append(c23.make_event(event_type="WEAK_ANCHOR_OBSERVED",stream_type="weak_anchor",stream_id=oid,
          producer="fixture",producer_version="1",producer_plane="INTERPRETATION",source_observation_key=oid,
          payload={"signature":sig,"label_status":"WEAK_LABEL_ONLY"}))
        events.append(c23.make_event(event_type="GRANULARITY_ROUTED",stream_type="observation",stream_id=oid,
          producer="fixture",producer_version="1",producer_plane="INTERPRETATION",source_observation_key=oid,
          payload={"route":"DIRECT_SIGNATURE_ANCHOR","reasons":["fixture"]}))
    # Negative fixture: only a label + metadata, must stay unrecovered.
    oid="ONLY-LABEL"
    con.execute("INSERT INTO items VALUES(?,?)",(oid,json.dumps({"primary_problem_signature":"QUALITY_LIMIT",
      "source_type":"fixture","metadata":{"padding":"x"*100}})))
    span="span-"+oid
    events.append(c23.make_event(event_type="EVIDENCE_SPAN_PROPOSED",stream_type="evidence_span",stream_id=span,
      producer="fixture",producer_version="1",producer_plane="INTERPRETATION",source_observation_key=oid,
      payload={"span_id":span,"text":"QUALITY_LIMIT","basis_path":"primary_problem_signature","basis_class":"EXPLICIT_SIGNATURE",
               "source":"fixture","locator":{},"valid_time_status":"UNKNOWN"}))
    events.append(c23.make_event(event_type="WEAK_ANCHOR_OBSERVED",stream_type="weak_anchor",stream_id=oid,
      producer="fixture",producer_version="1",producer_plane="INTERPRETATION",source_observation_key=oid,
      payload={"signature":"QUALITY_LIMIT","label_status":"WEAK_LABEL_ONLY"}))
    events.append(c23.make_event(event_type="GRANULARITY_ROUTED",stream_type="observation",stream_id=oid,
      producer="fixture",producer_version="1",producer_plane="INTERPRETATION",source_observation_key=oid,
      payload={"route":"DIRECT_SIGNATURE_ANCHOR","reasons":["fixture"]}))
    con.commit();con.close()
    l23.append_events(root,events);p23.rebuild(root)

    (rt/"discovery_knowledge_foundation_u23.json").write_text(json.dumps({
      "source_cache":{"path":str(raw),"unchanged":True},
      "status":"PASS_SHADOW_FOUNDATION"
    }),encoding="utf-8")

    resolved=rec.locate_raw_cache(root)
    ck("U25_2_RAW_SOURCE_LOCK",Path(resolved["path"]).resolve()==raw.resolve()
       and resolved["table"]=="items" and resolved["locator_source"]=="U23_LIVE_STATE",str(resolved))

    selection={"path":str(raw),"table":"items","rows":31,"columns":["doc_key","payload"],
               "locator_source":"INJECTED_FIXTURE"}

    rows,d=rec.recover(root,selection)
    ck("U25_LEGACY_LEAK_DETECTED",d["legacy_label_leak_observations"]==31,str(d))
    ck("U25_SIGNATURE_EXCLUDED_FROM_CONTENT",d["recovered_label_leak_observations"]==0)
    ck("U25_NONLABEL_CONTENT_RECOVERED",d["recovered_content"]==30,str(d["selected_path_distribution"]))
    ck("U25_LABEL_ONLY_FAILS_CLOSED",d["unrecovered"]==1,str(d["unrecovered_examples"]))
    ck("U25_CONTENT_PATH_NOT_SIGNATURE",all(r["content_path"]!="primary_problem_signature" for r in rows))
    ck("U25_1_STABLE_KEY_RESOLVED",d["key_resolution"]["resolved_key_column"]=="doc_key",str(d["key_resolution"]))
    decoy=rec._inspect_candidate(rt/"discovery_knowledge_events_v1.sqlite3")
    ck("U25_2_EVENTS_DB_REJECTED_AS_RAW_SOURCE",decoy is None)

    r=lab.run(root,client_factory=lambda:MockClient(),raw_selection=selection)
    ck("U25_END_TO_END_PASS",r["status"]=="PASS_BENCHMARK_DECONTAMINATION",r["status"])
    ck("U25_U24_PROXY_INVALIDATED",r["benchmark_lineage"]["U24_WEAK_LABEL_PROXY"]=="INVALIDATED_FOR_MODEL_COMPARISON")
    ck("U25_R0_DECONTAMINATED",r["arm_metrics"]["R0_RAW_CONTENT"]["status"]=="READY_DECONTAMINATED")
    ck("U25_R3_BOUNDED",r["llm_shadow"]["diagnostics"]["calls"]<=2)
    ck("U25_NO_WINNER",r["decision"]["winner"] is None and r["authority"]["promotion_allowed_from_u25"] is False)
    print("U25_LOCAL_ACCEPTANCE_ALL_PASS",r["engine_version"])
