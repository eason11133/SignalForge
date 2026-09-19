from __future__ import annotations
import json,sqlite3,time
from pathlib import Path
from processors.discovery_boundary_contracts_u26 import DB

DDL="""
CREATE TABLE IF NOT EXISTS runs(
 run_id TEXT PRIMARY KEY,recorded_at REAL NOT NULL,status TEXT NOT NULL,summary_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS source_snapshots(
 run_id TEXT PRIMARY KEY,manifest_sha256 TEXT NOT NULL,rows_frozen INTEGER NOT NULL,lineage_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cases(
 run_id TEXT NOT NULL,case_id TEXT NOT NULL,candidate_kind TEXT NOT NULL,candidate_similarity REAL,
 status TEXT NOT NULL,left_observation_key TEXT NOT NULL,right_observation_key TEXT NOT NULL,
 left_text TEXT NOT NULL,right_text TEXT NOT NULL,left_text_sha256 TEXT NOT NULL,right_text_sha256 TEXT NOT NULL,
 weak_label_metadata_json TEXT NOT NULL,adjudication_json TEXT NOT NULL,
 PRIMARY KEY(run_id,case_id)
);
CREATE TABLE IF NOT EXISTS pointwise(
 run_id TEXT NOT NULL,observation_key TEXT NOT NULL,text_sha256 TEXT NOT NULL,extraction_json TEXT NOT NULL,
 PRIMARY KEY(run_id,observation_key)
);
"""
def connect(root:Path):
    p=root/DB;p.parent.mkdir(parents=True,exist_ok=True)
    con=sqlite3.connect(p);con.executescript(DDL);con.commit();return con
def save(root:Path,run_id,status,summary,snapshot,cases,pointwise):
    con=connect(root)
    con.execute("INSERT OR REPLACE INTO runs VALUES(?,?,?,?)",
                (run_id,time.time(),status,json.dumps(summary,sort_keys=True,default=str)))
    con.execute("INSERT OR REPLACE INTO source_snapshots VALUES(?,?,?,?)",
                (run_id,snapshot["content_manifest_sha256"],snapshot["rows_frozen"],
                 json.dumps(snapshot["lineage"],sort_keys=True,default=str)))
    for oid,x in pointwise.items():
        # text hash is also stored in cases; derive from summary input manifest when possible.
        con.execute("INSERT OR REPLACE INTO pointwise VALUES(?,?,?,?)",
                    (run_id,oid,x.get("text_sha256",""),json.dumps(x,sort_keys=True,default=str)))
    for c in cases:
        con.execute("""INSERT OR REPLACE INTO cases VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",(
          run_id,c["case_id"],c["candidate_kind"],c.get("candidate_similarity_proxy"),c["status"],
          c["left"]["observation_key"],c["right"]["observation_key"],c["left"]["text"],c["right"]["text"],
          c["left"]["text_sha256"],c["right"]["text_sha256"],
          json.dumps({"left_signature":c["left"]["signature"],"right_signature":c["right"]["signature"],
                      "weak_label_relation_hint":c["weak_label_relation_hint"]},sort_keys=True),
          json.dumps(c["adjudication"],sort_keys=True,default=str)
        ))
    con.commit();con.close()
