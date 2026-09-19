from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Mapping

from processors.signalforge_brain_v2_contracts import SCHEMA_VERSION, canonical_json, stable_hash

ENGINE_VERSION = "signalforge-brain-v2-store-full-system-g3-structural-recall"
EVENT_DB = Path(".radar_runtime/signalforge_brain_v2_full_events.sqlite3")
STATE_DB = Path(".radar_runtime/signalforge_brain_v2_full_state.sqlite3")

ALLOWED_EVENT_TYPES = {
    "OBJECT_UPSERT",
    "OBJECT_RETIRED",
    "DEPENDENCIES_REPLACED",
    "TRUTH_INPUTS_REPLACED",
    "MEANINGFUL_CHANGE_RECORDED",
    "RESEARCH_ATTEMPT_RECORDED",
    "REFRESH_CHECKPOINT",
}
OBJECT_TYPES = {
    "problem_atom",
    "transition_atom",
    "problem_lineage",
    "transition_hypothesis",
    "transition_lineage",
    "existing_system",
    "structural_bridge_hypothesis",
    "structural_intersection",
    "opportunity_thesis",
    "research_question",
}


COMPATIBLE_SCHEMA_VERSIONS = {
    "signalforge-brain-v2-full-system-g2",
    "signalforge-brain-v2-full-system-g3",
}

def _ensure_schema_meta(con: sqlite3.Connection) -> None:
    row = con.execute("SELECT v FROM meta WHERE k='schema'").fetchone()
    current = str(row[0]) if row is not None else ""
    if current and current not in COMPATIBLE_SCHEMA_VERSIONS:
        raise RuntimeError(f"BRAIN_SCHEMA_INCOMPATIBLE:{current}")
    con.execute("INSERT OR REPLACE INTO meta(k,v) VALUES('schema',?)", (SCHEMA_VERSION,))

EVENT_DDL = """
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT NOT NULL);
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
  authority TEXT NOT NULL,
  source_truth_fingerprint TEXT,
  payload_json TEXT NOT NULL,
  payload_sha256 TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_bv2full_events_stream ON events(stream_type,stream_id,event_id);
CREATE INDEX IF NOT EXISTS idx_bv2full_events_type ON events(event_type,event_id);
CREATE TRIGGER IF NOT EXISTS bv2full_events_no_update
BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT,'APPEND_ONLY_BRAIN_EVENTS_UPDATE_FORBIDDEN'); END;
CREATE TRIGGER IF NOT EXISTS bv2full_events_no_delete
BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT,'APPEND_ONLY_BRAIN_EVENTS_DELETE_FORBIDDEN'); END;
"""

STATE_DDL = """
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS objects(
  object_type TEXT NOT NULL,
  object_id TEXT NOT NULL,
  semantic_hash TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  event_key TEXT NOT NULL,
  PRIMARY KEY(object_type,object_id)
);
CREATE INDEX IF NOT EXISTS idx_bv2full_objects_type ON objects(object_type,object_id);
CREATE TABLE IF NOT EXISTS dependencies(
  from_type TEXT NOT NULL,
  from_id TEXT NOT NULL,
  to_type TEXT NOT NULL,
  to_id TEXT NOT NULL,
  relation TEXT NOT NULL,
  event_key TEXT NOT NULL,
  PRIMARY KEY(from_type,from_id,to_type,to_id,relation)
);
CREATE INDEX IF NOT EXISTS idx_bv2full_dep_to ON dependencies(to_type,to_id,from_type,from_id);
CREATE TABLE IF NOT EXISTS truth_inputs(
  unit_key TEXT PRIMARY KEY,
  fingerprint TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  event_key TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meaningful_changes(
  change_id TEXT PRIMARY KEY,
  payload_json TEXT NOT NULL,
  event_key TEXT NOT NULL
);
"""


def _event_path(root: Path) -> Path:
    return root / EVENT_DB


def _state_path(root: Path) -> Path:
    return root / STATE_DB


