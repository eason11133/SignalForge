from __future__ import annotations
import os
for _k in ("OPENBLAS_NUM_THREADS","OMP_NUM_THREADS","MKL_NUM_THREADS","NUMEXPR_NUM_THREADS","VECLIB_MAXIMUM_THREADS","BLIS_NUM_THREADS"):
    os.environ[_k]="1"
import json,sqlite3,tempfile,re,hashlib
from pathlib import Path
from processors.discovery_criteria_first_symmetric_u27 import run
from processors.discovery_symmetric_contracts_u27 import U26_DB

def ck(n,x,d=""):
    if not x:raise AssertionError(n+" "+d)
    print(n+": PASS"+(" | "+d if d else ""))

class MockResponses:
    def create(self,model,input):
        if "CRITERIA BUILDER" in input:
            m=re.search(r"Cases=(\[.*\])$",input,re.S)
            if not m:
                # prompt uses Cases= only in judge; criteria uses Cases= appended too
                m=re.search(r"Cases=(\[.*\])$",input,re.S)
            # criteria prompt actually ends with Cases=
            payload=json.loads(input.split("Cases=",1)[1])
            out=[]
            for x in payload:
                out.append({"case_id":x["case_id"],"aspects":{
                  "WORKFLOW":{"criterion":"the task or process being performed","usable":True},
                  "FRICTION":{"criterion":"the observed difficulty or failure mode","usable":True},
                  "MECHANISM":{"criterion":"the supported causal mechanism","usable":False},
                  "CONSTRAINT":{"criterion":"the supported limiting condition","usable":False},
                  "CONSEQUENCE":{"criterion":"the observed impact","usable":False},
                }})
            return type("R",(),{"output_text":json.dumps({"cases":out})})()
        payload=json.loads(input.split("Cases=",1)[1])
        out=[]
        for x in payload:
            xt=x["X"]["text"].lower();yt=x["Y"]["text"].lower()
            same_delay=(("slow" in xt or "wait" in xt or "late" in xt) and ("slow" in yt or "wait" in yt or "late" in yt))
            same_crash=("crash" in xt and "crash" in yt)
            friction="SAME" if same_delay or same_crash else "DISTINCT"
            out.append({"case_id":x["case_id"],"criteria_hash":x["criteria_hash"],"aspects":{
              "WORKFLOW":{"verdict":"RELATED","reason":"both concern software work"},
              "FRICTION":{"verdict":friction,"reason":"compare the observed failure mode"},
              "MECHANISM":{"verdict":"DISTINCT","reason":"must be forced to UNKNOWN by unusable criterion"},
              "CONSTRAINT":{"verdict":"DISTINCT","reason":"must be forced to UNKNOWN by unusable criterion"},
              "CONSEQUENCE":{"verdict":"DISTINCT","reason":"must be forced to UNKNOWN by unusable criterion"},
            }})
        return type("R",(),{"output_text":json.dumps({"cases":out})})()
class MockClient:
    def __init__(self):self.responses=MockResponses()

