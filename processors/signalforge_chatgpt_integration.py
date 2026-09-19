"""SignalForge Part 5 — ChatGPT Integration + durability closure.

Authority paths remain deliberately separated:

READ / ANALYZE
    ChatGPT may search, probe, falsify, compare and request discussion packets.

WRITE / MODIFY (PENDING ARTIFACT ONLY)
    ChatGPT may PREPARE a durable pending Decision Artifact.  This is a persistent
    write and must be classified by an MCP host as a write/modify action.  It
    still has zero Market Truth authority and cannot confirm itself.

FOUNDER CONFIRMATION
    Only the SignalForge product surface may confirm a pending artifact.  That
    confirmation appends only to Part 2 Founder Memory.

Decision Artifact events are stored in SQLite using BEGIN IMMEDIATE transactions
so FastAPI and MCP processes cannot lose concurrent writes.  Existing JSONL
ledgers are migrated once, preserving their hash-chain records.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

ENGINE_VERSION = "signalforge-chatgpt-integration-part5-closure-v2"
SCHEMA_VERSION = 1
ARTIFACT_DB = Path(".radar_runtime/signalforge_chatgpt_decision_artifacts.sqlite3")
LEGACY_ARTIFACT_LEDGER = Path(".radar_runtime/signalforge_chatgpt_decision_artifacts.jsonl")
GENESIS_HASH = "GENESIS"
TRUTH_BOUNDARY = (
    "CHATGPT_MAY_READ_SIGNALFORGE_AND_PREPARE_DURABLE_PENDING_FOUNDER_REASONING_ARTIFACTS;_"
    "PREPARE_IS_A_WRITE_MODIFY_ACTION;_ONLY_EXPLICIT_FOUNDER_CONFIRMATION_MAY_APPEND_TO_FOUNDER_MEMORY;_"
    "MARKET_TRUTH_WRITE_AUTHORITY_IS_ALWAYS_ZERO"
)
MARKET_TRUTH_WRITES = 0

ARTIFACT_ENTRY_TYPES = {
    "HYPOTHESIS", "QUESTION", "ASSUMPTION", "DECISION", "REJECTED_DIRECTION", "CONSTRAINT", "REASON",
}
REASON_REQUIRED = {"DECISION", "REJECTED_DIRECTION"}
FORBIDDEN_KEYS = {
    "market_truth", "market_truth_state", "claim_state", "claim_states", "published_truth",
    "validation_status", "market_authority", "market_truth_impact",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(value: Any, *, max_len: int = 5000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:max_len]


def _db_path(root: Path | None = None) -> Path:
    return (Path(root) if root is not None else Path(".")) / ARTIFACT_DB


def _legacy_path(root: Path | None = None) -> Path:
    return (Path(root) if root is not None else Path(".")) / LEGACY_ARTIFACT_LEDGER


def _canonical_payload(row: Mapping[str, Any]) -> bytes:
    data = {k: v for k, v in row.items() if k != "record_hash"}
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _record_hash(row: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_payload(row)).hexdigest()


def _verify_event_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    verified: list[dict[str, Any]] = []
    previous = GENESIS_HASH
    for line_no, raw in enumerate(rows, start=1):
        row = dict(raw)
        if row.get("schema_version") != SCHEMA_VERSION:
            raise RuntimeError(f"Decision Artifact store corrupt at event {line_no}: unsupported schema")
        if row.get("prev_hash") != previous:
            raise RuntimeError(f"Decision Artifact store corrupt at event {line_no}: predecessor mismatch")
        expected = _record_hash(row)
        if row.get("record_hash") != expected:
            raise RuntimeError(f"Decision Artifact store corrupt at event {line_no}: record hash mismatch")
        previous = expected
        verified.append(row)
    return verified


def _read_legacy_events(root: Path | None = None) -> list[dict[str, Any]]:
    path = _legacy_path(root)
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
        except Exception as exc:
            raise RuntimeError(f"Decision Artifact legacy ledger corrupt at line {line_no}: invalid JSON: {exc}") from exc
        if not isinstance(row, dict):
            raise RuntimeError(f"Decision Artifact legacy ledger corrupt at line {line_no}: record is not an object")
        rows.append(row)
    return _verify_event_rows(rows)


def _connect(root: Path | None = None) -> sqlite3.Connection:
    path = _db_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS decision_artifact_events (
            seq INTEGER PRIMARY KEY AUTOINCREMENT,
            artifact_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            record_hash TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS ix_decision_artifact_events_artifact ON decision_artifact_events(artifact_id, seq)")
    _migrate_legacy_if_needed(conn, root)
    return conn


def _migrate_legacy_if_needed(conn: sqlite3.Connection, root: Path | None = None) -> None:
    legacy = _legacy_path(root)
    if not legacy.exists():
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        count = int(conn.execute("SELECT COUNT(*) FROM decision_artifact_events").fetchone()[0])
        if count == 0:
            for row in _read_legacy_events(root):
                conn.execute(
                    "INSERT INTO decision_artifact_events(artifact_id,event_type,payload_json,record_hash,created_at) VALUES(?,?,?,?,?)",
                    (
                        str(row.get("artifact_id") or ""), str(row.get("event_type") or ""),
                        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str),
                        str(row.get("record_hash") or ""), str(row.get("created_at") or ""),
                    ),
                )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def _load_events_on_conn(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for dbrow in conn.execute("SELECT payload_json FROM decision_artifact_events ORDER BY seq ASC"):
        try:
            payload = json.loads(str(dbrow["payload_json"]))
        except Exception as exc:
            raise RuntimeError(f"Decision Artifact SQLite store corrupt: invalid payload JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("Decision Artifact SQLite store corrupt: payload is not an object")
        rows.append(payload)
    return _verify_event_rows(rows)


def _load_events(root: Path | None = None) -> list[dict[str, Any]]:
    conn = _connect(root)
    try:
        return _load_events_on_conn(conn)
    finally:
        conn.close()


def _append_event_on_conn(conn: sqlite3.Connection, event: Mapping[str, Any]) -> dict[str, Any]:
    last = conn.execute("SELECT payload_json FROM decision_artifact_events ORDER BY seq DESC LIMIT 1").fetchone()
    previous = GENESIS_HASH
    if last is not None:
        previous_row = json.loads(str(last["payload_json"]))
        previous = str(previous_row.get("record_hash") or GENESIS_HASH)
    row = dict(event)
    row["schema_version"] = SCHEMA_VERSION
    row["prev_hash"] = previous
    row["record_hash"] = _record_hash(row)
    conn.execute(
        "INSERT INTO decision_artifact_events(artifact_id,event_type,payload_json,record_hash,created_at) VALUES(?,?,?,?,?)",
        (
            str(row.get("artifact_id") or ""), str(row.get("event_type") or ""),
            json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str),
            row["record_hash"], str(row.get("created_at") or ""),
        ),
    )
    return row


def _append_event(event: dict[str, Any], root: Path | None = None) -> dict[str, Any]:
    conn = _connect(root)
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = _append_event_on_conn(conn, event)
        conn.execute("COMMIT")
        verified = _load_events_on_conn(conn)
        if not verified or verified[-1].get("record_hash") != row["record_hash"]:
            raise RuntimeError("Decision Artifact durable SQLite write verification failed")
        return dict(verified[-1])
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        conn.close()


def _artifact_state(events: Sequence[Mapping[str, Any]], artifact_id: str) -> dict[str, Any] | None:
    matched = [dict(x) for x in events if str(x.get("artifact_id") or "") == artifact_id]
    if not matched:
        return None
    prepared = next((x for x in matched if x.get("event_type") == "PREPARED"), None)
    if not prepared:
        return None
    state = dict(prepared)
    state["status"] = "PENDING_FOUNDER_CONFIRMATION"
    state["founder_memory_entry_ids"] = []
    for row in matched[1:]:
        if row.get("event_type") == "CONFIRMED":
            state["status"] = "CONFIRMED_TO_FOUNDER_MEMORY"
            state["confirmed_at"] = row.get("created_at")
            state["founder_memory_entry_ids"] = list(row.get("founder_memory_entry_ids") or [])
        elif row.get("event_type") == "REJECTED":
            state["status"] = "REJECTED_BY_FOUNDER"
            state["rejected_at"] = row.get("created_at")
            state["rejection_reason"] = row.get("reason")
    return state


def _public_artifact(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "artifact_id": row.get("artifact_id"), "status": row.get("status"), "subject_key": row.get("subject_key"),
        "subject_label": row.get("subject_label"), "thesis_id": row.get("thesis_id"),
        "discussion_summary": row.get("discussion_summary"), "entries": list(row.get("entries") or []),
        "prepared_at": row.get("created_at"), "confirmed_at": row.get("confirmed_at"), "rejected_at": row.get("rejected_at"),
        "rejection_reason": row.get("rejection_reason"), "founder_memory_entry_ids": list(row.get("founder_memory_entry_ids") or []),
        "authority": "FOUNDER_CONFIRMATION_REQUIRED", "market_authority": "NONE", "market_truth_writes": 0,
        "operation_class": "WRITE_MODIFY_PENDING_ARTIFACT", "persistent_write": True, "truth_boundary": TRUTH_BOUNDARY,
    }


def _validate_entries(entries: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if not entries or len(entries) > 8:
        raise ValueError("Decision Artifact must contain 1-8 Founder reasoning entries")
    out: list[dict[str, Any]] = []
    for index, raw in enumerate(entries):
        if not isinstance(raw, Mapping):
            raise ValueError(f"entry {index} must be an object")
        forbidden = FORBIDDEN_KEYS.intersection({str(k).casefold() for k in raw.keys()})
        if forbidden:
            raise ValueError(f"entry {index} contains forbidden Market Truth fields: {sorted(forbidden)}")
        kind = _clean(raw.get("entry_type"), max_len=80).upper()
        if kind not in ARTIFACT_ENTRY_TYPES:
            raise ValueError(f"entry {index} has unsupported entry_type={kind!r}")
        statement = _clean(raw.get("statement"))
        if len(statement) < 3:
            raise ValueError(f"entry {index} statement must contain at least 3 characters")
        reason = _clean(raw.get("reason"))
        if kind in REASON_REQUIRED and len(reason) < 3:
            raise ValueError(f"entry {index} reason is required for {kind}")
        out.append({
            "entry_type": kind, "statement": statement, "reason": reason or None,
            "tags": [_clean(x, max_len=80) for x in (raw.get("tags") if isinstance(raw.get("tags"), list) else []) if _clean(x, max_len=80)][:12],
        })
    return out


def prepare_decision_artifact(*, subject_key: str, entries: Sequence[Mapping[str, Any]], subject_label: str | None = None,
                              thesis_id: str | None = None, discussion_summary: str | None = None,
                              source: str = "CHATGPT", root: Path | None = None) -> dict[str, Any]:
    key = _clean(subject_key or thesis_id, max_len=240).casefold()
    if len(key) < 2:
        raise ValueError("subject_key must contain at least 2 characters")
    clean_entries = _validate_entries(entries)
    row = _append_event({
        "event_type": "PREPARED", "artifact_id": f"da_{secrets.token_hex(8)}", "subject_key": key,
        "subject_label": _clean(subject_label or subject_key, max_len=240), "thesis_id": _clean(thesis_id, max_len=240) or None,
        "discussion_summary": _clean(discussion_summary) or None, "entries": clean_entries,
        "source": _clean(source, max_len=80) or "CHATGPT", "created_at": _now(), "authority": "FOUNDER_CONFIRMATION_REQUIRED",
        "market_authority": "NONE", "market_truth_writes": 0, "operation_class": "WRITE_MODIFY_PENDING_ARTIFACT",
        "truth_boundary": TRUTH_BOUNDARY,
    }, root)
    state = _artifact_state(_load_events(root), row["artifact_id"])
    return {"status": "PREPARED", "artifact": _public_artifact(state or row), "operation_class": "WRITE_MODIFY_PENDING_ARTIFACT", "market_truth_writes": 0, "truth_boundary": TRUTH_BOUNDARY}


def list_decision_artifacts(*, status: str | None = None, limit: int = 100, root: Path | None = None) -> dict[str, Any]:
    events = _load_events(root)
    ids: list[str] = []
    for row in events:
        aid = str(row.get("artifact_id") or "")
        if aid and aid not in ids:
            ids.append(aid)
    items = [_artifact_state(events, aid) for aid in ids]
    items = [x for x in items if x]
    if status:
        want = _clean(status, max_len=80).upper()
        items = [x for x in items if str(x.get("status") or "").upper() == want]
    items = items[-max(1, min(int(limit or 100), 500)):]
    return {
        "engine_version": ENGINE_VERSION, "status": "PASS", "count": len(items),
        "items": [_public_artifact(x) for x in reversed(items)], "append_only": True,
        "cross_process_safe": True, "storage": "SQLITE_BEGIN_IMMEDIATE_HASH_CHAIN",
        "market_truth_writes": 0, "truth_boundary": TRUTH_BOUNDARY,
    }


def confirm_decision_artifact(*, artifact_id: str, founder_confirmed: bool, root: Path | None = None) -> dict[str, Any]:
    if founder_confirmed is not True:
        raise ValueError("explicit Founder confirmation is required")
    aid = _clean(artifact_id, max_len=240)
    if not aid:
        raise ValueError("artifact_id is required")
    conn = _connect(root)
    try:
        # Hold the SQLite write transaction while checking state and appending the
        # corresponding Founder Memory entries.  This serializes confirms across
        # FastAPI/MCP processes.  Founder Memory itself also takes a process lock.
        conn.execute("BEGIN IMMEDIATE")
        events = _load_events_on_conn(conn)
        state = _artifact_state(events, aid)
        if not state:
            raise ValueError(f"Decision Artifact {aid!r} not found")
        if state.get("status") == "REJECTED_BY_FOUNDER":
            raise ValueError("rejected Decision Artifact cannot be confirmed")
        if state.get("status") == "CONFIRMED_TO_FOUNDER_MEMORY":
            conn.execute("COMMIT")
            return {"status": "ALREADY_CONFIRMED", "artifact": _public_artifact(state), "market_truth_writes": 0, "truth_boundary": TRUTH_BOUNDARY}

        from processors.signalforge_founder_memory import list_founder_reasoning, record_founder_reasoning
        existing = list_founder_reasoning(subject_key=str(state["subject_key"]), thesis_id=state.get("thesis_id"), limit=1000, root=root)
        existing_items = list(existing.get("items") or [])
        tag = f"decision_artifact:{aid}"
        entry_ids: list[str] = [str(x.get("entry_id")) for x in existing_items if tag in list(x.get("tags") or []) and x.get("entry_id")]
        for entry in state.get("entries") or []:
            already = next((x for x in existing_items if tag in list(x.get("tags") or []) and x.get("entry_type") == entry.get("entry_type") and x.get("statement") == entry.get("statement")), None)
            if already:
                if already.get("entry_id") and str(already.get("entry_id")) not in entry_ids:
                    entry_ids.append(str(already.get("entry_id")))
                continue
            saved = record_founder_reasoning(
                subject_key=str(state["subject_key"]), subject_label=state.get("subject_label"), thesis_id=state.get("thesis_id"),
                entry_type=str(entry.get("entry_type") or ""), statement=str(entry.get("statement") or ""), reason=entry.get("reason"),
                source_ref=f"CHATGPT_DECISION_ARTIFACT:{aid}", tags=[tag, "CHATGPT_DISCUSSION"] + [str(x) for x in (entry.get("tags") or [])], root=root,
            )
            entry_id = ((saved.get("entry") or {}).get("entry_id"))
            if entry_id:
                entry_ids.append(str(entry_id))
            existing_items.append(saved.get("entry") or {})
        _append_event_on_conn(conn, {
            "event_type": "CONFIRMED", "artifact_id": aid, "founder_memory_entry_ids": entry_ids, "created_at": _now(),
            "authority": "FOUNDER_EXPLICIT_CONFIRMATION", "market_authority": "NONE", "market_truth_writes": 0,
            "truth_boundary": TRUTH_BOUNDARY,
        })
        conn.execute("COMMIT")
        final = _artifact_state(_load_events_on_conn(conn), aid)
        return {"status": "CONFIRMED", "artifact": _public_artifact(final or state), "market_truth_writes": 0, "truth_boundary": TRUTH_BOUNDARY}
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        conn.close()


def reject_decision_artifact(*, artifact_id: str, reason: str | None = None, root: Path | None = None) -> dict[str, Any]:
    aid = _clean(artifact_id, max_len=240)
    conn = _connect(root)
    try:
        conn.execute("BEGIN IMMEDIATE")
        events = _load_events_on_conn(conn)
        state = _artifact_state(events, aid)
        if not state:
            raise ValueError(f"Decision Artifact {aid!r} not found")
        if state.get("status") == "CONFIRMED_TO_FOUNDER_MEMORY":
            raise ValueError("confirmed Decision Artifact cannot be rejected")
        if state.get("status") == "REJECTED_BY_FOUNDER":
            conn.execute("COMMIT")
            return {"status": "ALREADY_REJECTED", "artifact": _public_artifact(state), "market_truth_writes": 0, "truth_boundary": TRUTH_BOUNDARY}
        _append_event_on_conn(conn, {
            "event_type": "REJECTED", "artifact_id": aid, "reason": _clean(reason) or None, "created_at": _now(),
            "authority": "FOUNDER_REJECTION", "market_authority": "NONE", "market_truth_writes": 0, "truth_boundary": TRUTH_BOUNDARY,
        })
        conn.execute("COMMIT")
        final = _artifact_state(_load_events_on_conn(conn), aid)
        return {"status": "REJECTED", "artifact": _public_artifact(final or state), "market_truth_writes": 0, "truth_boundary": TRUTH_BOUNDARY}
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        conn.close()

async def build_discussion_packet(thesis_id: str) -> dict[str, Any]:
    tid = _clean(thesis_id, max_len=240)
    if not tid:
        raise ValueError("thesis_id is required")
    from processors.signalforge_brain_v2_engine import get_brain_v2_portfolio
    from processors.signalforge_money_trail import build_money_trail_for_thesis
    from processors.signalforge_trust_falsification import evidence_replay
    from processors.signalforge_opportunity_decision_closure import decorate_item
    from processors.signalforge_opportunity_decision import build_decision_item
    from processors.signalforge_founder_memory import build_discussion_brief, build_discussion_delta

    portfolio = dict(get_brain_v2_portfolio())
    thesis = next((dict(x) for x in (portfolio.get("portfolio") or []) if str(x.get("thesis_id") or "") == tid), None)
    if thesis is None:
        return {"status": "THESIS_NOT_FOUND", "thesis_id": tid, "market_truth_writes": 0, "truth_boundary": TRUTH_BOUNDARY}
    trail = await build_money_trail_for_thesis(thesis)
    replay = await evidence_replay(tid)
    decision = decorate_item(thesis, trail, build_decision_item(thesis, trail))
    subject_key = _clean(thesis.get("representative_title") or thesis.get("title") or tid, max_len=240).casefold()
    try:
        brief = build_discussion_brief(subject_key=subject_key, thesis_id=tid)
    except Exception as exc:
        brief = {"status": "FOUNDER_MEMORY_UNAVAILABLE", "error": f"{type(exc).__name__}: {exc}"}
    try:
        delta = build_discussion_delta(subject_key=subject_key, thesis_id=tid)
    except Exception as exc:
        delta = {"status": "NO_EXPLICIT_DISCUSSION_BASELINE", "error": f"{type(exc).__name__}: {exc}"}
    return {
        "engine_version": ENGINE_VERSION,
        "status": "PASS",
        "thesis_id": tid,
        "published_market_truth": {
            "title": thesis.get("representative_title") or thesis.get("title"),
            "problem": thesis.get("problem") or thesis.get("problem_statement"),
            "claim_states": dict(thesis.get("claim_states") or {}),
            "classification": thesis.get("classification"),
            "strategic_track": thesis.get("strategic_track"),
            "zip2_readiness": thesis.get("zip2_readiness"),
        },
        "money_trail": trail,
        "evidence_replay": replay,
        "decision_projection": decision,
        "founder_discussion_brief": brief,
        "since_last_discussion": delta,
        "instructions_for_chatgpt": [
            "Treat Published Market Truth and Founder Reasoning as separate authority domains.",
            "Do not promote Founder hypotheses into Market Truth.",
            "If discussion reaches a decision, prepare a Decision Artifact; do not claim it is written until Founder confirms it in SignalForge.",
        ],
        "market_truth_writes": 0,
        "truth_boundary": TRUTH_BOUNDARY,
    }


async def search_signalforge_for_chatgpt(q: str, *, weekly_hours: float = 10.0, cash_need: str = "HIGH", long_term: str = "HIGH") -> dict[str, Any]:
    from processors.signalforge_opportunity_decision_closure import ask_current_signalforge_closure
    return await ask_current_signalforge_closure(q, weekly_hours=weekly_hours, cash_need=cash_need, long_term=long_term)


async def probe_idea_for_chatgpt(title: str, description: str = "") -> dict[str, Any]:
    from processors.signalforge_founder_idea_loop import probe_founder_idea
    return await probe_founder_idea(title=title, description=description)


async def falsify_for_chatgpt(*, title: str, description: str = "", thesis_id: str | None = None) -> dict[str, Any]:
    from processors.signalforge_trust_falsification import falsify_direction
    return await falsify_direction(title=title, description=description, thesis_id=thesis_id)


async def compare_for_chatgpt(thesis_ids: Sequence[str], *, weekly_hours: float = 10.0, cash_need: str = "HIGH", long_term: str = "HIGH") -> dict[str, Any]:
    from processors.signalforge_opportunity_decision_closure import compare_theses_closure
    return await compare_theses_closure(thesis_ids, weekly_hours=weekly_hours, cash_need=cash_need, long_term=long_term)


def integration_status() -> dict[str, Any]:
    try:
        artifact_status = list_decision_artifacts(limit=1)
        artifact_ok = artifact_status.get("status") == "PASS"
    except Exception as exc:
        artifact_ok = False
        artifact_status = {"status": "FAIL", "error": f"{type(exc).__name__}: {exc}"}
    try:
        import mcp  # type: ignore  # noqa: F401
        mcp_dependency = "AVAILABLE"
    except Exception:
        mcp_dependency = "OPTIONAL_DEPENDENCY_NOT_INSTALLED"
    return {
        "engine_version": ENGINE_VERSION,
        "status": "PASS" if artifact_ok else "FAIL",
        "engineering_acceptance": "PASS" if artifact_ok else "FAIL",
        "live_chatgpt_acceptance": "PLATFORM_BLOCKED_OR_LIVE_ACCEPTANCE_PENDING",
        "mcp_adapter": "SOURCE_AVAILABLE",
        "mcp_python_dependency": mcp_dependency,
        "supported_deployment_mode": "SECURE_MCP_TUNNEL_ONLY",
        "public_remote_endpoint": "NOT_SUPPORTED_UNAUTHENTICATED",
        "chatgpt_connection_requirement": "REMOTE_MCP_REQUIRED;_LOCALHOST_NOT_DIRECT;_SIGNALFORGE_SUPPORTS_SECURE_MCP_TUNNEL_ONLY_UNTIL_AUTHENTICATED_REMOTE_DEPLOYMENT_IS_IMPLEMENTED",
        "tool_permission_contract": {
            "signalforge_search": "READ",
            "signalforge_get_thesis": "READ",
            "signalforge_probe_idea": "READ_EXTERNAL_NO_PERSISTENT_WRITE",
            "signalforge_falsify": "READ_EXTERNAL_NO_PERSISTENT_WRITE",
            "signalforge_compare": "READ",
            "signalforge_prepare_decision_artifact": "WRITE_MODIFY_PENDING_ARTIFACT",
            "signalforge_pending_decision_artifacts": "READ",
        },
        "writeback_policy": "MCP_CAN_PREPARE_PERSISTENT_PENDING_ARTIFACT_BUT_CANNOT_CONFIRM;_FOUNDER_CONFIRMS_IN_SIGNALFORGE_UI",
        "artifact_store": artifact_status,
        "market_truth_writes": 0,
        "truth_boundary": TRUTH_BOUNDARY,
    }

