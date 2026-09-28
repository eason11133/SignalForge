import json,sqlite3,tempfile,hashlib,os
from pathlib import Path
from processors.discovery_sentinel_review_u28 import run
from processors.discovery_sentinel_review_contracts_u28 import U26_DB,U27_DB

def ck(n,x,d=""):
    if not x:raise AssertionError(n+" "+d)
    print(n+": PASS"+(" | "+d if d else ""))

class MockResponses:
    def create(self,model,input):
        payload=json.loads(input.split("Cases=",1)[1]);out=[]
        for x in payload:
            aspects={}
            for a,cr in x["criteria"].items():
                if not cr.get("usable"):v="UNKNOWN"
                else:v={"WORKFLOW":"RELATED","FRICTION":"DISTINCT","MECHANISM":"SAME","CONSTRAINT":"SAME","CONSEQUENCE":"SAME"}[a]
                aspects[a]={"verdict":v,"reason":"independent review fixture"}
            out.append({"case_id":x["case_id"],"criteria_hash":x["criteria_hash"],"aspects":aspects})
        return type("R",(),{"output_text":json.dumps({"cases":out})})()
class MockClient:
    def __init__(self):self.responses=MockResponses()

with tempfile.TemporaryDirectory() as td:
    root=Path(td);rt=root/".radar_runtime";rt.mkdir();p26=root/U26_DB;p27=root/U27_DB
    c=sqlite3.connect(p26);c.executescript("""
      CREATE TABLE runs(run_id TEXT PRIMARY KEY,recorded_at REAL,status TEXT,summary_json TEXT);
      CREATE TABLE source_snapshots(run_id TEXT PRIMARY KEY,manifest_sha256 TEXT,rows_frozen INTEGER,lineage_json TEXT);
      CREATE TABLE cases(run_id TEXT,case_id TEXT,candidate_kind TEXT,candidate_similarity REAL,status TEXT,
        left_observation_key TEXT,right_observation_key TEXT,left_text TEXT,right_text TEXT,
        left_text_sha256 TEXT,right_text_sha256 TEXT,weak_label_metadata_json TEXT,adjudication_json TEXT);
    """)
    c.execute("INSERT INTO runs VALUES(?,?,?,?)",("u26x",1.0,"PASS_PROVISIONAL_SENTINEL_SEED","{}"))
    c.execute("INSERT INTO source_snapshots VALUES(?,?,?,?)",("u26x","snapx",20,"{}"))
    for i in range(10):
        lt=f"left frozen observation {i}";rtx=f"right frozen observation {i}"
        h1=hashlib.sha256(lt.encode()).hexdigest();h2=hashlib.sha256(rtx.encode()).hexdigest()
        c.execute("INSERT INTO cases VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",("u26x",f"c{i}","SECRET_KIND",0.2,"SECRET_STATUS",
          f"L{i}",f"R{i}",lt,rtx,h1,h2,json.dumps({"left_signature":"SECRET_A","right_signature":"SECRET_B"}),"{}"))
    c.commit();c.close()

    c=sqlite3.connect(p27);c.executescript("""
      CREATE TABLE runs(run_id TEXT PRIMARY KEY,recorded_at REAL,status TEXT,summary_json TEXT);
      CREATE TABLE criteria(run_id TEXT,case_id TEXT,criteria_hash TEXT,criteria_json TEXT);
      CREATE TABLE judgments(run_id TEXT,case_id TEXT,direction TEXT,criteria_hash TEXT,judgment_json TEXT);
    """)
    c.execute("INSERT INTO runs VALUES(?,?,?,?)",("u27x",2.0,"PASS_SYMMETRIC_PROTOCOL_IMPROVED",
      json.dumps({"source":{"u26_run_id":"u26x"},"judge":{"model":"gpt-5-mini"}})))
    expected={"WORKFLOW":"RELATED","FRICTION":"DISTINCT","MECHANISM":"SAME","CONSTRAINT":"SAME","CONSEQUENCE":"SAME"}
    for i in range(10):
        aspects={a:{"criterion":f"criterion {a}","usable":True} for a in expected}
        cr_obj={"aspects":aspects}
        # Criteria hash value is opaque to loader; it only must be reused consistently.
        ch=hashlib.sha256(json.dumps(cr_obj,sort_keys=True).encode()).hexdigest()
        c.execute("INSERT INTO criteria VALUES(?,?,?,?)",("u27x",f"c{i}",ch,json.dumps(cr_obj)))
        j={"criteria_hash":ch,"aspects":{a:{"verdict":v,"reason":"fixture"} for a,v in expected.items()}}
        for d in ("FORWARD","REVERSE"):c.execute("INSERT INTO judgments VALUES(?,?,?,?,?)",("u27x",f"c{i}",d,ch,json.dumps(j)))
    c.commit();c.close()

    b26=hashlib.sha256(p26.read_bytes()).hexdigest();b27=hashlib.sha256(p27.read_bytes()).hexdigest()
    os.environ["SIGNALFORGE_U28_REVIEW_MODEL"]="gpt-5-review-fixture"
    r=run(root,client_factory=lambda:MockClient())
    a26=hashlib.sha256(p26.read_bytes()).hexdigest();a27=hashlib.sha256(p27.read_bytes()).hexdigest()
    ck("U28_END_TO_END_PASS",r["status"]=="PASS_SENTINEL_V1_CANDIDATE_MODEL_DISTINCT",r["status"])
    ck("U28_SOURCE_DBS_UNCHANGED",b26==a26 and b27==a27)
    ck("U28_MODEL_DISTINCT_TRUTH",r["reviewer"]["independence_level"]=="MODEL_DISTINCT")
    ck("U28_ASPECT_LEVEL_CANDIDATES",r["candidate_manifest"]["candidate_count"]==50,str(r["candidate_manifest"]))
    ck("U28_GATE_PASS",r["decision"]["candidate_gate_pass"] is True)
    ck("U28_NOT_FROZEN",r["authority"]["sentinel_v1_frozen"] is False)
    ck("U28_NO_REP_PROMOTION",r["authority"]["representation_promotion_allowed_from_u28"] is False)
    ck("U28_CALL_BUDGET",r["reviewer"]["calls"]<=2,str(r["reviewer"]))
    print("U28_LOCAL_ACCEPTANCE_ALL_PASS",r["engine_version"])
