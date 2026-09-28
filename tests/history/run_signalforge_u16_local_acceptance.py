import json,tempfile
from pathlib import Path
import processors.founder_research_resilience_u16 as u16
from processors.founder_thesis_research_control_u14 import Store,GapType

def ck(n,c,d=""):
    if not c:raise AssertionError(n+" "+d)
    print(n+": PASS"+(" | "+d if d else ""))

with tempfile.TemporaryDirectory() as td:
    old_state,old_u15=u16.STATE,u16.U15_STATE
    try:
        u16.STATE=Path(td)/"u16.json";u16.U15_STATE=Path(td)/"u15.json"
        s=Store(Path(td)/"u14.json")
        card={"id":"userinnovation_test","type":"USER_INNOVATION_NEED_SOLUTION_SIGNAL",
              "best_next_evidence":{"next_steps":[
                {"evidence":"INDEPENDENT_NEED_RECURRENCE","query":"research privacy constraint format slides papers"},
                {"evidence":"CURRENT_SOLUTION_SUPPLY","query":"research format slides papers local llms"},
                {"evidence":"PEER_ADOPTION_OR_DIFFUSION","query":"research format slides papers local llms"},
                {"evidence":"PAYMENT_BEHAVIOR","query":None}]}}
        t=s.register_card(card);s.attach_plan(t.thesis_id,card["best_next_evidence"])
        rec=s.gap(t.thesis_id,GapType.INDEPENDENT_NEED_RECURRENCE.value)
        dif=s.gap(t.thesis_id,GapType.PEER_ADOPTION_OR_DIFFUSION.value)
        sup=s.gap(t.thesis_id,GapType.CURRENT_SOLUTION_SUPPLY.value)
        # emulate U15 wrong states
        rec.attempts=1;rec.zero_confirmed_yield_streak=1;rec.state="STOP_LOW_MARGINAL_VALUE"
        dif.attempts=1;dif.zero_confirmed_yield_streak=1;dif.state="STOP_LOW_MARGINAL_VALUE"
        s._persist()
        u15={
          "engine_version":"signalforge-founder-directed-acquisition-u15-v1","cycle":1,
          "founder_requests_total":3,"exploration_requests_total":0,
          "requests":[
            {"request_id":"r0","gap_id":rec.gap_id,"candidate_count":0,"judgments":{},"confirmed_count":0,
             "query":"privacy constraint format slides papers","adapter":"hackernews_search"},
            {"request_id":"r1","gap_id":sup.gap_id,"candidate_count":3,
             "judgments":{"a":{"judgment":"CONFIRMED_SUPPORT"}},"confirmed_count":3,
             "query":"format slides papers","adapter":"github_search"},
            {"request_id":"r2","gap_id":dif.gap_id,"candidate_count":5,"judgments":{},"confirmed_count":0,
             "query":"format slides papers","adapter":"github_search"},
          ],"query_history":[]
        }
        u16._atomic_json(u16.U15_STATE,u15)
        mig=u16.migrate_u15_semantics(s)
        ck("U16_RETRIEVAL_EMPTY_RECLASSIFIED",mig["retrieval_empty_reclassified"]==1)
        ck("U16_VERIFICATION_PENDING_RECLASSIFIED",mig["verification_pending_reclassified"]==1)
        ck("U16_U15_FALSE_STOP_REPAIRED",rec.zero_confirmed_yield_streak==0 and dif.zero_confirmed_yield_streak==0)
        state=u16._load_state()
        ck("U16_RETRIEVAL_EMPTY_RETAINS_POSITIVE_VOI",u16.resilient_voi(s,rec,state)>0,str(u16.resilient_voi(s,rec,state)))

        # dependency-aware surface must not recommend payment before recurrence.
        p=u16.dependency_aware_card_progress(s,card["id"])
        pay=next(x for x in p["gap_progress"] if x["gap"]==GapType.PAYMENT_BEHAVIOR.value)
        ck("U16_PAYMENT_BLOCKED_BY_RECURRENCE",pay["marginal_voi"]==0 and "WAITING_FOR_INDEPENDENT" in pay["research_state"],pay["research_state"])

        # fetch: first recurrence strategy empty, second returns one candidate.
        calls=[]
        def fake_fetch(adapter,q,limit):
            calls.append((adapter,q))
            if len(calls)==1:return []
            if adapter in {"stackexchange","hackernews_relevance","github_issues","hackernews_recent"}:
                return [{"evidence_id":"ev1","source_ref":"x","source_group":"user:alice",
                         "text":"I repeatedly spend hours preparing presentations from research papers.","meta":{}}]
            return [{"evidence_id":"gh:1","source_ref":"g","source_group":"github_repo:a/paper-slides",
                     "text":"paper slides research presentation","meta":{"stars":10,"forks":2,"archived":False}}]
        class V:
            calls=0
            def verify(self,gap,q,cands):
                self.calls+=1
                if gap==GapType.INDEPENDENT_NEED_RECURRENCE.value:
                    return {"ev1":{"judgment":"CONFIRMED_SUPPORT","rationale":"strict firsthand recurrence"}}
                return {}
        ex=u16.ResilientExecutor(fetch_fn=fake_fetch,verifier=V())
        state=u16._load_state()
        task=ex.run_task(s,state,card["id"],t.thesis_id,rec,max_fetch_attempts=2)
        ck("U16_ZERO_RESULT_TRIGGERS_REFORMULATION",len(task["fetch_attempts"])==2,str(task["fetch_attempts"]))
        ck("U16_SECOND_STRATEGY_CAN_CONFIRM",task["stats"]["confirmed"]==1)
        ck("U16_EXACT_CANDIDATE_ATTRIBUTION",task["candidate_ids"]==["ev1"])
        ck("U16_RETRIEVAL_EMPTY_DID_NOT_COUNT_VERIFIED_NEGATIVE",
           u16._load_state()["gap_overlays"][rec.gap_id]["verified_no_support_count"]==0)

        # diffusion verification must use adoption metadata, not repo existence alone.
        cands=[
          {"evidence_id":"gh:a","source_group":"repo:a","text":"paper slides research presentation","meta":{"stars":8,"forks":2}},
          {"evidence_id":"gh:b","source_group":"repo:b","text":"paper slides research presentation","meta":{"stars":0,"forks":0}},
        ]
        gv=u16.GapVerifier(max_calls=0)
        j=gv.verify(GapType.PEER_ADOPTION_OR_DIFFUSION.value,"paper slides research",cands)
        ck("U16_DIFFUSION_REQUIRES_ADOPTION_SIGNAL",j["gh:a"]["judgment"]=="CONFIRMED_SUPPORT" and j["gh:b"]["judgment"]!="CONFIRMED_SUPPORT")

        # after recurrence + supply exist, payment may become eligible.
        sup.confirmed_support_groups=["repo:supply"];s._persist()
        p2=u16.dependency_aware_card_progress(s,card["id"])
        pay2=next(x for x in p2["gap_progress"] if x["gap"]==GapType.PAYMENT_BEHAVIOR.value)
        ck("U16_PAYMENT_UNLOCKS_ONLY_AFTER_PREREQS",pay2["prerequisite"]=="READY")

        # persistence and budget state.
        u16.finish_cycle(False)
        ck("U16_STATE_PERSISTS",u16.STATE.exists())
        print("U16_LOCAL_ACCEPTANCE_ALL_PASS",u16.ENGINE_VERSION)
    finally:
        u16.STATE=old_state;u16.U15_STATE=old_u15
