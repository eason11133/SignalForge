from __future__ import annotations
import json,sqlite3,hashlib
from pathlib import Path
from processors.discovery_sentinel_review_contracts_u28 import U26_DB,U27_DB,ASPECTS

def sha_file(path:Path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):h.update(b)
    return h.hexdigest()

def _ro(path:Path):
    return sqlite3.connect("file:"+str(path.resolve())+"?mode=ro",uri=True)

def _json(s):
    try:return json.loads(s or "{}")
    except Exception:return {}

def load_sources(root:Path):
    p26=root/U26_DB;p27=root/U27_DB
    if not p26.exists():raise RuntimeError("U28_U26_DB_MISSING")
    if not p27.exists():raise RuntimeError("U28_U27_DB_MISSING")
    h26a=sha_file(p26);h27a=sha_file(p27)

    c27=_ro(p27);c27.row_factory=sqlite3.Row
    r27=c27.execute("SELECT run_id,status,recorded_at,summary_json FROM runs ORDER BY recorded_at DESC LIMIT 1").fetchone()
    if not r27:
        c27.close();raise RuntimeError("U28_U27_RUN_MISSING")
    summary=_json(r27["summary_json"])
    u26_run_id=((summary.get("source") or {}).get("u26_run_id"))
    if not u26_run_id:
        c27.close();raise RuntimeError("U28_U27_SOURCE_U26_RUN_MISSING")
    criteria={r["case_id"]:dict(r) for r in c27.execute(
        "SELECT case_id,criteria_hash,criteria_json FROM criteria WHERE run_id=?",(r27["run_id"],))}
    judgments={}
    for r in c27.execute("SELECT case_id,direction,criteria_hash,judgment_json FROM judgments WHERE run_id=?",(r27["run_id"],)):
        judgments.setdefault(r["case_id"],{})[r["direction"]]=dict(r)
    c27.close()

    c26=_ro(p26);c26.row_factory=sqlite3.Row
    snap=c26.execute("SELECT * FROM source_snapshots WHERE run_id=?",(u26_run_id,)).fetchone()
    cases={r["case_id"]:dict(r) for r in c26.execute("""
      SELECT case_id,left_observation_key,right_observation_key,left_text,right_text,
             left_text_sha256,right_text_sha256
      FROM cases WHERE run_id=? ORDER BY case_id
    """,(u26_run_id,))}
    c26.close()

    h26b=sha_file(p26);h27b=sha_file(p27)
    if h26a!=h26b:raise RuntimeError("U28_U26_DB_CHANGED_DURING_READ")
    if h27a!=h27b:raise RuntimeError("U28_U27_DB_CHANGED_DURING_READ")
    return {
      "u27_run":dict(r27),"u27_summary":summary,"u26_run_id":u26_run_id,
      "snapshot":dict(snap) if snap else None,"criteria":criteria,"judgments":judgments,"cases":cases,
      "hashes":{"u26_before":h26a,"u26_after":h26b,"u27_before":h27a,"u27_after":h27b}
    }

def build_review_units(data):
    units=[];case_payloads=[]
    for cid,case in sorted(data["cases"].items()):
        cr_row=data["criteria"].get(cid);js=data["judgments"].get(cid) or {}
        frow=js.get("FORWARD");rrow=js.get("REVERSE")
        if not cr_row or not frow or not rrow:continue
        cr=_json(cr_row["criteria_json"]);f=_json(frow["judgment_json"]);rv=_json(rrow["judgment_json"])
        criteria_hash=cr_row["criteria_hash"]
        if frow["criteria_hash"]!=criteria_hash or rrow["criteria_hash"]!=criteria_hash:continue
        review_criteria={}
        for a in ASPECTS:
            crit=((cr.get("aspects") or {}).get(a) or {})
            fv=(((f.get("aspects") or {}).get(a) or {}).get("verdict") or "UNKNOWN").upper()
            rvv=(((rv.get("aspects") or {}).get(a) or {}).get("verdict") or "UNKNOWN").upper()
            stable=(fv==rvv);consensus=fv if stable else "UNKNOWN"
            criterion=crit.get("criterion") or "";usable=bool(crit.get("usable"))
            review_criteria[a]={"criterion":criterion,"usable":usable}
            units.append({
              "case_id":cid,"aspect":a,"criteria_hash":criteria_hash,"criterion":criterion,"usable":usable,
              "u27_forward":fv,"u27_reverse":rvv,"u27_stable":stable,"u27_consensus":consensus,
              "left_text_sha256":case["left_text_sha256"],"right_text_sha256":case["right_text_sha256"],
            })
        left={"id":case["left_observation_key"],"text":case["left_text"],"sha256":case["left_text_sha256"]}
        right={"id":case["right_observation_key"],"text":case["right_text"],"sha256":case["right_text_sha256"]}
        if (left["sha256"],left["id"]) > (right["sha256"],right["id"]):left,right=right,left
        case_payloads.append({
          "case_id":cid,"criteria_hash":criteria_hash,"item_1":left,"item_2":right,"criteria":review_criteria
        })
    return units,case_payloads