def connect_events(root: Path) -> sqlite3.Connection:
    p = _event_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p)
    try:
        con.row_factory = sqlite3.Row
        con.executescript(EVENT_DDL)
        _ensure_schema_meta(con)
        con.commit()
        return con
    except BaseException:
        # Constructor failures must not strand a live SQLite handle.  This matters
        # especially on Windows, where an unclosed handle prevents TemporaryDirectory
        # cleanup and can also pin a failed migration fixture on disk.
        con.close()
        raise


def connect_state(root: Path) -> sqlite3.Connection:
    p = _state_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p)
    try:
        con.row_factory = sqlite3.Row
        con.executescript(STATE_DDL)
        _ensure_schema_meta(con)
        con.execute("INSERT OR IGNORE INTO meta(k,v) VALUES('last_applied_event_id','0')")
        con.commit()
        return con
    except BaseException:
        # Fail-closed schema validation must still be resource-safe.  Returning no
        # connection means ownership stays here, so close before propagating.
        con.close()
        raise


def _validate_event(row: Mapping[str, Any]) -> None:
    t = str(row.get("event_type") or "")
    if t not in ALLOWED_EVENT_TYPES:
        raise ValueError(f"BRAIN_V2_UNKNOWN_EVENT_TYPE:{t}")
    if not str(row.get("stream_type") or "") or not str(row.get("stream_id") or ""):
        raise ValueError("BRAIN_V2_EVENT_STREAM_REQUIRED")
    if not isinstance(row.get("payload"), Mapping):
        raise ValueError("BRAIN_V2_EVENT_PAYLOAD_MUST_BE_OBJECT")


def _event_identity(row: Mapping[str, Any]) -> tuple[str, str, str]:
    payload = dict(row.get("payload") or {})
    payload_json = canonical_json(payload)
    payload_sha = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
    if str(row.get("event_type") or "") == "RESEARCH_ATTEMPT_RECORDED" and str(payload.get("attempt_key") or ""):
        # A scheduler retry of the same logical research attempt must be idempotent even
        # if wall-clock metadata differs.
        identity_part = "attempt:" + str(payload.get("attempt_key"))
    else:
        identity_part = payload_sha
    key = "bv2full_evt_" + stable_hash(
        SCHEMA_VERSION,
        row.get("stream_type"),
        row.get("stream_id"),
        row.get("event_type"),
        identity_part,
        length=40,
    )
    return key, payload_sha, payload_json


def _chunks(items: list[Any], size: int = 800) -> Iterable[list[Any]]:
    for i in range(0, len(items), size):
        yield items[i:i + size]


