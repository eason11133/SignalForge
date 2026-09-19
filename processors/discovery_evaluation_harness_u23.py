from __future__ import annotations
import hashlib,json,sqlite3,time
from collections import Counter
from pathlib import Path

DB=Path(".radar_runtime/discovery_evaluation_v1.sqlite3")
DDL="""
CREATE TABLE IF NOT EXISTS runs(
 run_id TEXT PRIMARY KEY,recorded_at REAL NOT NULL,status TEXT NOT NULL,summary_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS weak_anchor_splits(
 signature TEXT PRIMARY KEY,split TEXT NOT NULL,observations INTEGER NOT NULL,label_status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS premortem_controls(
 control_id TEXT PRIMARY KEY,status TEXT NOT NULL,detail TEXT
);
"""

def connect(root:Path):
    p=root/DB;p.parent.mkdir(parents=True,exist_ok=True)
    con=sqlite3.connect(p);con.executescript(DDL);con.commit();return con

def _split(sig):
    x=int(hashlib.sha256(sig.encode()).hexdigest()[:8],16)%100
    return "CALIBRATION" if x<60 else ("VALIDATION" if x<80 else "BLIND")

def record_anchor_inventory(root:Path, top_or_all:dict):
    con=connect(root)
    for sig,n in top_or_all.items():
        con.execute("INSERT OR REPLACE INTO weak_anchor_splits VALUES(?,?,?,?)",
                    (sig,_split(sig),int(n),"WEAK_LABEL_ONLY_NOT_GROUND_TRUTH"))
    con.commit()
    split=Counter()
    for s,n in con.execute("SELECT split,COUNT(*) FROM weak_anchor_splits GROUP BY split"):split[s]=n
    total=con.execute("SELECT COUNT(*) FROM weak_anchor_splits").fetchone()[0]
    con.close()
    return {"distinct_signature_groups":int(total),"group_split_counts":dict(split),
            "truth_boundary":"GROUP_SPLITS_ARE_WEAK_LABEL_INVENTORY_NOT_SENTINEL_GROUND_TRUTH"}

def record_controls(root:Path,controls:dict):
    con=connect(root)
    for k,v in controls.items():
        if isinstance(v,dict):status=v.get("status","UNKNOWN");detail=json.dumps(v,sort_keys=True)
        else:status="PASS" if bool(v) else "FAIL";detail=str(v)
        con.execute("INSERT OR REPLACE INTO premortem_controls VALUES(?,?,?)",(k,status,detail))
    con.commit();con.close()

def record_run(root:Path,status:str,summary:dict):
    run_id="run_"+hashlib.sha256(json.dumps(summary,sort_keys=True,default=str).encode()).hexdigest()[:20]
    con=connect(root)
    con.execute("INSERT OR REPLACE INTO runs VALUES(?,?,?,?)",(run_id,time.time(),status,json.dumps(summary,sort_keys=True,default=str)))
    con.commit();con.close();return run_id
