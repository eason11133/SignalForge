from __future__ import annotations
import json,sqlite3,time
from pathlib import Path
from processors.discovery_sentinel_review_contracts_u28 import DB
DDL="""
CREATE TABLE IF NOT EXISTS runs(run_id TEXT PRIMARY KEY,recorded_at REAL NOT NULL,status TEXT NOT NULL,summary_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS aspect_candidates(
 run_id TEXT NOT NULL,case_id TEXT NOT NULL,aspect TEXT NOT NULL,candidate_status TEXT NOT NULL,
 criteria_hash TEXT NOT NULL,criterion TEXT NOT NULL,u27_consensus TEXT NOT NULL,review_verdict TEXT NOT NULL,
 left_text_sha256 TEXT NOT NULL,right_text_sha256 TEXT NOT NULL,review_json TEXT NOT NULL,
 PRIMARY KEY(run_id,case_id,aspect));
CREATE TABLE IF NOT EXISTS candidate_manifests(
 run_id TEXT PRIMARY KEY,manifest_sha256 TEXT NOT NULL,source_snapshot_sha256 TEXT,
 independence_level TEXT NOT NULL,candidate_count INTEGER NOT NULL);
"""
def save(root:Path,run_id,status,summary,units,manifest):
    p=root/DB;p.parent.mkdir(parents=True,exist_ok=True)
    con=sqlite3.connect(p);con.executescript(DDL)
    con.execute("INSERT OR REPLACE INTO runs VALUES(?,?,?,?)",(run_id,time.time(),status,json.dumps(summary,sort_keys=True,default=str)))
    for u in units:
        con.execute("INSERT OR REPLACE INTO aspect_candidates VALUES(?,?,?,?,?,?,?,?,?,?,?)",(
          run_id,u["case_id"],u["aspect"],u["candidate_status"],u["criteria_hash"],u["criterion"],
          u["u27_consensus"],u["review_verdict"],u["left_text_sha256"],u["right_text_sha256"],
          json.dumps(u.get("review") or {},sort_keys=True,default=str)))
    con.execute("INSERT OR REPLACE INTO candidate_manifests VALUES(?,?,?,?,?)",(
      run_id,manifest["manifest_sha256"],manifest.get("source_snapshot_sha256"),manifest["independence_level"],manifest["candidate_count"]))
    con.commit();con.close()
