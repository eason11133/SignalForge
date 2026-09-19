from __future__ import annotations
import json,sqlite3,time
from pathlib import Path
from processors.discovery_representation_contracts_u24 import RESULT_DB

DDL="""
CREATE TABLE IF NOT EXISTS runs(
 run_id TEXT PRIMARY KEY,recorded_at REAL NOT NULL,status TEXT NOT NULL,summary_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS anchor_group_audit(
 run_id TEXT NOT NULL,signature TEXT NOT NULL,observations INTEGER NOT NULL,state TEXT NOT NULL,
 flags_json TEXT NOT NULL,intra_similarity REAL,nearest_signature TEXT,nearest_similarity REAL,
 PRIMARY KEY(run_id,signature)
);
CREATE TABLE IF NOT EXISTS representation_arm_metrics(
 run_id TEXT NOT NULL,arm TEXT NOT NULL,status TEXT NOT NULL,metrics_json TEXT NOT NULL,
 PRIMARY KEY(run_id,arm)
);
CREATE TABLE IF NOT EXISTS llm_frame_sample(
 run_id TEXT NOT NULL,observation_key TEXT NOT NULL,frame_json TEXT NOT NULL,
 PRIMARY KEY(run_id,observation_key)
);
"""
def connect(root:Path):
    p=root/RESULT_DB;p.parent.mkdir(parents=True,exist_ok=True)
    con=sqlite3.connect(p);con.executescript(DDL);con.commit();return con
def save(root:Path,run_id,status,summary,audit,arm_metrics,frames):
    con=connect(root)
    con.execute("INSERT OR REPLACE INTO runs VALUES(?,?,?,?)",(run_id,time.time(),status,json.dumps(summary,sort_keys=True,default=str)))
    for x in audit.get("groups") or []:
        con.execute("INSERT OR REPLACE INTO anchor_group_audit VALUES(?,?,?,?,?,?,?,?)",
          (run_id,x["signature"],x["observations"],x["state"],json.dumps(x["flags"],sort_keys=True),
           x.get("intra_similarity_proxy"),x.get("nearest_signature"),x.get("nearest_centroid_similarity_proxy")))
    for arm,m in arm_metrics.items():
        con.execute("INSERT OR REPLACE INTO representation_arm_metrics VALUES(?,?,?,?)",
                    (run_id,arm,m.get("status","READY"),json.dumps(m,sort_keys=True,default=str)))
    for oid,fr in frames.items():
        con.execute("INSERT OR REPLACE INTO llm_frame_sample VALUES(?,?,?)",(run_id,oid,json.dumps(fr,sort_keys=True)))
    con.commit();con.close()
