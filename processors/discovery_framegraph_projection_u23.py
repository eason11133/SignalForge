from __future__ import annotations
import hashlib,json,sqlite3
from pathlib import Path
from processors.discovery_knowledge_contracts_u23 import validate_event, EVENT_SCHEMA_VERSION, canonical_json
from processors.discovery_event_ledger_u23 import read_events

DB=Path(".radar_runtime/discovery_knowledge_projection_v1.sqlite3")

DDL="""
CREATE TABLE meta(k TEXT PRIMARY KEY,v TEXT NOT NULL);
CREATE TABLE evidence_spans(
  span_id TEXT PRIMARY KEY,observation_key TEXT,text TEXT,basis_path TEXT,basis_class TEXT,source TEXT,
  valid_at TEXT,valid_time_status TEXT,locator_json TEXT,active INTEGER,proposed_event_key TEXT,invalidated_event_key TEXT
);
CREATE TABLE weak_anchors(
  observation_key TEXT PRIMARY KEY,signature TEXT NOT NULL,label_status TEXT NOT NULL,event_key TEXT NOT NULL
);
CREATE TABLE granularity_routes(
  observation_key TEXT PRIMARY KEY,route TEXT NOT NULL,reasons_json TEXT NOT NULL,event_key TEXT NOT NULL
);
CREATE TABLE constraints_current(
  constraint_id TEXT PRIMARY KEY,aspect TEXT NOT NULL,left_id TEXT NOT NULL,right_id TEXT NOT NULL,
  verdict TEXT NOT NULL,event_key TEXT NOT NULL
);
CREATE TABLE claims(
  claim_id TEXT PRIMARY KEY,claim_json TEXT NOT NULL,status TEXT NOT NULL,event_key TEXT NOT NULL
);
CREATE TABLE justifications(
  justification_id TEXT PRIMARY KEY,claim_id TEXT NOT NULL,active INTEGER NOT NULL,depends_json TEXT NOT NULL,event_key TEXT NOT NULL
);
CREATE TABLE taxonomy_nodes(
  node_id TEXT PRIMARY KEY,label TEXT,state TEXT,event_key TEXT
);
CREATE TABLE provider_eligibility(
  provider TEXT PRIMARY KEY,level TEXT NOT NULL,event_key TEXT NOT NULL
);
CREATE TABLE intelligence_hypotheses(
  hypothesis_id TEXT PRIMARY KEY,kind TEXT NOT NULL,payload_json TEXT NOT NULL,event_key TEXT NOT NULL
);
"""

def _payload(e): return json.loads(e["payload_json"])

def _recompute_claim(con,claim_id):
    n=con.execute("SELECT COUNT(*) FROM justifications WHERE claim_id=? AND active=1",(claim_id,)).fetchone()[0]
    con.execute("UPDATE claims SET status=? WHERE claim_id=?",("SUPPORTED" if n else "UNSUPPORTED",claim_id))

