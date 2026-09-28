import json,sqlite3,tempfile
from pathlib import Path
import processors.discovery_coverage_u19 as u19

def ck(n,c,d=""):
    if not c:raise AssertionError(n+" "+d)
    print(n+": PASS"+(" | "+d if d else ""))

with tempfile.TemporaryDirectory() as td:
    root=Path(td);rt=root/".radar_runtime";rt.mkdir()
    db=rt/"observation_cache.sqlite"
    con=sqlite3.connect(db)
    con.execute("CREATE TABLE observations (cache_key TEXT PRIMARY KEY, payload TEXT)")
    rows=[]
    # Synthetic chronological corpus: common families recur; rare families appear once/twice;
    # later blocks include genuinely novel families so holdout calibration has something to test.
    idx=0
    for block in range(12):
        for j in range(100):
            if j<55:
                fam=f"workflow manual reentry shared system family{j%5}"
            elif j<85:
                fam=f"paper slides formatting privacy issue pattern{j%7}"
            elif j<95:
                fam=f"rare integration bottleneck block{block%4} item{j}"
            else:
                fam=f"novel family block{block} item{j%5}"
            payload={
                "need_statement":fam,
                "source_type":"hackernews" if j%2 else "github_issues",
                "created_at":1700000000+idx*60,
                "url":"https://example.com/"+str(idx)
            }
            rows.append((str(idx),json.dumps(payload)))
            idx+=1
    con.executemany("INSERT INTO observations VALUES (?,?)",rows);con.commit();con.close()

    loc=u19.locate_observation_table(root)
    ck("U19_SQLITE_CACHE_DISCOVERED",loc["status"]=="FOUND",str(loc.get("selected")))
    raw,q=u19.read_records(loc["selected"])
    ck("U19_SEMANTIC_EXTRACTION",len(raw)>=1000,str(q))
    fam,meta=u19.assign_families(raw)
    ck("U19_FAMILY_ASSIGNMENT",len(fam)>=1000 and meta["families"]>5,str(meta["families"]))
    m=u19.coverage_metrics(fam)
    ck("U19_GOOD_TURING_PROXY_BOUNDED",0<=m["good_turing_unseen_mass_proxy"]<=1,str(m))
    ck("U19_CHAO2_LOWER_BOUND_NOT_BELOW_OBSERVED",
       m["chao2_lower_bound_proxy"] is None or m["chao2_lower_bound_proxy"]>=m["observed_families"])
    bt=u19.backtest(fam)
    ck("U19_HOLDOUT_BACKTEST_EXISTS",bt["status"]=="PASS" and len(bt["points"])>=3,str(bt))
    dec=u19.decision(m,bt,u19.source_metrics(fam))
    ck("U19_BUDGET_REQUIRES_CALIBRATION",
       dec["eligible_for_exploration_budget_control"]==(bt.get("calibration")=="DIRECTIONALLY_SUPPORTED"))
    r=u19.analyze(root)
    ck("U19_END_TO_END_ANALYSIS_PASS",r["status"]=="PASS")
    ck("U19_POLICY_PERSISTED",(root/u19.POLICY).exists())
    ck("U19_TRUTH_BOUNDARY_EXPLICIT","NOT_MARKET" in u19.TRUTH_BOUNDARY or "NOT MARKET" in u19.TRUTH_BOUNDARY)
    # Negative: no DB must fail closed, not invent coverage.
    empty=root/"empty";(empty/".radar_runtime").mkdir(parents=True)
    r2=u19.analyze(empty)
    ck("U19_NO_CACHE_FAILS_CLOSED",r2["status"]=="NO_OBSERVATION_SQLITE")
    print("U19_LOCAL_ACCEPTANCE_ALL_PASS",u19.ENGINE_VERSION)
