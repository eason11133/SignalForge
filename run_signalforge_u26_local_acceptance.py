from __future__ import annotations
import os
for _k in ("OPENBLAS_NUM_THREADS","OMP_NUM_THREADS","MKL_NUM_THREADS","NUMEXPR_NUM_THREADS","VECLIB_MAXIMUM_THREADS","BLIS_NUM_THREADS"):
    os.environ[_k]="1"
import json,sqlite3,tempfile,re
from pathlib import Path

import processors.discovery_boundary_sentinel_u26 as lab
import processors.discovery_boundary_candidates_u26 as cand
from processors.discovery_benchmark_contracts_u25 import DB as U25_DB

def ck(n,x,d=""):
    if not x:raise AssertionError(n+" "+d)
    print(n+": PASS"+(" | "+d if d else ""))

class MockResponses:
    def create(self,model,input):
        if "Extract only what the text explicitly supports" in input:
            m=re.search(r"Items=(\[.*\])$",input,re.S);items=json.loads(m.group(1));out=[]
            for x in items:
                t=x["text"]
                low=t.lower()
                if "slow" in low or "wait" in low or "late" in low:
                    friction="delay";fev="slow" if "slow" in low else ("wait" if "wait" in low else "late")
                elif "crash" in low:
                    friction="crash";fev="crash"
                elif "access" in low or "open" in low:
                    friction="access unavailable";fev="open" if "open" in low else "access"
                else:
                    friction="workflow failure";fev="fails" if "fails" in low else "UNKNOWN"
                out.append({"id":x["id"],"aspects":{
                  "WORKFLOW":{"value":"software workflow","evidence":"application" if "application" in low else "Users"},
                  "FRICTION":{"value":friction,"evidence":fev},
                  "MECHANISM":{"value":"UNKNOWN","evidence":"UNKNOWN"},
                  "CONSTRAINT":{"value":"UNKNOWN","evidence":"UNKNOWN"},
                  "CONSEQUENCE":{"value":"UNKNOWN","evidence":"UNKNOWN"},
                }})
            return type("R",(),{"output_text":json.dumps({"items":out})})()
        m=re.search(r"Cases=(\[.*\])$",input,re.S);items=json.loads(m.group(1));out=[]
        for x in items:
            a=x["A"]["text"].lower();b=x["B"]["text"].lower()
            same_delay=(("slow" in a or "wait" in a or "late" in a) and ("slow" in b or "wait" in b or "late" in b))
            same_crash=("crash" in a and "crash" in b)
            v="SAME" if (same_delay or same_crash) else "DISTINCT"
            out.append({"case_id":x["case_id"],"aspects":{
              "WORKFLOW":{"criteria":"task context","verdict":"RELATED"},
              "FRICTION":{"criteria":"observed failure mode","verdict":v},
              "MECHANISM":{"criteria":"causal mechanism","verdict":"UNKNOWN"},
              "CONSTRAINT":{"criteria":"limiting condition","verdict":"UNKNOWN"},
              "CONSEQUENCE":{"criteria":"observed impact","verdict":"UNKNOWN"},
            }})
        return type("R",(),{"output_text":json.dumps({"cases":out})})()
class MockClient:
    def __init__(self):self.responses=MockResponses()

with tempfile.TemporaryDirectory() as td:
    root=Path(td);rt=root/".radar_runtime";rt.mkdir()
    db=root/U25_DB
    con=sqlite3.connect(db)
    con.executescript("""
    CREATE TABLE runs(run_id TEXT PRIMARY KEY,recorded_at REAL,status TEXT,summary_json TEXT);
    CREATE TABLE recovered_anchor_content(
      run_id TEXT,observation_key TEXT,signature TEXT,text TEXT,content_path TEXT,content_class TEXT,source TEXT,
      PRIMARY KEY(run_id,observation_key));
    """)
    con.execute("INSERT INTO runs VALUES(?,?,?,?)",("u25-fixture",1.0,"PASS_BENCHMARK_DECONTAMINATION","{}"))
    sigs=["SLOW_DELAY","PROCESSING_DELAY","CRASH_FREEZE","ACCESS_UNAVAILABLE"]
    rows=[]
    for sig in sigs:
        for j in range(6):
            if sig=="SLOW_DELAY":txt=f"Users wait because the application is slow during normal editing case {j}"
            elif sig=="PROCESSING_DELAY":txt=f"Batch processing finishes late and downstream users wait case {j}"
            elif sig=="CRASH_FREEZE":txt=f"The application crash stops editing and loses the current session case {j}"
            else:txt=f"Users cannot open the application workspace because access is unavailable case {j}"
            rows.append(("u25-fixture",f"{sig}-{j}",sig,txt,"evidence_atom.text","FALLBACK_TEXT","fixture"))
    con.executemany("INSERT INTO recovered_anchor_content VALUES(?,?,?,?,?,?,?)",rows);con.commit();con.close()

    raw_rows,lineage=cand.load_latest_decontaminated_rows(root)
    cases,diag=cand.generate_candidates(raw_rows,max_cases=12)
    ck("U26_BOUNDARY_CASES_GENERATED",len(cases)==12,str(diag))
    ck("U26_FROZEN_TEXT_HASHES",all(c["left"]["text_sha256"] and c["right"]["text_sha256"] for c in cases))
    ck("U26_WEAK_LABELS_ONLY_METADATA",all("signature" in c["left"] and "signature" in c["right"] for c in cases))

    r=lab.run(root,client_factory=lambda:MockClient())
    ck("U26_END_TO_END_PASS",r["status"]=="PASS_PROVISIONAL_SENTINEL_SEED",r["status"])
    ck("U26_POINTWISE_GROUNDED",r["pointwise"]["fully_grounded"]>0,str(r["pointwise"]))
    ck("U26_BIDIRECTIONAL_CASES",r["adjudication"]["forward_cases"]==r["adjudication"]["reverse_cases"])
    ck("U26_PROVISIONAL_SEED_EXISTS",r["adjudication"]["case_status_counts"].get("PROVISIONAL_SENTINEL_SEED",0)>0)
    ck("U26_NO_PROMOTION",r["authority"]["representation_promotion_allowed_from_u26"] is False)
    ck("U26_CALL_BUDGET",r["judge"]["calls"]<=6,str(r["judge"]))
    print("U26_LOCAL_ACCEPTANCE_ALL_PASS",r["engine_version"])
