from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

ENGINE_VERSION = "signalforge-founder-hypothesis-registry-live-closure-v1"
TRUTH_BOUNDARY = "FOUNDER_HYPOTHESIS_REGISTRY_IS_DURABLE_FOUNDER_REASONING_ONLY;_MARKET_AUTHORITY_NONE;_MARKET_TRUTH_WRITES_ZERO"


def _root(root: Path | None = None) -> Path:
    return Path(root or Path.cwd())


def _db_path(root: Path | None = None) -> Path:
    path = _root(root) / ".radar_runtime" / "signalforge_founder_hypotheses.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _connect(root: Path | None = None) -> sqlite3.Connection:
    con = sqlite3.connect(_db_path(root), timeout=30.0, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=FULL")
    con.execute("PRAGMA busy_timeout=30000")
    con.execute(
        """CREATE TABLE IF NOT EXISTS founder_hypotheses(
            hypothesis_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            provenance_type TEXT NOT NULL,
            market_authority TEXT NOT NULL,
            independent_market_recurrence_count INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_probe_json TEXT NOT NULL
        )"""
    )
    return con


def hypothesis_id(title: str, description: str = "") -> str:
    canonical = " ".join(f"{title} {description}".lower().split())
    return "fh_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


def record_founder_hypothesis_probe(*, title: str, description: str, probe: Mapping[str, Any], root: Path | None = None) -> dict[str, Any]:
    hid = hypothesis_id(title, description)
    now = datetime.now(timezone.utc).isoformat()
    snapshot = {
        "status": probe.get("status"),
        "fast_probe": probe.get("fast_probe") or {},
        "published_money_trail": probe.get("published_money_trail") or {},
        "decision_frontier": probe.get("decision_frontier") or {},
        "today": probe.get("today") or {},
        "market_truth_writes": 0,
    }
    payload = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, default=str)
    con = _connect(root)
    try:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute("SELECT created_at FROM founder_hypotheses WHERE hypothesis_id=?", (hid,)).fetchone()
        created = str(row["created_at"]) if row else now
        con.execute(
            """INSERT INTO founder_hypotheses(
                hypothesis_id,title,description,provenance_type,market_authority,independent_market_recurrence_count,created_at,updated_at,last_probe_json
            ) VALUES(?,?,?,?,?,?,?,?,?)
            ON CONFLICT(hypothesis_id) DO UPDATE SET
                title=excluded.title, description=excluded.description, updated_at=excluded.updated_at, last_probe_json=excluded.last_probe_json
            """,
            (hid, title, description, "FOUNDER_HYPOTHESIS", "NONE", 0, created, now, payload),
        )
        con.execute("COMMIT")
    except Exception:
        try:
            con.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        con.close()
    return {"hypothesis_id": hid, "status": "RECORDED", "provenance_type": "FOUNDER_HYPOTHESIS", "market_authority": "NONE", "independent_market_recurrence_count": 0, "market_truth_writes": 0, "truth_boundary": TRUTH_BOUNDARY}


def list_founder_hypotheses(*, limit: int = 100, root: Path | None = None) -> list[dict[str, Any]]:
    con = _connect(root)
    try:
        rows = con.execute("SELECT * FROM founder_hypotheses ORDER BY updated_at DESC LIMIT ?", (max(1, min(int(limit), 500)),)).fetchall()
    finally:
        con.close()
    out: list[dict[str, Any]] = []
    for row in rows:
        try:
            probe = json.loads(str(row["last_probe_json"] or "{}"))
        except Exception:
            probe = {"status": "CORRUPT_PROBE_SNAPSHOT_FAIL_VISIBLE"}
        out.append({
            "hypothesis_id": row["hypothesis_id"], "title": row["title"], "description": row["description"],
            "provenance_type": row["provenance_type"], "market_authority": row["market_authority"],
            "independent_market_recurrence_count": int(row["independent_market_recurrence_count"] or 0),
            "created_at": row["created_at"], "updated_at": row["updated_at"], "last_probe": probe,
            "market_truth_writes": 0, "truth_boundary": TRUTH_BOUNDARY,
        })
    return out


def registry_status(*, root: Path | None = None) -> dict[str, Any]:
    rows = list_founder_hypotheses(limit=500, root=root)
    return {"engine_version": ENGINE_VERSION, "status": "PASS", "count": len(rows), "market_truth_writes": 0, "truth_boundary": TRUTH_BOUNDARY}
