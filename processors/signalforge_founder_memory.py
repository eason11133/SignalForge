"""SignalForge Part 2 — Founder Memory.

Founder Memory is deliberately *not* Market Truth.

It preserves hypotheses, questions, assumptions, decisions, rejected directions,
constraints and reasons in an append-only Founder-owned ledger.  The ledger has
zero authority over RadarClaim/C01-C14, Published evidence, calibration or any
other market-truth surface.

The module also produces two Founder-facing projections:
- Discussion Brief: Published market state and Founder reasoning shown side by side.
- Discussion Delta: what changed since the last explicit discussion checkpoint.

No LLM is required and no database write is performed here.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

ENGINE_VERSION = "signalforge-founder-memory-part2-v1"
SCHEMA_VERSION = 1
LEDGER_RELATIVE_PATH = Path(".radar_runtime/signalforge_founder_reasoning.jsonl")
TRUTH_BOUNDARY = "FOUNDER_REASONING_HAS_ZERO_MARKET_TRUTH_AUTHORITY"
MARKET_TRUTH_IMPACT = "NONE"
MARKET_AUTHORITY = "NONE"
FOUNDER_AUTHORITY = "FOUNDER"
GENESIS_HASH = "GENESIS"
LOCK_RELATIVE_PATH = Path(".radar_runtime/signalforge_founder_reasoning.lock")

ENTRY_TYPES = {
    "HYPOTHESIS",
    "QUESTION",
    "ASSUMPTION",
    "DECISION",
    "REJECTED_DIRECTION",
    "CONSTRAINT",
    "REASON",
}
REASON_REQUIRED_TYPES = {"DECISION", "REJECTED_DIRECTION"}

CLAIM_LABELS = {
    "C01": "Problem exists",
    "C02": "Independent recurrence",
    "C03": "Material consequence",
    "C04": "Actor identified",
    "C05": "Buyer / payer exists",
    "C06": "Current solution exists",
    "C07": "Unresolved gap",
    "C08": "Differentiation",
    "C09": "Founder / execution fit",
    "C10": "Reachable distribution",
    "C11": "Economics / WTP",
    "C12": "Timing window",
    "C13": "Competitive survivability",
    "C14": "Switch / pay behavior",
}

_LOCK = threading.RLock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(value: Any, *, max_len: int = 4000) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:max_len]


def _subject_key(value: str | None, thesis_id: str | None = None) -> str:
    raw = _clean(value or thesis_id or "", max_len=240).casefold()
    raw = re.sub(r"\s+", " ", raw).strip()
    if len(raw) < 2:
        raise ValueError("subject_key must contain at least 2 characters")
    return raw


def _ledger_path(root: Path | None = None) -> Path:
    base = Path(root) if root is not None else Path(".")
    return base / LEDGER_RELATIVE_PATH


def _lock_path(root: Path | None = None) -> Path:
    base = Path(root) if root is not None else Path(".")
    return base / LOCK_RELATIVE_PATH


def _canonical_payload(row: Mapping[str, Any]) -> bytes:
    data = {k: v for k, v in row.items() if k != "record_hash"}
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _record_hash(row: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_payload(row)).hexdigest()


def _load_records(root: Path | None = None) -> list[dict[str, Any]]:
    path = _ledger_path(root)
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    previous = GENESIS_HASH
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        raw = raw.strip()
        if not raw:
            continue
        try:
            row = json.loads(raw)
        except Exception as exc:
            raise RuntimeError(f"Founder Memory ledger corrupt at line {line_no}: invalid JSON: {exc}") from exc
        if not isinstance(row, dict):
            raise RuntimeError(f"Founder Memory ledger corrupt at line {line_no}: record is not an object")
        if row.get("schema_version") != SCHEMA_VERSION:
            raise RuntimeError(f"Founder Memory ledger corrupt at line {line_no}: unsupported schema_version={row.get('schema_version')!r}")
        if row.get("prev_hash") != previous:
            raise RuntimeError(f"Founder Memory ledger corrupt at line {line_no}: hash-chain predecessor mismatch")
        expected = _record_hash(row)
        if row.get("record_hash") != expected:
            raise RuntimeError(f"Founder Memory ledger corrupt at line {line_no}: record hash mismatch")
        previous = expected
        records.append(row)
    return records


def _write_records(records: list[dict[str, Any]], root: Path | None = None) -> None:
    path = _ledger_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str) for r in records)
    if payload:
        payload += "\n"
    tmp = path.with_name(path.name + f".tmp-{os.getpid()}-{secrets.token_hex(4)}")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)


def _append_record_locked(record: dict[str, Any], root: Path | None = None) -> dict[str, Any]:
    """Append while the caller already owns the shared cross-process mutation lock."""
    rows = _load_records(root)
    record = dict(record)
    record["schema_version"] = SCHEMA_VERSION
    record["prev_hash"] = rows[-1]["record_hash"] if rows else GENESIS_HASH
    record["record_hash"] = _record_hash(record)
    rows.append(record)
    _write_records(rows, root)
    # Read back through the validator while the shared process lock is held,
    # so an acknowledged write is durably present and hash-chain valid.
    verified = _load_records(root)
    if not verified or verified[-1].get("record_hash") != record["record_hash"]:
        raise RuntimeError("Founder Memory durable write verification failed")
    return dict(verified[-1])


def _append_record(record: dict[str, Any], root: Path | None = None) -> dict[str, Any]:
    # Keep the Part-5 closure's single lock identity.  Do not introduce a second
    # .jsonl.lock domain that could race with already-running FastAPI/MCP workers.
    from processors.signalforge_process_lock import cross_process_file_lock

    with _LOCK:
        with cross_process_file_lock(_lock_path(root), timeout=30.0):
            return _append_record_locked(record, root)


def _public_entry(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "entry_id": row.get("entry_id"),
        "subject_key": row.get("subject_key"),
        "subject_label": row.get("subject_label"),
        "thesis_id": row.get("thesis_id"),
        "entry_type": row.get("entry_type"),
        "statement": row.get("statement"),
        "reason": row.get("reason"),
        "source_ref": row.get("source_ref"),
        "tags": list(row.get("tags") or []),
        "created_at": row.get("created_at"),
        "authority": FOUNDER_AUTHORITY,
        "market_authority": MARKET_AUTHORITY,
        "market_truth_impact": MARKET_TRUTH_IMPACT,
        "validation_status": row.get("validation_status"),
        "truth_boundary": TRUTH_BOUNDARY,
    }


def record_founder_reasoning(
    *,
    subject_key: str,
    entry_type: str,
    statement: str,
    reason: str | None = None,
    thesis_id: str | None = None,
    subject_label: str | None = None,
    source_ref: str | None = None,
    tags: list[str] | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    key = _subject_key(subject_key, thesis_id)
    kind = _clean(entry_type, max_len=80).upper()
    if kind not in ENTRY_TYPES:
        raise ValueError(f"unsupported Founder Memory entry_type={kind!r}; allowed={sorted(ENTRY_TYPES)}")
    body = _clean(statement)
    if len(body) < 3:
        raise ValueError("statement must contain at least 3 characters")
    why = _clean(reason)
    if kind in REASON_REQUIRED_TYPES and len(why) < 3:
        raise ValueError(f"reason is required for {kind}")
    clean_tags = []
    seen: set[str] = set()
    for tag in tags or []:
        t = _clean(tag, max_len=80)
        if t and t.casefold() not in seen:
            seen.add(t.casefold())
            clean_tags.append(t)
    row = {
        "record_type": "ENTRY",
        "entry_id": f"fm_{secrets.token_hex(8)}",
        "subject_key": key,
        "subject_label": _clean(subject_label or subject_key, max_len=240),
        "thesis_id": _clean(thesis_id, max_len=240) or None,
        "entry_type": kind,
        "statement": body,
        "reason": why or None,
        "source_ref": _clean(source_ref, max_len=800) or None,
        "tags": clean_tags,
        "created_at": _now(),
        "authority": FOUNDER_AUTHORITY,
        "market_authority": MARKET_AUTHORITY,
        "market_truth_impact": MARKET_TRUTH_IMPACT,
        "validation_status": "UNVALIDATED_FOUNDER_REASONING" if kind in {"HYPOTHESIS", "QUESTION", "ASSUMPTION"} else "FOUNDER_DECISION_OR_CONTEXT_ONLY",
        "truth_boundary": TRUTH_BOUNDARY,
    }
    saved = _append_record(row, root)
    return {"status": "RECORDED", "entry": _public_entry(saved), "market_truth_writes": 0, "truth_boundary": TRUTH_BOUNDARY}


def list_founder_reasoning(
    *,
    subject_key: str | None = None,
    thesis_id: str | None = None,
    limit: int = 200,
    root: Path | None = None,
) -> dict[str, Any]:
    rows = _load_records(root)
    entries = [r for r in rows if r.get("record_type") == "ENTRY"]
    if subject_key or thesis_id:
        key = _subject_key(subject_key, thesis_id)
        entries = [r for r in entries if r.get("subject_key") == key or (thesis_id and r.get("thesis_id") == thesis_id)]
    entries = entries[-max(1, min(int(limit or 200), 1000)):]
    return {
        "engine_version": ENGINE_VERSION,
        "status": "PASS",
        "count": len(entries),
        "items": [_public_entry(r) for r in entries],
        "ledger_path": str(_ledger_path(root)),
        "append_only": True,
        "market_truth_writes": 0,
        "truth_boundary": TRUTH_BOUNDARY,
    }


def list_founder_memory_subjects(*, root: Path | None = None) -> dict[str, Any]:
    rows = [r for r in _load_records(root) if r.get("record_type") == "ENTRY"]
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row.get("subject_key") or "")
        if not key:
            continue
        current = grouped.setdefault(key, {
            "subject_key": key,
            "subject_label": row.get("subject_label") or key,
            "thesis_id": row.get("thesis_id"),
            "entry_count": 0,
            "last_entry_at": None,
            "latest_decision": None,
            "latest_question": None,
        })
        current["entry_count"] += 1
        current["subject_label"] = row.get("subject_label") or current["subject_label"]
        current["thesis_id"] = row.get("thesis_id") or current.get("thesis_id")
        current["last_entry_at"] = row.get("created_at")
        if row.get("entry_type") == "DECISION":
            current["latest_decision"] = row.get("statement")
        if row.get("entry_type") == "QUESTION":
            current["latest_question"] = row.get("statement")
    items = sorted(grouped.values(), key=lambda x: str(x.get("last_entry_at") or ""), reverse=True)
    return {"engine_version": ENGINE_VERSION, "count": len(items), "items": items, "truth_boundary": TRUTH_BOUNDARY}


def _published_market_snapshot(thesis_id: str | None) -> dict[str, Any]:
    tid = _clean(thesis_id, max_len=240)
    if not tid:
        return {
            "status": "NO_LINKED_PUBLISHED_THESIS",
            "thesis_id": None,
            "claim_states": {},
            "known": [],
            "contradicted": [],
            "unknown": [],
            "truth_boundary": "NO_FOUNDER_REASONING_PROMOTED_TO_MARKET_TRUTH",
        }
    try:
        from processors.signalforge_brain_v2_engine import get_brain_v2_portfolio
        portfolio = dict(get_brain_v2_portfolio())
    except Exception as exc:
        return {
            "status": "PUBLISHED_MARKET_SNAPSHOT_UNAVAILABLE",
            "thesis_id": tid,
            "claim_states": {},
            "known": [],
            "contradicted": [],
            "unknown": [],
            "error": f"{type(exc).__name__}: {exc}",
            "truth_boundary": "READ_FAILURE_DOES_NOT_PROMOTE_FOUNDER_REASONING",
        }
    thesis = next((dict(x) for x in portfolio.get("portfolio") or [] if isinstance(x, Mapping) and str(x.get("thesis_id") or "") == tid), None)
    if thesis is None:
        return {
            "status": "LINKED_THESIS_NOT_IN_CURRENT_PUBLISHED_PORTFOLIO",
            "thesis_id": tid,
            "claim_states": {},
            "known": [],
            "contradicted": [],
            "unknown": [],
            "truth_boundary": "MISSING_PUBLISHED_THESIS_REMAINS_UNKNOWN",
        }
    states = {str(k): str(v or "UNKNOWN").upper() for k, v in dict(thesis.get("claim_states") or {}).items() if str(k) in CLAIM_LABELS}
    for code in CLAIM_LABELS:
        states.setdefault(code, "UNKNOWN")
    known: list[dict[str, str]] = []
    contradicted: list[dict[str, str]] = []
    unknown: list[dict[str, str]] = []
    for code, label in CLAIM_LABELS.items():
        state = states.get(code, "UNKNOWN")
        row = {"claim_code": code, "label": label, "state": state}
        if state in {"SUPPORTED", "KNOWN"}:
            known.append(row)
        elif state in {"REFUTED", "CONTRADICTED"}:
            contradicted.append(row)
        else:
            unknown.append(row)
    return {
        "status": "PASS",
        "thesis_id": tid,
        "representative_title": thesis.get("representative_title"),
        "revision": thesis.get("revision"),
        "classification": thesis.get("classification"),
        "strategic_track": thesis.get("strategic_track"),
        "zip2_readiness": thesis.get("zip2_readiness"),
        "claim_states": states,
        "known": known,
        "contradicted": contradicted,
        "unknown": unknown,
        "truth_boundary": "PUBLISHED_BRAIN_STATE_READ_ONLY",
    }


def _entries_for_subject(rows: list[dict[str, Any]], key: str, thesis_id: str | None = None) -> list[dict[str, Any]]:
    return [
        r for r in rows
        if r.get("record_type") == "ENTRY" and (r.get("subject_key") == key or (thesis_id and r.get("thesis_id") == thesis_id))
    ]


def build_discussion_brief(
    *,
    subject_key: str,
    thesis_id: str | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    key = _subject_key(subject_key, thesis_id)
    rows = _load_records(root)
    entries = _entries_for_subject(rows, key, thesis_id)
    grouped: dict[str, list[dict[str, Any]]] = {kind: [] for kind in ENTRY_TYPES}
    for row in entries:
        kind = str(row.get("entry_type") or "")
        if kind in grouped:
            grouped[kind].append(_public_entry(row))
    market = _published_market_snapshot(thesis_id)
    latest_question = grouped["QUESTION"][-1] if grouped["QUESTION"] else None
    latest_decision = grouped["DECISION"][-1] if grouped["DECISION"] else None
    rejected = [
        {"statement": x.get("statement"), "reason": x.get("reason"), "created_at": x.get("created_at")}
        for x in grouped["REJECTED_DIRECTION"]
    ]
    do_not_discuss_again = []
    for x in grouped["REJECTED_DIRECTION"][-5:]:
        do_not_discuss_again.append({"type": "REJECTED_DIRECTION", "statement": x.get("statement"), "reason": x.get("reason")})
    # Preserve append-only decision history in founder_reasoning.decisions, while
    # active settled guidance uses only the latest decision so a superseded
    # decision is not simultaneously presented as current.
    if latest_decision:
        do_not_discuss_again.append({"type": "DECISION", "statement": latest_decision.get("statement"), "reason": latest_decision.get("reason")})
    return {
        "engine_version": ENGINE_VERSION,
        "status": "PASS",
        "subject": {
            "subject_key": key,
            "subject_label": (entries[-1].get("subject_label") if entries else subject_key),
            "thesis_id": thesis_id,
        },
        "market_truth": market,
        "founder_reasoning": {
            "hypotheses": grouped["HYPOTHESIS"],
            "assumptions": grouped["ASSUMPTION"],
            "questions": grouped["QUESTION"],
            "decisions": grouped["DECISION"],
            "rejected_directions": rejected,
            "constraints": grouped["CONSTRAINT"],
            "reasons": grouped["REASON"],
        },
        "current_decision_frontier": latest_question,
        "latest_founder_decision": latest_decision,
        "do_not_discuss_again": do_not_discuss_again,
        "entry_count": len(entries),
        "market_truth_writes": 0,
        "truth_boundary": "DISCUSSION_BRIEF_SEPARATES_PUBLISHED_MARKET_TRUTH_FROM_FOUNDER_REASONING",
    }


def _checkpoint_rows(rows: list[dict[str, Any]], key: str, thesis_id: str | None = None) -> list[dict[str, Any]]:
    return [
        r for r in rows
        if r.get("record_type") == "CHECKPOINT" and (r.get("subject_key") == key or (thesis_id and r.get("thesis_id") == thesis_id))
    ]


def create_discussion_checkpoint(
    *,
    subject_key: str,
    thesis_id: str | None = None,
    note: str | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    key = _subject_key(subject_key, thesis_id)
    market = _published_market_snapshot(thesis_id)
    from processors.signalforge_process_lock import cross_process_file_lock
    with _LOCK:
        with cross_process_file_lock(_lock_path(root), timeout=30.0):
            existing = _load_records(root)
            entries = _entries_for_subject(existing, key, thesis_id)
            record = {
                "record_type": "CHECKPOINT",
                "checkpoint_id": f"fmc_{secrets.token_hex(8)}",
                "subject_key": key,
                "subject_label": entries[-1].get("subject_label") if entries else _clean(subject_key, max_len=240),
                "thesis_id": _clean(thesis_id, max_len=240) or None,
                "created_at": _now(),
                "note": _clean(note) or None,
                "memory_entry_count": len(entries),
                "market_snapshot": market,
                "authority": FOUNDER_AUTHORITY,
                "market_authority": MARKET_AUTHORITY,
                "market_truth_impact": MARKET_TRUTH_IMPACT,
                "truth_boundary": TRUTH_BOUNDARY,
            }
            saved = _append_record_locked(record, root)
    return {
        "status": "CHECKPOINT_RECORDED",
        "checkpoint": {
            "checkpoint_id": saved.get("checkpoint_id"),
            "subject_key": key,
            "thesis_id": saved.get("thesis_id"),
            "created_at": saved.get("created_at"),
            "memory_entry_count": saved.get("memory_entry_count"),
            "note": saved.get("note"),
            "market_snapshot_status": (saved.get("market_snapshot") or {}).get("status"),
        },
        "market_truth_writes": 0,
        "truth_boundary": "CHECKPOINT_IS_FOUNDER_DISCUSSION_BASELINE_NOT_MARKET_TRUTH",
    }


def _market_delta(previous: Mapping[str, Any], current: Mapping[str, Any]) -> dict[str, Any]:
    before = dict(previous.get("claim_states") or {})
    after = dict(current.get("claim_states") or {})
    changed: list[dict[str, str]] = []
    newly_contradicted: list[dict[str, str]] = []
    for code in CLAIM_LABELS:
        a = str(before.get(code) or "UNKNOWN").upper()
        b = str(after.get(code) or "UNKNOWN").upper()
        if a != b:
            row = {"claim_code": code, "label": CLAIM_LABELS[code], "before": a, "after": b}
            changed.append(row)
            if b in {"REFUTED", "CONTRADICTED"}:
                newly_contradicted.append(row)
    meta_changed: list[dict[str, Any]] = []
    for field in ("classification", "strategic_track", "zip2_readiness", "revision"):
        if previous.get(field) != current.get(field):
            meta_changed.append({"field": field, "before": previous.get(field), "after": current.get(field)})
    return {
        "changed_claims": changed,
        "newly_contradicted": newly_contradicted,
        "metadata_changes": meta_changed,
        "changed": bool(changed or meta_changed),
    }


def build_discussion_delta(
    *,
    subject_key: str,
    thesis_id: str | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    key = _subject_key(subject_key, thesis_id)
    rows = _load_records(root)
    entries = _entries_for_subject(rows, key, thesis_id)
    checkpoints = _checkpoint_rows(rows, key, thesis_id)
    current_market = _published_market_snapshot(thesis_id)
    if not checkpoints:
        latest_question = next((_public_entry(x) for x in reversed(entries) if x.get("entry_type") == "QUESTION"), None)
        return {
            "engine_version": ENGINE_VERSION,
            "status": "NO_DISCUSSION_BASELINE",
            "subject_key": key,
            "baseline": None,
            "new_founder_reasoning": [_public_entry(x) for x in entries],
            "market_delta": {"changed": False, "changed_claims": [], "newly_contradicted": [], "metadata_changes": [], "reason": "NO_BASELINE"},
            "new_next_question": latest_question,
            "instruction": "Create a discussion checkpoint after you finish the current discussion; the next Delta will show only what changed after it.",
            "market_truth_writes": 0,
            "truth_boundary": "NO_BASELINE_DOES_NOT_INVENT_A_DELTA",
        }
    checkpoint = checkpoints[-1]
    # Locate the latest checkpoint in the global append-only sequence and only
    # treat later ENTRY records as new discussion memory.
    checkpoint_hash = checkpoint.get("record_hash")
    index = next((i for i, r in enumerate(rows) if r.get("record_hash") == checkpoint_hash), -1)
    after_rows = rows[index + 1:] if index >= 0 else []
    new_entries = [
        r for r in after_rows
        if r.get("record_type") == "ENTRY" and (r.get("subject_key") == key or (thesis_id and r.get("thesis_id") == thesis_id))
    ]
    market_delta = _market_delta(dict(checkpoint.get("market_snapshot") or {}), current_market)
    latest_question = next((_public_entry(x) for x in reversed(new_entries) if x.get("entry_type") == "QUESTION"), None)
    return {
        "engine_version": ENGINE_VERSION,
        "status": "PASS",
        "subject_key": key,
        "baseline": {
            "checkpoint_id": checkpoint.get("checkpoint_id"),
            "created_at": checkpoint.get("created_at"),
            "note": checkpoint.get("note"),
            "memory_entry_count": checkpoint.get("memory_entry_count"),
        },
        "new_founder_reasoning": [_public_entry(x) for x in new_entries],
        "market_delta": market_delta,
        "new_next_question": latest_question,
        "market_truth_writes": 0,
        "truth_boundary": "DISCUSSION_DELTA_COMPARES_APPEND_ONLY_FOUNDER_MEMORY_AND_READ_ONLY_PUBLISHED_MARKET_STATE",
    }


def founder_memory_status(*, root: Path | None = None) -> dict[str, Any]:
    try:
        rows = _load_records(root)
    except Exception as exc:
        return {
            "engine_version": ENGINE_VERSION,
            "status": "CORRUPT_OR_UNREADABLE",
            "error": f"{type(exc).__name__}: {exc}",
            "writable": False,
            "market_truth_writes": 0,
            "truth_boundary": TRUTH_BOUNDARY,
        }
    return {
        "engine_version": ENGINE_VERSION,
        "status": "PASS",
        "records": len(rows),
        "entries": sum(1 for r in rows if r.get("record_type") == "ENTRY"),
        "checkpoints": sum(1 for r in rows if r.get("record_type") == "CHECKPOINT"),
        "append_only": True,
        "hash_chain_verified": True,
        "writable": True,
        "market_truth_writes": 0,
        "truth_boundary": TRUTH_BOUNDARY,
    }
