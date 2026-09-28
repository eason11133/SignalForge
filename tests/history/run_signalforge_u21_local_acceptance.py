import json,sqlite3,tempfile
from pathlib import Path
import processors.semantic_basis_contract_u21 as u21

def ck(n,c,d=""):
    if not c:raise AssertionError(n+" "+d)
    print(n+": PASS"+(" | "+d if d else ""))

# Direct adversarial field tests.
x=u21.classify_leaf("need_frame.version","need-frame-v1")
ck("U21_FRAME_VERSION_REJECTED",not x["eligible"] and x["reason"] in {"NEGATIVE_METADATA_PATH","VERSION_MARKER"},str(x))
x=u21.classify_leaf("source_type","source_type")
ck("U21_SOURCE_TYPE_PLACEHOLDER_REJECTED",not x["eligible"],str(x))
x=u21.classify_leaf("package_name","package_name")
ck("U21_PACKAGE_NAME_PLACEHOLDER_REJECTED",not x["eligible"],str(x))
x=u21.classify_leaf("problem_signature","SLOW_DELAY")
ck("U21_PROBLEM_SIGNATURE_ACCEPTED",x["eligible"],str(x))
x=u21.classify_leaf("need_frame.problem","Users repeatedly re-enter the same data across disconnected tools")
ck("U21_FRAME_PROBLEM_TEXT_ACCEPTED",x["eligible"],str(x))

with tempfile.TemporaryDirectory() as td:
    root=Path(td);rt=root/".radar_runtime";rt.mkdir()
    db=rt/"opportunity_observation_cache_v3.sqlite3"
    con=sqlite3.connect(db)
    con.execute("CREATE TABLE items (doc_key TEXT PRIMARY KEY, payload TEXT)")
    rows=[]
    idx=0
    semantic=[
        "SLOW_DELAY","CRASH_FREEZE","STATE_LOSS","MANUAL_REENTRY",
        "PAPER_TO_SLIDES","PRIVACY_CONSTRAINT","CONTEXT_RECONSTRUCTION",
        "FORMAT_TRANSFORMATION","HUMAN_VERIFICATION_BOTTLENECK",
    ]
    for block in range(14):
        for j in range(100):
            if j<70:
                sig=semantic[j%len(semantic)]
                payload={
                    "need_frame":{"version":"need-frame-v1","problem_signature":sig,
                                  "problem":"Users report "+sig.replace("_"," ").lower()+" in repeated workflows"},
                    "source_type":"hackernews" if j%2 else "github_issues",
                    "package_name":"package_name",
                    "created_at":1700000000+idx*60,
                }
            elif j<90:
                payload={
                    "need_frame":{"version":"need-frame-v1",
                                  "problem":f"Repeated manual workflow bottleneck pattern {j%6} causes delay"},
                    "source_type":"hackernews",
                    "metadata":{"package_name":"package_name","schema_version":"v3"},
                    "created_at":1700000000+idx*60,
                }
            else:
                payload={
                    "need_frame":{"version":"need-frame-v1",
                                  "problem_signature":f"NOVEL_WORKFLOW_BLOCK_{block}_{j%5}"},
                    "source_type":"github_issues",
                    "created_at":1700000000+idx*60,
                }
            rows.append((str(idx),json.dumps(payload)));idx+=1
    con.executemany("INSERT INTO items VALUES (?,?)",rows);con.commit();con.close()

    loc=u21.u19.locate_observation_table(root)
    rec,bq=u21.read_semantic_records(loc["selected"])
    ck("U21_SEMANTIC_BASIS_GATE_PASS",bq["status"]=="PASS",str(bq))
    topvals=dict(bq["top_selected_values"])
    ck("U21_NEED_FRAME_VERSION_NOT_SELECTED","need-frame-v1" not in topvals,str(bq["top_selected_values"][:5]))
    ck("U21_SOURCE_TYPE_NOT_SELECTED","source_type" not in topvals)
    ck("U21_PACKAGE_NAME_NOT_SELECTED","package_name" not in topvals)
    ck("U21_SEMANTIC_YIELD_HIGH",bq["semantic_yield"]>=0.95,str(bq["semantic_yield"]))

    fam,fd=u21.u20.form_families(rec)
    ck("U21_FAMILY_FORMATION_NOT_OVERMERGED",fd["status"]=="PASS",str(fd))
    ck("U21_LARGEST_FAMILY_SHARE_BOUNDED",fd["largest_family_share"]<0.45,str(fd["largest_family_share"]))

    r=u21.analyze(root)
    ck("U21_END_TO_END_PASS",r["status"]=="PASS",str(r.get("basis_quality")))
    ck("U21_BUDGET_CONTROL_FAILS_CLOSED",
       r["exploration_policy"]["eligible_for_exploration_budget_control"] ==
       r["calibration_gate"]["eligible_for_exploration_budget_control"])
    ck("U21_STATE_PERSISTED",(root/u21.STATE).exists())

    # Metadata-only corpus must fail before family formation.
    badroot=root/"bad";(badroot/".radar_runtime").mkdir(parents=True)
    baddb=badroot/".radar_runtime"/"observation_cache.sqlite"
    con=sqlite3.connect(baddb);con.execute("CREATE TABLE items (doc_key TEXT,payload TEXT)")
    badrows=[]
    # Must exceed the observation-locator's minimum DB-size threshold so this
    # negative test actually reaches the semantic-basis gate.
    for i in range(3000):
        badrows.append((str(i),json.dumps({"need_frame":{"version":"need-frame-v1"},
                                          "source_type":"source_type","package_name":"package_name",
                                          "metadata":{"padding":"x"*80,"schema_version":"v3"}})))
    con.executemany("INSERT INTO items VALUES (?,?)",badrows);con.commit();con.close()
    rb=u21.analyze(badroot)
    ck("U21_METADATA_ONLY_FAILS_BEFORE_FAMILY",rb["status"] in {"INSUFFICIENT_SEMANTIC_RECORDS","LOW_SEMANTIC_YIELD"},str(rb["status"]))
    print("U21_LOCAL_ACCEPTANCE_ALL_PASS",u21.ENGINE_VERSION)
