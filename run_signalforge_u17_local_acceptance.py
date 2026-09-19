import json,os,tempfile
from pathlib import Path
import processors.evidence_adjudication_u17 as u17
from processors.founder_thesis_research_control_u14 import Store,GapType

def ck(n,c,d=""):
    if not c:raise AssertionError(n+" "+d)
    print(n+": PASS"+(" | "+d if d else ""))

with tempfile.TemporaryDirectory() as td:
    old_state,old_u16=u17.STATE,u17.U16_STATE
    old_key=os.environ.pop("OPENAI_API_KEY",None)
    try:
        root=Path(td);u17.STATE=root/"u17.json";u17.U16_STATE=root/"u16.json"
        (root/".env").write_text("OPENAI_API_KEY=test-key-from-dotenv\n",encoding="utf-8")
        env=u17.load_project_env(root)
        ck("U17_DOTENV_LOADS_VERIFIER_KEY",env["openai_key_after"] is True,env["method"])

        s=Store(root/"u14.json")
        card={"id":"userinnovation_test","type":"USER_INNOVATION_NEED_SOLUTION_SIGNAL",
              "best_next_evidence":{"next_steps":[
                {"evidence":"INDEPENDENT_NEED_RECURRENCE","query":"privacy slides papers"},
                {"evidence":"CURRENT_SOLUTION_SUPPLY","query":"slides papers software"},
                {"evidence":"PEER_ADOPTION_OR_DIFFUSION","query":"slides papers adoption"},
                {"evidence":"PAYMENT_BEHAVIOR","query":None}]}}
        t=s.register_card(card);s.attach_plan(t.thesis_id,card["best_next_evidence"])
        rec=s.gap(t.thesis_id,GapType.INDEPENDENT_NEED_RECURRENCE.value)
        sup=s.gap(t.thesis_id,GapType.CURRENT_SOLUTION_SUPPLY.value)
        sup.confirmed_support_groups=["repo:supply"];s._persist()

        task={
          "task_id":"u16pending1","card_id":card["id"],"thesis_id":t.thesis_id,"gap_id":rec.gap_id,
          "gap":GapType.INDEPENDENT_NEED_RECURRENCE.value,
          "fetch_attempts":[{"query":"privacy slides papers","adapter":"github_issues"}],
          "candidate_ids":["ghi:1","ghi:2"],"judgments":{},"outcome":"VERIFICATION_PENDING"
        }
        u17._atomic(u17.U16_STATE,{"tasks":[task]})
        def fake_fetch(adapter,q,limit):
            return [
              {"evidence_id":"ghi:1","source_ref":"x1","source_group":"user:alice",
               "text":"I repeatedly lose hours making slides from research papers.","meta":{}},
              {"evidence_id":"ghi:2","source_ref":"x2","source_group":"user:bob",
               "text":"Generic feature request for presentation software.","meta":{}},
            ]
        mig=u17.migrate_u16_pending(fake_fetch)
        ck("U17_PENDING_REHYDRATES_EXACT_IDS",mig["rehydrated"]==2 and mig["queue_added"]==2,str(mig))
        mig2=u17.migrate_u16_pending(fake_fetch)
        ck("U17_PENDING_MIGRATION_IDEMPOTENT",mig2["queue_added"]==0)

        class FakeVerifier:
            available=True;calls=0
            def adjudicate_group(self,gap,items):
                self.calls+=1
                out={}
                for x in items:
                    if x["evidence_id"]=="ghi:1":
                        out[x["queue_id"]]={"judgment":"CONFIRMED_SUPPORT","rationale":"independent firsthand recurrence"}
                    else:
                        out[x["queue_id"]]={"judgment":"RELATED_BUT_NOT_EVIDENCE","rationale":"adjacent only"}
                return out
        fv=FakeVerifier()
        adj=u17.adjudicate_pending(s,fv,max_groups=3)
        ck("U17_PENDING_FIRST_ADJUDICATES",adj["resolved"]==2 and adj["pending_after"]==0,str(adj))
        ck("U17_ADJUDICATION_UPDATES_GAP",rec.confirmed==1 and rec.adjudicated==2)

        # Pending backlog blocks new retrieval before adjudication.
        task2={**task,"task_id":"u16pending2","candidate_ids":["ghi:3"]}
        u17._atomic(u17.U16_STATE,{"tasks":[task,task2]})
        # Manually enqueue one new pending row.
        c3=[{"evidence_id":"ghi:3","source_ref":"x3","source_group":"user:carol",
             "text":"Same workflow is tedious for me too.","meta":{}}]
        u17.enqueue_from_task(task2,c3)
        p=u17.card_progress(s,card["id"])
        ck("U17_PENDING_FIRST_SURFACE",p["best_next_research"]["action"]=="ADJUDICATE_PENDING_EVIDENCE_FIRST")

        # If verifier is unavailable, recurrence retrieval is blocked rather than piled up.
        st=u17._load();st["provider"]={"status":"UNAVAILABLE","checked_at":0};u17._atomic(u17.STATE,st)
        sel=u17.select_new_retrieval(s,False)
        # Supply is already sufficient; payment may be eligible because recurrence confirmed. But recurrence itself must not be selected with pending.
        ck("U17_PENDING_GAP_NOT_SELECTED_WHEN_VERIFIER_UNAVAILABLE",
           sel is None or sel[2].gap_id!=rec.gap_id)

        # Provider failure preserves pending, no negative evidence mutation.
        class FailingVerifier:
            available=True;calls=0
            def adjudicate_group(self,gap,items):
                self.calls+=1
                return {"__error__":{"judgment":"ERROR","rationale":"provider down"}}
        before_confirmed=rec.confirmed
        bad=u17.adjudicate_pending(s,FailingVerifier(),max_groups=3)
        ck("U17_PROVIDER_FAILURE_PRESERVES_PENDING",bad["pending_after"]>=1)
        ck("U17_PROVIDER_FAILURE_NO_FALSE_NEGATIVE",rec.confirmed==before_confirmed)

        ck("U17_QUEUE_PERSISTS",u17.STATE.exists() and len(u17._load()["queue"])>=3)
        print("U17_LOCAL_ACCEPTANCE_ALL_PASS",u17.ENGINE_VERSION)
    finally:
        u17.STATE=old_state;u17.U16_STATE=old_u16
        if old_key is not None:os.environ["OPENAI_API_KEY"]=old_key
        else:os.environ.pop("OPENAI_API_KEY",None)
