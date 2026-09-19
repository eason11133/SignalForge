from __future__ import annotations
import json,sqlite3,time
from pathlib import Path
from processors.discovery_benchmark_contracts_u25 import DB

DDL="""
CREATE TABLE IF NOT EXISTS runs(
 run_id TEXT PRIMARY KEY,recorded_at REAL NOT NULL,status TEXT NOT NULL,summary_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS recovered_anchor_content(
 run_id TEXT NOT NULL,observation_key TEXT NOT NULL,signature TEXT NOT NULL,text TEXT NOT NULL,
 content_path TEXT NOT NULL,content_class TEXT NOT NULL,source TEXT,
 PRIMARY KEY(run_id,observation_key)
);
CREATE TABLE IF NOT EXISTS benchmark_lineage(
 run_id TEXT NOT NULL,parent_benchmark TEXT NOT NULL,parent_status TEXT NOT NULL,reason TEXT NOT NULL,
 PRIMARY KEY(run_id,parent_benchmark)
);
"""
def connect(root:Path):
    p=root/DB;p.parent.mkdir(parents=True,exist_ok=True)
    con=sqlite3.connect(p);con.executescript(DDL);con.commit();return con
def save(root:Path,run_id,status,summary,rows):
    con=connect(root)
    con.execute("INSERT OR REPLACE INTO runs VALUES(?,?,?,?)",(run_id,time.time(),status,json.dumps(summary,sort_keys=True,default=str)))
    for r in rows:
        con.execute("INSERT OR REPLACE INTO recovered_anchor_content VALUES(?,?,?,?,?,?,?)",
                    (run_id,r["observation_key"],r["signature"],r["text"],r["content_path"],r["content_class"],r.get("source")))
    con.execute("INSERT OR REPLACE INTO benchmark_lineage VALUES(?,?,?,?)",
                (run_id,"U24_WEAK_LABEL_PROXY","INVALIDATED_FOR_MODEL_COMPARISON",
                 "EXPLICIT_SIGNATURE_LABEL_TEXT_WAS_USED_AS_REPRESENTATION_INPUT_FOR_WEAK_ANCHOR_ROWS"))
    con.commit();con.close()
