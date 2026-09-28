import json,os,tempfile
from pathlib import Path
import processors.thesis_conditioned_evidence_u18 as u18
from processors.founder_thesis_research_control_u14 import Store,GapType

def ck(n,c,d=""):
    if not c:raise AssertionError(n+" "+d)
    print(n+": PASS"+(" | "+d if d else ""))

with tempfile.TemporaryDirectory() as td:
    root=Path(td)
    old_state,old17,old16=u18.STATE,u18.U17_STATE,u18.U16_STATE
    try:
        u18.STATE=root/"u18.json";u18.U17_STATE=root/"u17.json";u18.U16_STATE=root/"u16.json"
        s=Store(root/"u14.json")
        card={"id":"userinnovation_test","type":"USER_INNOVATION_NEED_SOLUTION_SIGNAL",
              "best_next_evidence":{"next_steps":[
                {"evidence":"INDEPENDENT_NEED_RECURRENCE","query":"privacy constraint format slides papers"},
                {"evidence":"CURRENT_SOLUTION_SUPPLY","query":"format slides papers local llms"},
                {"evidence":"PEER_ADOPTION_OR_DIFFUSION","query":"format slides papers local llms"},
                {"evidence":"PAYMENT_BEHAVIOR","query":None}]}}
        t=s.register_card(card);s.attach_plan(t.thesis_id,card["best_next_evidence"])
        ctx=u18.build_thesis_context(s,t.thesis_id)
        ck("U18_THESIS_CONTEXT_HAS_SUBJECT",ctx["quality"]=="PASS" and len(ctx["subject_terms"])>=2,str(ctx))
        ck("U18_GENERIC_PAYMENT_QUERY_REJECTED",not u18.query_contract("payment_behavior",ctx)["pass"])
        pq=u18.query_family(GapType.PAYMENT_BEHAVIOR.value,ctx)[0]
        ck("U18_PAYMENT_QUERY_IS_THESIS_CONDITIONED",u18.query_contract(pq,ctx)["pass"],pq)

        pay=s.gap(t.thesis_id,GapType.PAYMENT_BEHAVIOR.value)
        pay.confirmed_support_groups=["generic:1"];pay.adjudicated=2;pay.related_or_insufficient=1;s._persist()
        badq={
          "q1":{"queue_id":"q1","status":"CONFIRMED_SUPPORT","judgment":"CONFIRMED_SUPPORT","task_id":"x",
                "card_id":card["id"],"thesis_id":t.thesis_id,"gap_id":pay.gap_id,"gap":GapType.PAYMENT_BEHAVIOR.value,
                "query":"payment_behavior","source_group":"generic:1","evidence_id":"e1","text":"I pay for cloud hosting"},
          "q2":{"queue_id":"q2","status":"RELATED_BUT_NOT_EVIDENCE","judgment":"RELATED_BUT_NOT_EVIDENCE","task_id":"x",
                "card_id":card["id"],"thesis_id":t.thesis_id,"gap_id":pay.gap_id,"gap":GapType.PAYMENT_BEHAVIOR.value,
                "query":"payment_behavior","source_group":"generic:2","evidence_id":"e2","text":"payment discussion"},
        }
        u18._atomic(u18.U17_STATE,{"queue":badq})
        q=u18.quarantine_context_invalid_u17(s)
        ck("U18_TAINTED_PAYMENT_SUPPORT_REVOKED",q["support_revoked"]==1 and pay.confirmed==0,str(q))
        ck("U18_TAINTED_NEGATIVE_ALSO_REVOKED",pay.related_or_insufficient==0 and pay.adjudicated==0)

        # Recreate one valid pending item and require dual thesis+gap match.
        validq=u18.query_family(GapType.INDEPENDENT_NEED_RECURRENCE.value,ctx)[0]
        rec=s.gap(t.thesis_id,GapType.INDEPENDENT_NEED_RECURRENCE.value)
        u18._atomic(u18.U17_STATE,{"queue":{
          "r1":{"queue_id":"r1","status":"PENDING","task_id":"r","card_id":card["id"],"thesis_id":t.thesis_id,
                "gap_id":rec.gap_id,"gap":GapType.INDEPENDENT_NEED_RECURRENCE.value,"query":validq,
                "source_group":"user:alice","evidence_id":"e3",
                "text":"I repeatedly spend hours turning research papers into presentation slides because formatting is painful."}
        }})
        class FV:
            available=True;calls=0;max_calls=3
            def adjudicate(self,gap,ctx,items):
                self.calls+=1
                return {x["candidate_id"]:{"thesis_match":"MATCH","gap_judgment":"CONFIRMED_SUPPORT","rationale":"same workflow and recurring pain"} for x in items}
        fv=FV()
        a=u18.adjudicate_valid_u17_pending(s,fv)
        ck("U18_DUAL_MATCH_CAN_CONFIRM",a["resolved"]==1 and rec.confirmed==1,str(a))

        # Explicit test: thesis mismatch must never become support even if gap judgment says support.
        item={"candidate_id":"m1","source_group":"user:x","text":"I pay monthly for database hosting"}
        before=pay.confirmed
        final=u18._apply(s,pay,item,{"thesis_match":"MISMATCH","gap_judgment":"CONFIRMED_SUPPORT","rationale":"wrong thesis"})
        ck("U18_THESIS_MISMATCH_BLOCKS_SUPPORT",final=="THESIS_MISMATCH" and pay.confirmed==before)

        # Capacity planner: no new retrieval when verifier has no calls left.
        class Full:
            available=True;calls=3;max_calls=3
        sel=u18.select_next(s,Full())
        ck("U18_VERIFIER_CAPACITY_BACKPRESSURE",sel is None)

        # Query generation for every gap must satisfy the thesis contract.
        all_ok=True
        for gt in GapType:
            for query in u18.query_family(gt.value,ctx):
                all_ok=all_ok and u18.query_contract(query,ctx)["pass"]
        ck("U18_ALL_GENERATED_QUERIES_CONTEXT_BOUND",all_ok)

        # U16 overlay reconciliation clears stale pending when U17 has no pending.
        u18._atomic(u18.U16_STATE,{"gap_overlays":{rec.gap_id:{
            "verification_pending_count":1,"last_outcome":"VERIFICATION_PENDING","research_state":"WAITING_FOR_VERIFICATION"
        }}})
        d=json.loads(u18.U17_STATE.read_text(encoding="utf-8"));d["queue"]["r1"]["status"]="CONFIRMED_SUPPORT";u18._atomic(u18.U17_STATE,d)
        rr=u18.reconcile_u16_overlays(s)
        d16=json.loads(u18.U16_STATE.read_text(encoding="utf-8"))
        ck("U18_STALE_PENDING_RECONCILED",d16["gap_overlays"][rec.gap_id]["verification_pending_count"]==0,str(rr))
        print("U18_LOCAL_ACCEPTANCE_ALL_PASS",u18.ENGINE_VERSION)
    finally:
        u18.STATE=old_state;u18.U17_STATE=old17;u18.U16_STATE=old16
