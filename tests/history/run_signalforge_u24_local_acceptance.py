import json,sqlite3,tempfile,os
from pathlib import Path
import numpy as np

import processors.discovery_knowledge_contracts_u23 as c23
import processors.discovery_event_ledger_u23 as l23
import processors.discovery_framegraph_projection_u23 as p23
import processors.discovery_representation_arms_u24 as arms
import processors.discovery_anchor_audit_u24 as aa
import processors.discovery_representation_lab_u24 as lab

def ck(n,x,d=""):
    if not x:raise AssertionError(n+" "+d)
    print(n+": PASS"+(" | "+d if d else ""))

class MockResponses:
    def create(self,model,input):
        import re,json
        m=re.search(r"Items=(\[.*\])$",input,re.S)
        items=json.loads(m.group(1))
        out=[]
        for x in items:
            text=x["text"].lower()
            if "slow" in text or "delay" in text:
                f="DELAY";mech="LATENCY"
            elif "crash" in text or "freeze" in text:
                f="CRASH_FREEZE";mech="RUNTIME_INSTABILITY"
            elif "state" in text:
                f="STATE_LOSS";mech="STATE_PERSISTENCE_FAILURE"
            else:
                f="WORKFLOW_FRICTION";mech="UNKNOWN"
            out.append({"id":x["id"],"workflow":"software workflow","friction":f,"mechanism":mech,
                        "constraint":"UNKNOWN","consequence":"time loss","response":"UNKNOWN","emergent_frame":f})
        return type("R",(),{"output_text":json.dumps({"items":out})})()
class MockClient:
    def __init__(self):self.responses=MockResponses()

with tempfile.TemporaryDirectory() as td:
    root=Path(td);(root/".radar_runtime").mkdir()
    # Build U23-style event foundation directly.
    events=[]
    sigs=["SLOW_DELAY","CRASH_FREEZE","STATE_LOSS","ACCESS_UNAVAILABLE","PROCESSING_DELAY","SYNC_FAILURE"]
    for gi,sig in enumerate(sigs):
        for j in range(8):
            oid=f"{sig}-{j}"
            text={
              "SLOW_DELAY":f"Application is slow and users wait for response {j}",
              "PROCESSING_DELAY":f"Processing jobs take a long time and finish late {j}",
              "CRASH_FREEZE":f"Application crashes and freezes during work {j}",
              "STATE_LOSS":f"Application loses state and context after restart {j}",
              "ACCESS_UNAVAILABLE":f"Users cannot access login or permission protected page {j}",
              "SYNC_FAILURE":f"Synchronization fails between devices and data is not updated {j}",
            }[sig]
            span=f"span-{oid}"
            events.append(c23.make_event(event_type="EVIDENCE_SPAN_PROPOSED",stream_type="evidence_span",stream_id=span,
                producer="fixture",producer_version="1",producer_plane="INTERPRETATION",source_observation_key=oid,
                payload={"span_id":span,"text":text,"basis_path":"primary_problem_signature","basis_class":"EXPLICIT_SIGNATURE",
                         "source":"fixture","locator":{},"valid_time_status":"UNKNOWN"}))
            events.append(c23.make_event(event_type="WEAK_ANCHOR_OBSERVED",stream_type="weak_anchor",stream_id=oid,
                producer="fixture",producer_version="1",producer_plane="INTERPRETATION",source_observation_key=oid,
                payload={"signature":sig,"label_status":"WEAK_LABEL_ONLY"}))
            events.append(c23.make_event(event_type="GRANULARITY_ROUTED",stream_type="observation",stream_id=oid,
                producer="fixture",producer_version="1",producer_plane="INTERPRETATION",source_observation_key=oid,
                payload={"route":"DIRECT_SIGNATURE_ANCHOR","reasons":["fixture"]}))
    # add composites
    for j in range(18):
        oid=f"COMPOSITE-{j}";span=f"span-{oid}"
        events.append(c23.make_event(event_type="EVIDENCE_SPAN_PROPOSED",stream_type="evidence_span",stream_id=span,
          producer="fixture",producer_version="1",producer_plane="INTERPRETATION",source_observation_key=oid,
          payload={"span_id":span,"text":f"Users manually copy data and wait for review because integration is unavailable {j}",
                   "basis_path":"evidence_atom.text","basis_class":"FALLBACK_TEXT","source":"fixture","locator":{},"valid_time_status":"UNKNOWN"}))
        events.append(c23.make_event(event_type="GRANULARITY_ROUTED",stream_type="observation",stream_id=oid,
          producer="fixture",producer_version="1",producer_plane="INTERPRETATION",source_observation_key=oid,
          payload={"route":"COMPOSITE_CANDIDATE","reasons":["fixture"]}))
    l23.append_events(root,events);p23.rebuild(root)

    r=lab.run(root,client_factory=lambda:MockClient())
    ck("U24_END_TO_END_PASS",r["status"]=="PASS_SHADOW_REPRESENTATION_AUDIT",r["status"])
    ck("U24_ANCHOR_GROUPS_AUDITED",r["corpus"]["distinct_weak_signature_groups"]==6)
    parts=r["anchor_audit"]["partitions"]["groups"]
    ck("U24_BALANCED_GROUP_PARTITIONS",all(len(parts[k])>=1 for k in parts),str(parts))
    ck("U24_R0_READY",r["arm_metrics"]["R0_RAW_TEXT"]["status"]=="READY")
    ck("U24_R1_READY",r["arm_metrics"]["R1_SALIENT_CODE"]["status"]=="READY")
    ck("U24_R2_READY",r["arm_metrics"]["R2_FIXED_ATOMS"]["status"]=="READY")
    ck("U24_R3_BOUNDED_READY",r["arm_metrics"]["R3_HYBRID_FRAME"]["status"]=="READY_SHADOW_SAMPLE")
    ck("U24_R4_NO_EXTRA_LLM",r["llm_shadow"]["diagnostics"]["calls"]<=2)
    ck("U24_NO_WINNER",r["decision"]["winner"] is None and r["authority"]["promotion_allowed_from_u24"] is False)
    ck("U24_PROVIDER_AUTHORITY_ZERO",r["authority"]["production_authority"]==0)

    # R2 must preserve unknown rather than hallucinate facets.
    txt=arms.fixed_atom_text("A completely unfamiliar neutral statement")
    ck("U24_R2_UNKNOWN_PRESERVED","UNKNOWN" in txt,txt)
    print("U24_LOCAL_ACCEPTANCE_ALL_PASS",r["engine_version"])
