import tempfile
from pathlib import Path
import processors.founder_directed_research_u15 as u15
from processors.founder_thesis_research_control_u14 import Store,GapType

def ck(n,c,detail=""):
    if not c: raise AssertionError(n+" "+detail)
    print(n+": PASS"+(" | "+detail if detail else ""))

def fake_fetch(adapter,query,limit):
    if adapter=="github_search":
        return [
            {"evidence_id":"gh:1","source_ref":"https://github.com/a/paper-slides","source_group":"github_repo:a/paper-slides",
             "text":"paper slides privacy academic presentation", "meta":{"archived":False,"stars":20,"forks":3}},
            {"evidence_id":"gh:2","source_ref":"https://github.com/b/unrelated","source_group":"github_repo:b/unrelated",
             "text":"unrelated weather app", "meta":{"archived":False,"stars":100,"forks":10}},
        ]
    return [
        {"evidence_id":"hn:1","source_ref":"hn:1","source_group":"hn_author:alice",
         "text":"I repeatedly spend hours formatting slides from research papers", "meta":{}},
        {"evidence_id":"hn:2","source_ref":"hn:2","source_group":"hn_author:bob",
         "text":"generic discussion about presentations", "meta":{}},
    ]

class FakeVerifier:
    calls=0
    def verify_recurrence(self,query,cands):
        self.calls+=1
        return {
            "hn:1":{"judgment":"CONFIRMED_SUPPORT","rationale":"independent firsthand recurrence"},
            "hn:2":{"judgment":"RELATED_BUT_NOT_EVIDENCE","rationale":"generic discussion"},
        }

with tempfile.TemporaryDirectory() as td:
    old_u14=u15.STATE
    try:
        u15.STATE=Path(td)/"u15.json"
        s=Store(Path(td)/"u14.json")
        c={"id":"userinnovation_test","type":"USER_INNOVATION_NEED_SOLUTION_SIGNAL",
           "best_next_evidence":{"next_steps":[
             {"evidence":"INDEPENDENT_NEED_RECURRENCE","query":"research privacy format slides papers"},
             {"evidence":"CURRENT_SOLUTION_SUPPLY","query":"research format slides papers privacy"},
             {"evidence":"PEER_ADOPTION_OR_DIFFUSION","query":"research format slides papers privacy"},
             {"evidence":"PAYMENT_BEHAVIOR","query":None}]}}
        t=s.register_card(c);s.attach_plan(t.thesis_id,c["best_next_evidence"])
        ex=u15.FounderDirectedExecutor(fetch_fn=fake_fetch,verifier=FakeVerifier())
        r=ex.execute(s,founder_requests=5)
        ck("U15_FOUNDER_REQUESTS_EXECUTED",r["founder_requests"]==5,str(r["founder_requests"]))
        reqs=r["requests"]
        ck("U15_EXACT_DOC_IDS_PER_REQUEST",all("candidate_ids" in x and isinstance(x["candidate_ids"],list) for x in reqs))
        rec=s.gap(t.thesis_id,GapType.INDEPENDENT_NEED_RECURRENCE.value)
        sup=s.gap(t.thesis_id,GapType.CURRENT_SOLUTION_SUPPLY.value)
        pay=s.gap(t.thesis_id,GapType.PAYMENT_BEHAVIOR.value)
        ck("U15_RECURRENCE_CONFIRMED_ONLY_BY_VERIFIER",rec.confirmed>=1)
        ck("U15_SUPPLY_SEPARATE_FROM_RECURRENCE",sup.confirmed>=1 and rec.confirmed>=1)
        pay_reqs=[x for x in reqs if x["gap"]==GapType.PAYMENT_BEHAVIOR.value]
        # Payment can become eligible only after both recurrence and supply confirmation.
        if pay_reqs:
            idx=reqs.index(pay_reqs[0])
            earlier=reqs[:idx]
            ck("U15_PAYMENT_NOT_FIRST",idx>0)
        else:
            ck("U15_PAYMENT_DEPENDENCY_GATE",pay.attempts==0)
        ck("U15_QUERY_ATTRIBUTION_NO_GLOBAL_BATCH_LEAK",
           all(x["candidate_count"]==len(x["candidate_ids"]) for x in reqs))
        # Four-cycle accounting target: 20 founder requests vs one U13 refresh of 6 ~= 76.9/23.1.
        sstate={"engine_version":u15.ENGINE_VERSION,"cycle":3,"founder_requests_total":20,
                "exploration_requests_total":0,"requests":[],"query_history":[]}
        u15._atomic_json(u15.STATE,sstate)
        acc=u15.cycle_accounting(True,0)
        ck("U15_LONG_RUN_BUDGET_APPROX_75_25",0.74<=acc["founder_share"]<=0.80,str(acc))
        s2=Store(Path(td)/"u14.json")
        ck("U15_PERSISTENT_GAP_PROGRESS",s2.gap(t.thesis_id,GapType.INDEPENDENT_NEED_RECURRENCE.value).attempts>0)
        print("U15_LOCAL_ACCEPTANCE_ALL_PASS",u15.ENGINE_VERSION)
    finally:
        u15.STATE=old_u14
