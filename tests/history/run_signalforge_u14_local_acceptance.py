from processors.founder_thesis_research_control_u14 import Store,GapType,ENGINE_VERSION
import tempfile
from pathlib import Path

def ck(n,c):
    if not c: raise AssertionError(n)
    print(n+": PASS")

with tempfile.TemporaryDirectory() as td:
    s=Store(Path(td)/"state.json")
    c={"id":"userinnovation_3bdb1079d1cd66d3a6","type":"USER_INNOVATION_NEED_SOLUTION_SIGNAL",
       "best_next_evidence":{"next_steps":[
           {"evidence":"INDEPENDENT_NEED_RECURRENCE","query":"research privacy constraint format generate slides papers"},
           {"evidence":"CURRENT_SOLUTION_SUPPLY","query":"research format generate slides papers local llms"}]}}
    t=s.register_card(c);s.attach_plan(t.thesis_id,c["best_next_evidence"])
    p=s.card_progress(c["id"],0.08)
    ck("U14_CARD_PROGRESS_NONEMPTY",len(p["gap_progress"])==4)
    rows=[{"anchor_key":"frag_wrong","evidence_gap":"INDEPENDENT_NEED_RECURRENCE","attempts":1,
           "downstream_evidence_docs":20,"voi":{"expected_information_value":1.0}}]
    s.ingest_legacy_u13_rows_as_unverified(rows,[c])
    p2=s.card_progress(c["id"],0.08)
    rec=next(x for x in p2["gap_progress"] if x["gap"]=="INDEPENDENT_NEED_RECURRENCE")
    ck("U14_LEGACY_FRAGMENT_NOT_AUTO_ATTACHED",rec["retrieved_candidates"]==0 and rec["confirmed_independent_support"]==0)
    ck("U14_CANDIDATE_NOT_CONFIRMED",rec["confirmed_independent_support"]==0)
    ck("U14_PROSPECTIVE_VOI_BOUNDED",0<=rec["marginal_voi"]<1.0)
    ck("U14_FOUNDER_BUDGET_PRIORITY",s.budget(8,0.08)=={"founder_directed":6,"exploration":2})
    s2=Store(Path(td)/"state.json")
    ck("U14_PERSISTENCE_ROUNDTRIP",s2.card_map[c["id"]]==t.thesis_id)
    print("U14_LOCAL_ACCEPTANCE_ALL_PASS",ENGINE_VERSION)
