from __future__ import annotations
import sqlite3
from pathlib import Path
from processors.discovery_knowledge_contracts_u23 import validate_event

DB=Path(".radar_runtime/discovery_knowledge_events_v1.sqlite3")

DDL="""
CREATE TABLE IF NOT EXISTS meta(
  k TEXT PRIMARY KEY,
  v TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events(
  event_id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_key TEXT NOT NULL UNIQUE,
  stream_type TEXT NOT NULL,
  stream_id TEXT NOT NULL,
  stream_seq INTEGER NOT NULL,
  event_type TEXT NOT NULL,
  schema_version TEXT NOT NULL,
  recorded_at TEXT NOT NULL,
  valid_at TEXT,
  producer TEXT NOT NULL,
  producer_version TEXT NOT NULL,
  producer_plane TEXT NOT NULL,
  source_observation_key TEXT,
  causation_event_key TEXT,
  correlation_id TEXT,
  payload_json TEXT NOT NULL,
  payload_sha256 TEXT NOT NULL,
  created_db_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_events_stream ON events(stream_type,stream_id,event_id);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type,event_id);
CREATE INDEX IF NOT EXISTS idx_events_obs ON events(source_observation_key,event_id);

CREATE TRIGGER IF NOT EXISTS events_no_update
BEFORE UPDATE ON events
BEGIN
  SELECT RAISE(ABORT,'APPEND_ONLY_EVENTS_UPDATE_FORBIDDEN');
END;

CREATE TRIGGER IF NOT EXISTS events_no_delete
BEFORE DELETE ON events
BEGIN
  SELECT RAISE(ABORT,'APPEND_ONLY_EVENTS_DELETE_FORBIDDEN');
END;
"""

def connect(root:Path):
    p=root/DB;p.parent.mkdir(parents=True,exist_ok=True)
    con=sqlite3.connect(p)
    con.row_factory=sqlite3.Row
    con.executescript(DDL)
    con.execute("INSERT OR IGNORE INTO meta(k,v) VALUES('schema','discovery_knowledge_events_v1')")
    con.commit()
    return con

def append_events(root:Path, events:list[dict]):
    con=connect(root);inserted=0;skipped=0
    try:
        con.execute("BEGIN")
        for e in events:
            validate_event(e)
            cur=con.execute("""INSERT OR IGNORE INTO events(
                event_key,stream_type,stream_id,stream_seq,event_type,schema_version,recorded_at,valid_at,
                producer,producer_version,producer_plane,source_observation_key,causation_event_key,
                correlation_id,payload_json,payload_sha256
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(
                e["event_key"],e["stream_type"],e["stream_id"],e["stream_seq"],e["event_type"],
                e["schema_version"],e["recorded_at"],e.get("valid_at"),e["producer"],e["producer_version"],
                e["producer_plane"],e.get("source_observation_key"),e.get("causation_event_key"),
                e.get("correlation_id"),e["payload_json"],e["payload_sha256"]))
            if cur.rowcount==1: inserted+=1
            else: skipped+=1
        con.commit()
    except Exception:
        con.rollback();raise
    finally:
        con.close()
    return {"inserted":inserted,"skipped_existing":skipped,"attempted":len(events)}

def read_events(root:Path):
    con=connect(root)
    rows=[dict(r) for r in con.execute("SELECT * FROM events ORDER BY event_id")]
    con.close()
    return rows

def count_events(root:Path):
    con=connect(root)
    n=con.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    con.close();return int(n)
