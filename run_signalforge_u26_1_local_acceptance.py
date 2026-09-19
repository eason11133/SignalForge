import sqlite3,json,tempfile
from pathlib import Path
from processors.discovery_boundary_diagnostic_u26_1 import analyze,DB

def ck(n,x,d=""):
    if not x: raise AssertionError(n+" "+d)
    print(n+": PASS"+(" | "+d if d else ""))

with tempfile.TemporaryDirectory() as td:
    root=Path(td);(root/".radar_runtime").mkdir()
    con=sqlite3.connect(root/DB)
    con.executescript("""
      CREATE TABLE runs(run_id TEXT PRIMARY KEY,recorded_at REAL,status TEXT,summary_json TEXT);
      CREATE TABLE cases(
        run_id TEXT,case_id TEXT,candidate_kind TEXT,candidate_similarity REAL,status TEXT,
        left_observation_key TEXT,right_observation_key TEXT,left_text TEXT,right_text TEXT,
        left_text_sha256 TEXT,right_text_sha256 TEXT,weak_label_metadata_json TEXT,adjudication_json TEXT
      );
    """)
    con.execute("INSERT INTO runs VALUES(?,?,?,?)",("r1",1.0,"PASS_PROVISIONAL_SENTINEL_SEED","{}"))
    meta=json.dumps({"left_signature":"A","right_signature":"B"})
    a={"aspects":{
      "WORKFLOW":{"forward":"SAME","reverse":"DISTINCT"},
      "FRICTION":{"forward":"RELATED","reverse":"UNKNOWN"},
      "MECHANISM":{"forward":"UNKNOWN","reverse":"UNKNOWN"},
      "CONSTRAINT":{"forward":"UNKNOWN","reverse":"UNKNOWN"},
      "CONSEQUENCE":{"forward":"UNKNOWN","reverse":"UNKNOWN"}}}
    b={"aspects":{x:{"forward":"UNKNOWN","reverse":"UNKNOWN"} for x in
                  ("WORKFLOW","FRICTION","MECHANISM","CONSTRAINT","CONSEQUENCE")}}
    con.executemany("INSERT INTO cases VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",[
      ("r1","c1","CROSS_LABEL_NEAR",0.3,"INSUFFICIENT","a","b","x","y","h1","h2",meta,json.dumps(a)),
      ("r1","c2","CROSS_LABEL_ORTHOGONAL",0.0,"INSUFFICIENT","c","d","x","y","h3","h4",meta,json.dumps(b)),
    ])
    con.commit();con.close()
    r=analyze(root)
    ck("U26_1_READ_ONLY_PASS",r["status"]=="PASS_READ_ONLY_DIAGNOSTIC")
    ck("U26_1_ORDER_SENSITIVITY_DETECTED",r["root_cause_counts"].get("ORDER_SENSITIVITY")==1,str(r["root_cause_counts"]))
    ck("U26_1_TRUE_GAP_DETECTED",r["root_cause_counts"].get("TRUE_INFORMATION_GAP")==1,str(r["root_cause_counts"]))
    ck("U26_1_UNKNOWN_ASYMMETRY_CLASSIFIED",r["aspect_summary"]["FRICTION"]["unknown_asymmetry"]==1)
    ck("U26_1_ORDER_FLIP_CLASSIFIED",r["aspect_summary"]["WORKFLOW"]["order_flip"]==1)
    ck("U26_1_NO_AUTHORITY",r["decision"]["production_authority"]==0 and not r["decision"]["u26_data_modified"])
    print("U26_1_LOCAL_ACCEPTANCE_ALL_PASS")