def rebuild(root:Path):
    path=root/DB;path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():path.unlink()
    con=sqlite3.connect(path);con.row_factory=sqlite3.Row;con.executescript(DDL)
    con.execute("INSERT INTO meta(k,v) VALUES('schema','discovery_knowledge_projection_v1')")
    applied=0
    for e in read_events(root):
        validate_event(e)
        if e["schema_version"]!=EVENT_SCHEMA_VERSION: raise RuntimeError("PROJECTION_UNSUPPORTED_SCHEMA")
        p=_payload(e);t=e["event_type"]
        if t=="EVIDENCE_SPAN_PROPOSED":
            con.execute("""INSERT OR REPLACE INTO evidence_spans VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",(
                p["span_id"],e["source_observation_key"],p["text"],p["basis_path"],p["basis_class"],p["source"],
                e.get("valid_at"),p.get("valid_time_status","UNKNOWN"),json.dumps(p.get("locator") or {},sort_keys=True),
                1,e["event_key"],None))
        elif t=="EVIDENCE_SPAN_INVALIDATED":
            con.execute("UPDATE evidence_spans SET active=0,invalidated_event_key=? WHERE span_id=?",
                        (e["event_key"],p["span_id"]))
        elif t=="WEAK_ANCHOR_OBSERVED":
            con.execute("INSERT OR REPLACE INTO weak_anchors VALUES(?,?,?,?)",
                        (e["source_observation_key"],p["signature"],p.get("label_status","WEAK_LABEL_ONLY"),e["event_key"]))
        elif t=="GRANULARITY_ROUTED":
            con.execute("INSERT OR REPLACE INTO granularity_routes VALUES(?,?,?,?)",
                        (e["source_observation_key"],p["route"],json.dumps(p.get("reasons") or [],sort_keys=True),e["event_key"]))
        elif t in {"CONSTRAINT_JUDGED","CONSTRAINT_REVISED"}:
            con.execute("INSERT OR REPLACE INTO constraints_current VALUES(?,?,?,?,?,?)",
                        (p["constraint_id"],p["aspect"],p["left_id"],p["right_id"],p["verdict"],e["event_key"]))
        elif t=="CLAIM_PROPOSED":
            con.execute("INSERT OR REPLACE INTO claims VALUES(?,?,?,?)",
                        (p["claim_id"],json.dumps(p.get("claim") or {},sort_keys=True),"UNSUPPORTED",e["event_key"]))
        elif t=="JUSTIFICATION_ATTACHED":
            con.execute("INSERT OR REPLACE INTO justifications VALUES(?,?,?,?,?)",
                        (p["justification_id"],p["claim_id"],1,json.dumps(p.get("depends_on_event_keys") or [],sort_keys=True),e["event_key"]))
            _recompute_claim(con,p["claim_id"])
        elif t=="JUSTIFICATION_INVALIDATED":
            row=con.execute("SELECT claim_id FROM justifications WHERE justification_id=?",(p["justification_id"],)).fetchone()
            con.execute("UPDATE justifications SET active=0,event_key=? WHERE justification_id=?",
                        (e["event_key"],p["justification_id"]))
            if row:_recompute_claim(con,row[0])
        elif t=="TAXONOMY_NODE_PROPOSED":
            con.execute("INSERT OR REPLACE INTO taxonomy_nodes VALUES(?,?,?,?)",
                        (p["node_id"],p["label"],p.get("state","PROVISIONAL_NODE"),e["event_key"]))
        elif t=="TAXONOMY_NODE_STATE_CHANGED":
            con.execute("UPDATE taxonomy_nodes SET state=?,event_key=? WHERE node_id=?",
                        (p["state"],e["event_key"],p["node_id"]))
        elif t=="INTERPRETATION_PROVIDER_ELIGIBILITY_CHANGED":
            con.execute("INSERT OR REPLACE INTO provider_eligibility VALUES(?,?,?)",
                        (p["provider"],p["level"],e["event_key"]))
        elif t=="ANALOGY_HYPOTHESIS_CREATED":
            con.execute("INSERT OR REPLACE INTO intelligence_hypotheses VALUES(?,?,?,?)",
                        (p["hypothesis_id"],p.get("kind","STRUCTURAL_ANALOGY"),json.dumps(p,sort_keys=True),e["event_key"]))
        applied+=1
    con.commit();con.close()
    return {"events_applied":applied,"projection_hash":projection_hash(root)}

def projection_hash(root:Path):
    con=sqlite3.connect(root/DB);con.row_factory=sqlite3.Row
    tables=["evidence_spans","weak_anchors","granularity_routes","constraints_current","claims",
            "justifications","taxonomy_nodes","provider_eligibility","intelligence_hypotheses"]
    obj={}
    for t in tables:
        rows=[dict(r) for r in con.execute(f"SELECT * FROM {t} ORDER BY 1")]
        obj[t]=rows
    con.close()
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()

def summary(root:Path):
    con=sqlite3.connect(root/DB);con.row_factory=sqlite3.Row
    def one(q): return int(con.execute(q).fetchone()[0])
    anchors=[dict(r) for r in con.execute(
        "SELECT signature,COUNT(*) observations FROM weak_anchors GROUP BY signature ORDER BY observations DESC,signature LIMIT 20")]
    routes=[dict(r) for r in con.execute(
        "SELECT route,COUNT(*) observations FROM granularity_routes GROUP BY route ORDER BY observations DESC,route")]
    providers=[dict(r) for r in con.execute("SELECT * FROM provider_eligibility ORDER BY provider")]
    out={"active_evidence_spans":one("SELECT COUNT(*) FROM evidence_spans WHERE active=1"),
         "weak_anchor_observations":one("SELECT COUNT(*) FROM weak_anchors"),
         "distinct_weak_anchor_signatures":one("SELECT COUNT(DISTINCT signature) FROM weak_anchors"),
         "top_weak_anchor_groups":anchors,"granularity_routes":routes,"providers":providers,
         "projection_hash":projection_hash(root)}
    con.close();return out