with tempfile.TemporaryDirectory() as td:
    root=Path(td);(root/".radar_runtime").mkdir()
    db=root/U26_DB
    con=sqlite3.connect(db)
    con.executescript("""
      CREATE TABLE runs(run_id TEXT PRIMARY KEY,recorded_at REAL,status TEXT,summary_json TEXT);
      CREATE TABLE source_snapshots(run_id TEXT PRIMARY KEY,manifest_sha256 TEXT,rows_frozen INTEGER,lineage_json TEXT);
      CREATE TABLE cases(
        run_id TEXT,case_id TEXT,candidate_kind TEXT,candidate_similarity REAL,status TEXT,
        left_observation_key TEXT,right_observation_key TEXT,left_text TEXT,right_text TEXT,
        left_text_sha256 TEXT,right_text_sha256 TEXT,weak_label_metadata_json TEXT,adjudication_json TEXT
      );
      CREATE TABLE pointwise(run_id TEXT,observation_key TEXT,text_sha256 TEXT,extraction_json TEXT);
    """)
    con.execute("INSERT INTO runs VALUES(?,?,?,?)",("r1",1.0,"PASS_PROVISIONAL_SENTINEL_SEED","{}"))
    con.execute("INSERT INTO source_snapshots VALUES(?,?,?,?)",("r1","manifest",4,"{}"))
    texts={
      "a":"Users wait because the application is slow during editing",
      "b":"Batch processing is late and users wait for output",
      "c":"The application crash stops editing",
      "d":"Users cannot open the application workspace",
    }
    def hs(s):return hashlib.sha256(s.encode()).hexdigest()
    old_adj={"aspects":{
      "WORKFLOW":{"forward":"SAME","reverse":"UNKNOWN"},
      "FRICTION":{"forward":"RELATED","reverse":"DISTINCT"},
      "MECHANISM":{"forward":"UNKNOWN","reverse":"UNKNOWN"},
      "CONSTRAINT":{"forward":"UNKNOWN","reverse":"UNKNOWN"},
      "CONSEQUENCE":{"forward":"UNKNOWN","reverse":"UNKNOWN"},
    }}
    meta=json.dumps({"left_signature":"SECRET_A","right_signature":"SECRET_B"})
    cases=[
      ("r1","c1","SAME_LABEL_DIVERGENT",0.1,"CHALLENGE_ONLY","a","b",texts["a"],texts["b"],hs(texts["a"]),hs(texts["b"]),meta,json.dumps(old_adj)),
      ("r1","c2","CROSS_LABEL_NEAR",0.3,"CHALLENGE_ONLY","c","d",texts["c"],texts["d"],hs(texts["c"]),hs(texts["d"]),meta,json.dumps(old_adj)),
    ]
    con.executemany("INSERT INTO cases VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",cases)
    for oid,t in texts.items():
        ex={"aspects":{"WORKFLOW":{"value":"software workflow","evidence":"application","grounded":True},
                       "FRICTION":{"value":"problem","evidence":"UNKNOWN","grounded":True},
                       "MECHANISM":{"value":"UNKNOWN","evidence":"UNKNOWN","grounded":True},
                       "CONSTRAINT":{"value":"UNKNOWN","evidence":"UNKNOWN","grounded":True},
                       "CONSEQUENCE":{"value":"UNKNOWN","evidence":"UNKNOWN","grounded":True}},
            "all_evidence_grounded":True,"text_sha256":hs(t)}
        con.execute("INSERT INTO pointwise VALUES(?,?,?,?)",("r1",oid,hs(t),json.dumps(ex)))
    con.commit();con.close()
    before=hashlib.sha256(db.read_bytes()).hexdigest()
    r=run(root,client_factory=lambda:MockClient())
    after=hashlib.sha256(db.read_bytes()).hexdigest()
    ck("U27_END_TO_END_PASS",r["status"] in ("PASS_SYMMETRIC_PROTOCOL_IMPROVED","PASS_SYMMETRIC_PROTOCOL_SCREEN_NO_PROMOTION"),r["status"])
    ck("U27_SHARED_CRITERIA_REUSED",r["protocol"]["same_criteria_reused_bidirectionally"] is True)
    ck("U27_U26_DB_UNCHANGED",before==after and r["source"]["u26_db_unchanged"] is True)
    ck("U27_WEAK_LABEL_HIDDEN",r["protocol"]["weak_labels_visible_to_judge"] is False)
    ck("U27_CANDIDATE_KIND_HIDDEN",r["protocol"]["candidate_kind_visible_to_judge"] is False)
    ck("U27_UNUSABLE_CRITERIA_FORCE_UNKNOWN",r["u27_aspect_summary"]["MECHANISM"]["stable_unknown"]==2)
    ck("U27_NO_PROMOTION",r["authority"]["sentinel_promotion_allowed_from_u27"] is False and
       r["authority"]["representation_promotion_allowed_from_u27"] is False)
    ck("U27_CALL_BUDGET",r["judge"]["calls"]<=6,str(r["judge"]))
    print("U27_LOCAL_ACCEPTANCE_ALL_PASS",r["engine_version"])
