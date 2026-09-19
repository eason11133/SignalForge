from __future__ import annotations
import json,sqlite3,hashlib
from pathlib import Path
from processors.discovery_symmetric_contracts_u27 import U26_DB,ASPECTS

def sha_file(path:Path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):h.update(b)
    return h.hexdigest()

def _connect_ro(path:Path):
    return sqlite3.connect("file:"+str(path.resolve())+"?mode=ro",uri=True)

def load_latest_u26(root:Path):
    path=root/U26_DB
    if not path.exists(): raise RuntimeError("U27_U26_DB_MISSING")
    before=sha_file(path)
    con=_connect_ro(path);con.row_factory=sqlite3.Row
    run=con.execute("SELECT run_id,status,recorded_at,summary_json FROM runs ORDER BY recorded_at DESC LIMIT 1").fetchone()
    if not run:
        con.close();raise RuntimeError("U27_U26_RUN_MISSING")
    snap=con.execute("SELECT * FROM source_snapshots WHERE run_id=?",(run["run_id"],)).fetchone()
    cases=[dict(r) for r in con.execute("""
      SELECT case_id,candidate_kind,candidate_similarity,status,
             left_observation_key,right_observation_key,left_text,right_text,
             left_text_sha256,right_text_sha256,weak_label_metadata_json,adjudication_json
      FROM cases WHERE run_id=? ORDER BY case_id
    """,(run["run_id"],))]
    pws={r["observation_key"]:dict(r) for r in con.execute(
        "SELECT * FROM pointwise WHERE run_id=?",(run["run_id"],))}
    con.close()
    after=sha_file(path)
    if before!=after: raise RuntimeError("U27_U26_DB_HASH_CHANGED_DURING_READ")
    return {
      "run":dict(run),"snapshot":dict(snap) if snap else None,
      "cases":cases,"pointwise":pws,"u26_db_sha256":before
    }

def pointwise_payload(raw):
    if not raw:return {}
    try:return json.loads(raw.get("extraction_json") or "{}")
    except Exception:return {}

def canonical_pair(case):
    left={
      "id":case["left_observation_key"],"text":case["left_text"],"text_sha256":case["left_text_sha256"]
    }
    right={
      "id":case["right_observation_key"],"text":case["right_text"],"text_sha256":case["right_text_sha256"]
    }
    return (left,right) if (left["text_sha256"],left["id"]) <= (right["text_sha256"],right["id"]) else (right,left)

def baseline_instability(cases):
    out={a:{"stable":0,"unstable":0} for a in ASPECTS}
    for c in cases:
        adj=json.loads(c["adjudication_json"])
        for a in ASPECTS:
            z=(adj.get("aspects") or {}).get(a) or {}
            f=str(z.get("forward") or "UNKNOWN").upper()
            r=str(z.get("reverse") or "UNKNOWN").upper()
            if f==r:out[a]["stable"]+=1
            else:out[a]["unstable"]+=1
    n=max(1,len(cases))
    return {a:{
      "stable":x["stable"],"unstable":x["unstable"],
      "order_instability_rate":round(x["unstable"]/n,6)
    } for a,x in out.items()}