def append_events(
    root: Path,
    events: Iterable[Mapping[str, Any]],
    *,
    recorded_at: str,
    source_truth_fingerprint: str | None = None,
) -> dict[str, Any]:
    """Append a refresh batch without per-event read amplification.

    The prior implementation performed an idempotency SELECT and a MAX(stream_seq)
    SELECT for every event. A first longitudinal rebuild can legitimately emit thousands
    of events, so Windows/SQLite filesystem latency turned those O(events) round trips
    into a dominant wall-clock cost even when structural computation itself was fast.

    This implementation preserves the same append-only/event-key semantics while:
      * canonicalizing each payload once;
      * fetching existing event keys in bounded IN batches;
      * loading stream sequence heads once per transaction;
      * issuing only INSERT statements in the hot loop.
    """
    rows = [dict(x) for x in events]
    prepared: list[tuple[dict[str, Any], str, str, str]] = []
    for row in rows:
        _validate_event(row)
        event_key, payload_sha, payload_json = _event_identity(row)
        prepared.append((row, event_key, payload_sha, payload_json))

    inserted = 0
    skipped = 0
    con = connect_events(root)
    try:
        con.execute("BEGIN")

        keys = [x[1] for x in prepared]
        existing: set[str] = set()
        for chunk in _chunks(keys):
            if not chunk:
                continue
            marks = ",".join("?" for _ in chunk)
            existing.update(
                str(r[0])
                for r in con.execute(
                    f"SELECT event_key FROM events WHERE event_key IN ({marks})",
                    tuple(chunk),
                )
            )

        # Stream sequence is diagnostic ordering within a stream, not authority.
        # One grouped read is semantically equivalent to MAX(stream_seq) per event.
        stream_seq: dict[tuple[str, str], int] = {
            (str(r["stream_type"]), str(r["stream_id"])): int(r["max_seq"] or 0)
            for r in con.execute(
                "SELECT stream_type,stream_id,MAX(stream_seq) AS max_seq "
                "FROM events GROUP BY stream_type,stream_id"
            )
        }

        batch_seen: set[str] = set()
        for row, event_key, payload_sha, payload_json in prepared:
            if event_key in existing or event_key in batch_seen:
                skipped += 1
                continue
            batch_seen.add(event_key)

            stream_type = str(row["stream_type"])
            stream_id = str(row["stream_id"])
            stream = (stream_type, stream_id)
            seq = stream_seq.get(stream, 0) + 1
            stream_seq[stream] = seq

            cur = con.execute(
                """INSERT INTO events(event_key,stream_type,stream_id,stream_seq,event_type,schema_version,
                recorded_at,valid_at,producer,producer_version,producer_plane,authority,source_truth_fingerprint,
                payload_json,payload_sha256) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    event_key, stream_type, stream_id, seq, str(row["event_type"]), SCHEMA_VERSION,
                    recorded_at, row.get("valid_at"), "SignalForgeBrainV2", ENGINE_VERSION,
                    "LONGITUDINAL_DERIVED_INTELLIGENCE", "STRUCTURAL_PLANNING_ONLY_NO_RADAR_CLAIM_WRITE",
                    source_truth_fingerprint, payload_json, payload_sha,
                ),
            )
            inserted += int(cur.rowcount == 1)
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    return {"inserted": inserted, "skipped_existing": skipped, "attempted": len(rows)}


def _apply_event(con: sqlite3.Connection, event: Mapping[str, Any]) -> None:
    t = str(event["event_type"])
    p = json.loads(str(event["payload_json"]))
    event_key = str(event["event_key"])
    if t == "OBJECT_UPSERT":
        obj_type = str(p.get("object_type") or event["stream_type"])
        obj_id = str(p.get("object_id") or event["stream_id"])
        if obj_type not in OBJECT_TYPES:
            raise ValueError(f"UNKNOWN_OBJECT_TYPE:{obj_type}")
        payload = p.get("payload") if isinstance(p.get("payload"), Mapping) else {}
        semantic_hash = str(p.get("semantic_hash") or stable_hash(payload, length=40))
        con.execute(
            "INSERT OR REPLACE INTO objects(object_type,object_id,semantic_hash,payload_json,event_key) VALUES(?,?,?,?,?)",
            (obj_type, obj_id, semantic_hash, canonical_json(payload), event_key),
        )
    elif t == "OBJECT_RETIRED":
        obj_type = str(p.get("object_type") or event["stream_type"])
        obj_id = str(p.get("object_id") or event["stream_id"])
        con.execute("DELETE FROM objects WHERE object_type=? AND object_id=?", (obj_type, obj_id))
        con.execute("DELETE FROM dependencies WHERE (from_type=? AND from_id=?) OR (to_type=? AND to_id=?)", (obj_type, obj_id, obj_type, obj_id))
    elif t == "DEPENDENCIES_REPLACED":
        obj_type = str(p.get("from_type") or event["stream_type"])
        obj_id = str(p.get("from_id") or event["stream_id"])
        con.execute("DELETE FROM dependencies WHERE from_type=? AND from_id=?", (obj_type, obj_id))
        for edge in p.get("edges", []) if isinstance(p.get("edges"), list) else []:
            if not isinstance(edge, Mapping):
                continue
            to_type = str(edge.get("to_type") or "")
            to_id = str(edge.get("to_id") or "")
            relation = str(edge.get("relation") or "DEPENDS_ON")
            if to_type and to_id:
                con.execute(
                    "INSERT OR REPLACE INTO dependencies(from_type,from_id,to_type,to_id,relation,event_key) VALUES(?,?,?,?,?,?)",
                    (obj_type, obj_id, to_type, to_id, relation, event_key),
                )
    elif t == "TRUTH_INPUTS_REPLACED":
        con.execute("DELETE FROM truth_inputs")
        for item in p.get("items", []) if isinstance(p.get("items"), list) else []:
            if not isinstance(item, Mapping):
                continue
            key = str(item.get("unit_key") or "")
            fp = str(item.get("fingerprint") or "")
            if key and fp:
                con.execute(
                    "INSERT INTO truth_inputs(unit_key,fingerprint,payload_json,event_key) VALUES(?,?,?,?)",
                    (key, fp, canonical_json(dict(item.get("payload") or {})), event_key),
                )
    elif t == "MEANINGFUL_CHANGE_RECORDED":
        change_id = str(p.get("change_id") or event["stream_id"])
        con.execute(
            "INSERT OR REPLACE INTO meaningful_changes(change_id,payload_json,event_key) VALUES(?,?,?)",
            (change_id, canonical_json(p), event_key),
        )
    elif t == "RESEARCH_ATTEMPT_RECORDED":
        qid = str(p.get("research_question_id") or event["stream_id"])
        row = con.execute(
            "SELECT payload_json FROM objects WHERE object_type='research_question' AND object_id=?",
            (qid,),
        ).fetchone()
        if row is not None:
            payload = json.loads(str(row[0]))
            old_attempts = int(payload.get("attempts", 0) or 0)
            payload["attempts"] = old_attempts + 1
            try:
                old_voi = float(payload.get("voi", 0) or 0)
                payload["voi"] = round(old_voi * (1.0 + 0.40 * old_attempts) / (1.0 + 0.40 * payload["attempts"]), 6)
            except Exception:
                pass
            payload["redundancy_penalty"] = round(1.0 / (1.0 + 0.40 * payload["attempts"]), 4)
            payload["last_attempt_at"] = p.get("attempted_at")
            payload["last_attempt_status"] = p.get("result_status")
            history = list(payload.get("attempt_history") or [])[-11:]
            history.append({
                "attempt_key": p.get("attempt_key"),
                "attempted_at": p.get("attempted_at"),
                "source_group": p.get("source_group"),
                "result_status": p.get("result_status"),
            })
            payload["attempt_history"] = history
            con.execute(
                "UPDATE objects SET semantic_hash=?, payload_json=?, event_key=? WHERE object_type='research_question' AND object_id=?",
                (stable_hash(payload, length=40), canonical_json(payload), event_key, qid),
            )
    elif t == "REFRESH_CHECKPOINT":
        for key in ("truth_fingerprint", "refreshed_at", "engine_version", "status"):
            if key in p:
                con.execute("INSERT OR REPLACE INTO meta(k,v) VALUES(?,?)", (key, str(p.get(key) or "")))


def apply_pending_events(root: Path) -> dict[str, Any]:
    econ = connect_events(root)
    scon = connect_state(root)
    try:
        last = int(scon.execute("SELECT v FROM meta WHERE k='last_applied_event_id'").fetchone()[0])
        rows = [dict(r) for r in econ.execute("SELECT * FROM events WHERE event_id>? ORDER BY event_id", (last,))]
        if not rows:
            return {"applied": 0, "last_event_id": last}
        scon.execute("BEGIN")
        for event in rows:
            _apply_event(scon, event)
            last = int(event["event_id"])
        scon.execute("INSERT OR REPLACE INTO meta(k,v) VALUES('last_applied_event_id',?)", (str(last),))
        scon.commit()
        return {"applied": len(rows), "last_event_id": last}
    except Exception:
        scon.rollback()
        raise
    finally:
        econ.close()
        scon.close()


def read_events(root: Path) -> list[dict[str, Any]]:
    con = connect_events(root)
    try:
        return [dict(r) for r in con.execute("SELECT * FROM events ORDER BY event_id")]
    finally:
        con.close()


def count_events(root: Path) -> int:
    con = connect_events(root)
    try:
        return int(con.execute("SELECT COUNT(*) FROM events").fetchone()[0])
    finally:
        con.close()


def object_map(root: Path, object_type: str) -> dict[str, dict[str, Any]]:
    apply_pending_events(root)
    con = connect_state(root)
    try:
        out: dict[str, dict[str, Any]] = {}
        for r in con.execute("SELECT object_id,payload_json FROM objects WHERE object_type=? ORDER BY object_id", (object_type,)):
            out[str(r["object_id"])] = json.loads(str(r["payload_json"]))
        return out
    finally:
        con.close()


def get_object(root: Path, object_type: str, object_id: str) -> dict[str, Any] | None:
    apply_pending_events(root)
    con = connect_state(root)
    try:
        r = con.execute("SELECT payload_json FROM objects WHERE object_type=? AND object_id=?", (object_type, object_id)).fetchone()
        return json.loads(str(r[0])) if r else None
    finally:
        con.close()


def dependency_rows(root: Path) -> list[dict[str, Any]]:
    apply_pending_events(root)
    con = connect_state(root)
    try:
        return [dict(r) for r in con.execute("SELECT from_type,from_id,to_type,to_id,relation FROM dependencies ORDER BY 1,2,3,4,5")]
    finally:
        con.close()


def truth_input_map(root: Path) -> dict[str, dict[str, Any]]:
    apply_pending_events(root)
    con = connect_state(root)
    try:
        out = {}
        for r in con.execute("SELECT unit_key,fingerprint,payload_json FROM truth_inputs ORDER BY unit_key"):
            out[str(r["unit_key"])] = {"fingerprint": str(r["fingerprint"]), "payload": json.loads(str(r["payload_json"]))}
        return out
    finally:
        con.close()


def state_meta(root: Path) -> dict[str, str]:
    apply_pending_events(root)
    con = connect_state(root)
    try:
        return {str(r["k"]): str(r["v"]) for r in con.execute("SELECT k,v FROM meta ORDER BY k")}
    finally:
        con.close()


def meaningful_changes(root: Path, limit: int = 500) -> list[dict[str, Any]]:
    apply_pending_events(root)
    con = connect_state(root)
    try:
        rows = list(con.execute("SELECT payload_json FROM meaningful_changes ORDER BY rowid DESC LIMIT ?", (max(1, int(limit)),)))
        return [json.loads(str(r[0])) for r in rows]
    finally:
        con.close()


def state_snapshot(root: Path) -> dict[str, Any]:
    """Read the active projection with one apply pass and one state connection.

    Older code recursively called helpers that each re-ran apply_pending_events and
    reopened SQLite. That was correct but amplified filesystem latency during portfolio
    materialization. Keep public helper semantics unchanged while making the full snapshot
    a single coherent read transaction.
    """
    apply_pending_events(root)
    con = connect_state(root)
    try:
        objects: dict[str, list[dict[str, Any]]] = {t: [] for t in OBJECT_TYPES}
        for r in con.execute(
            "SELECT object_type,object_id,payload_json FROM objects ORDER BY object_type,object_id"
        ):
            typ = str(r["object_type"])
            if typ in objects:
                objects[typ].append(json.loads(str(r["payload_json"])))

        dependencies = [
            dict(r)
            for r in con.execute(
                "SELECT from_type,from_id,to_type,to_id,relation FROM dependencies "
                "ORDER BY 1,2,3,4,5"
            )
        ]
        truth_inputs: dict[str, dict[str, Any]] = {}
        for r in con.execute(
            "SELECT unit_key,fingerprint,payload_json FROM truth_inputs ORDER BY unit_key"
        ):
            truth_inputs[str(r["unit_key"])] = {
                "fingerprint": str(r["fingerprint"]),
                "payload": json.loads(str(r["payload_json"])),
            }
        changes = [
            json.loads(str(r[0]))
            for r in con.execute(
                "SELECT payload_json FROM meaningful_changes ORDER BY rowid DESC LIMIT 500"
            )
        ]
        meta = {str(r["k"]): str(r["v"]) for r in con.execute("SELECT k,v FROM meta ORDER BY k")}

        return {
            "problem_atoms": objects["problem_atom"],
            "transition_atoms": objects["transition_atom"],
            "problem_lineages": objects["problem_lineage"],
            "transition_hypotheses": objects["transition_hypothesis"],
            "transition_lineages": objects["transition_lineage"],
            "existing_systems": objects["existing_system"],
            "structural_bridge_hypotheses": objects["structural_bridge_hypothesis"],
            "structural_intersections": objects["structural_intersection"],
            "opportunity_theses": objects["opportunity_thesis"],
            "research_questions": objects["research_question"],
            "dependencies": dependencies,
            "meaningful_changes": changes,
            "truth_inputs": truth_inputs,
            "meta": meta,
        }
    finally:
        con.close()


def state_hash_from_snapshot(snap: Mapping[str, Any]) -> str:
    # Changes are historical and grow; exclude them from active projection determinism.
    active = {k: v for k, v in dict(snap).items() if k != "meaningful_changes"}
    return hashlib.sha256(canonical_json(active).encode("utf-8")).hexdigest()


def state_hash(root: Path) -> str:
    return state_hash_from_snapshot(state_snapshot(root))


def replay_projection(root: Path, target: Path | None = None) -> dict[str, Any]:
    target = target or _state_path(root).with_suffix(".replay.sqlite3")
    if target.exists():
        target.unlink()
    # Build a temporary root-like state DB path by replaying directly.
    target.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(target)
    con.row_factory = sqlite3.Row
    con.executescript(STATE_DDL)
    con.execute("INSERT OR REPLACE INTO meta(k,v) VALUES('schema',?)", (SCHEMA_VERSION,))
    last = 0
    try:
        for event in read_events(root):
            _apply_event(con, event)
            last = int(event["event_id"])
        con.execute("INSERT OR REPLACE INTO meta(k,v) VALUES('last_applied_event_id',?)", (str(last),))
        con.commit()
        obj = {}
        for table in ("objects", "dependencies", "truth_inputs"):
            obj[table] = [dict(r) for r in con.execute(f"SELECT * FROM {table} ORDER BY 1,2,3,4,5" if table == "dependencies" else f"SELECT * FROM {table} ORDER BY 1,2")]
        h = hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()
        return {"target": str(target), "events_applied": last, "active_hash": h}
    finally:
        con.close()


def _active_hash_from_state_db(path: Path) -> str:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    try:
        obj = {
            "objects": [dict(r) for r in con.execute("SELECT * FROM objects ORDER BY 1,2")],
            "dependencies": [dict(r) for r in con.execute("SELECT * FROM dependencies ORDER BY 1,2,3,4,5")],
            "truth_inputs": [dict(r) for r in con.execute("SELECT * FROM truth_inputs ORDER BY 1")],
        }
        return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()
    finally:
        con.close()


def static_acceptance(root: Path) -> dict[str, bool]:
    now = "2026-01-01T00:00:00Z"
    obj = {
        "stream_type":"problem_atom","stream_id":"pa1","event_type":"OBJECT_UPSERT",
        "payload":{"object_type":"problem_atom","object_id":"pa1","semantic_hash":"h1","payload":{"atom_id":"pa1","candidate_id":1}},
    }
    dep = {
        "stream_type":"problem_atom","stream_id":"pa1","event_type":"DEPENDENCIES_REPLACED",
        "payload":{"from_type":"problem_atom","from_id":"pa1","edges":[{"to_type":"problem_lineage","to_id":"pl1","relation":"MEMBER_OF"}]},
    }
    truth = {
        "stream_type":"truth_inputs","stream_id":"current","event_type":"TRUTH_INPUTS_REPLACED",
        "payload":{"items":[{"unit_key":"candidate:1","fingerprint":"f1","payload":{"candidate_id":1}}]},
    }
    first = append_events(root, [obj, dep, truth], recorded_at=now, source_truth_fingerprint="truth1")
    second = append_events(root, [obj, dep, truth], recorded_at=now, source_truth_fingerprint="truth1")
    applied = apply_pending_events(root)
    snap = state_snapshot(root)
    update_blocked = delete_blocked = False
    econ = connect_events(root)
    try:
        try:
            econ.execute("UPDATE events SET stream_id='tamper' WHERE event_id=1")
        except sqlite3.DatabaseError:
            update_blocked = True
            econ.rollback()
        try:
            econ.execute("DELETE FROM events WHERE event_id=1")
        except sqlite3.DatabaseError:
            delete_blocked = True
            econ.rollback()
    finally:
        econ.close()
    replay = replay_projection(root)
    current_active_hash = _active_hash_from_state_db(_state_path(root))
    replay_hash = _active_hash_from_state_db(Path(replay["target"]))
    retire = {
        "stream_type":"problem_atom","stream_id":"pa1","event_type":"OBJECT_RETIRED",
        "payload":{"object_type":"problem_atom","object_id":"pa1","reason":"fixture"},
    }
    append_events(root, [retire], recorded_at="2026-01-02T00:00:00Z", source_truth_fingerprint="truth2")
    apply_pending_events(root)
    after = state_snapshot(root)

    # Brain-only schema migration contract: installed G2 state is compatible and upgrades
    # in place; an unknown schema fails closed rather than being silently reinterpreted.
    compat_root = root / "schema_compat_g2"
    compat = connect_state(compat_root); compat.execute("INSERT OR REPLACE INTO meta(k,v) VALUES('schema','signalforge-brain-v2-full-system-g2')"); compat.commit(); compat.close()
    compat = connect_state(compat_root); compat_schema = str(compat.execute("SELECT v FROM meta WHERE k='schema'").fetchone()[0]); compat.close()
    bad_root = root / "schema_incompatible"
    bad = connect_state(bad_root); bad.execute("INSERT OR REPLACE INTO meta(k,v) VALUES('schema','signalforge-brain-v2-unknown-future')"); bad.commit(); bad.close()
    incompatible_blocked=False
    incompatible_handle_released=False
    try:
        bad=connect_state(bad_root); bad.close()
    except RuntimeError as exc:
        incompatible_blocked="BRAIN_SCHEMA_INCOMPATIBLE" in str(exc)
        # Windows regression guard: the failed constructor must have released its
        # SQLite handle, otherwise this unlink raises WinError 32 and the enclosing
        # TemporaryDirectory cannot clean up.  On POSIX this also verifies the file
        # remains independently manageable after the fail-closed path.
        bad_path = _state_path(bad_root)
        try:
            bad_path.unlink()
            incompatible_handle_released = True
        except (PermissionError, OSError):
            incompatible_handle_released = False

    return {
        "append_only_update_blocked": update_blocked,
        "append_only_delete_blocked": delete_blocked,
        "idempotent_event_append": first["inserted"] == 3 and second["inserted"] == 0,
        "incremental_apply_only_pending": applied["applied"] == 3,
        "projection_has_object": len(snap["problem_atoms"]) == 1,
        "dependency_materialized": len(snap["dependencies"]) == 1,
        "truth_input_materialized": "candidate:1" in snap["truth_inputs"],
        "replay_matches_active_state": current_active_hash == replay_hash,
        "retirement_removes_object": not after["problem_atoms"],
        "retirement_removes_dependencies": not after["dependencies"],
        "g2_schema_upgrades_to_g3": compat_schema == SCHEMA_VERSION,
        "unknown_schema_fails_closed": incompatible_blocked,
        "unknown_schema_releases_sqlite_handle": incompatible_handle_released,
    }
