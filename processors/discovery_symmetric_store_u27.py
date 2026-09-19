from __future__ import annotations
import json,sqlite3,time
from pathlib import Path
from processors.discovery_symmetric_contracts_u27 import DB

DDL="""
CREATE TABLE IF NOT EXISTS runs(
 run_id TEXT PRIMARY KEY,recorded_at REAL NOT NULL,status TEXT NOT NULL,summary_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS criteria(
 run_id TEXT NOT NULL,case_id TEXT NOT NULL,criteria_hash TEXT NOT NULL,criteria_json TEXT NOT NULL,
 PRIMARY KEY(run_id,case_id)
);
CREATE TABLE IF NOT EXISTS judgments(
 run_id TEXT NOT NULL,case_id TEXT NOT NULL,direction TEXT NOT NULL,criteria_hash TEXT NOT NULL,
 judgment_json TEXT NOT NULL,PRIMARY KEY(run_id,case_id,direction)
);
"""
def save(root:Path,run_id,status,summary,criteria,forward,reverse):
    p=root/DB;p.parent.mkdir(parents=True,exist_ok=True)
    con=sqlite3.connect(p);con.executescript(DDL)
    con.execute("INSERT OR REPLACE INTO runs VALUES(?,?,?,?)",
                (run_id,time.time(),status,json.dumps(summary,sort_keys=True,default=str)))
    for cid,x in criteria.items():
        con.execute("INSERT OR REPLACE INTO criteria VALUES(?,?,?,?)",
                    (run_id,cid,x["criteria_hash"],json.dumps(x,sort_keys=True,default=str)))
    for direction,data in (("FORWARD",forward),("REVERSE",reverse)):
        for cid,x in data.items():
            con.execute("INSERT OR REPLACE INTO judgments VALUES(?,?,?,?,?)",
                        (run_id,cid,direction,x["criteria_hash"],json.dumps(x,sort_keys=True,default=str)))
    con.commit();con.close()
