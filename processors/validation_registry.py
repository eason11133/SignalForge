"""SignalForge pre-registered validation experiments V2.

A real-market result is clean ground truth only when:
- the experiment was registered before the result,
- the case / claim / event match the registration,
- the experiment is still pending,
- the immutable pre-test decision snapshot is preserved.

This closes the previous bypass where an unregistered result could still create
claim SUPPORT.
"""

from __future__ import annotations

import json
import secrets
from datetime import datetime
from pathlib import Path
from typing import Any

from processors.signalforge_process_lock import cross_process_file_lock


ENGINE_VERSION = "validation-registry-v2-quality-locked"
REGISTRY_PATH = Path(".radar_runtime/validation_experiments.jsonl")
REGISTRY_LOCK_PATH = Path(".radar_runtime/validation_experiments.lock")

CLAIM_EVENT = {
    "C10": "ACQUISITION",
    "C11": "PRICE",
    "C14": "SWITCH",
}


def _load_rows() -> list[dict[str, Any]]:
    if not REGISTRY_PATH.exists():
        return []
    rows = []
    for line in REGISTRY_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _rewrite(rows: list[dict[str, Any]]) -> None:
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = "\n".join(
        json.dumps(row, ensure_ascii=False, default=str)
        for row in rows
    )
    if payload:
        payload += "\n"
    tmp = REGISTRY_PATH.with_suffix(".tmp")
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(REGISTRY_PATH)




def _brain_strategy_snapshot(candidate_id: int) -> dict[str, Any]:
    """Best-effort read-only strategic snapshot for future calibration.

    Validation remains legal when Brain is unavailable; the missing strategic snapshot is
    explicit and future Founder-addressability/structural calibration will exclude it.
    """
    try:
        from processors.signalforge_brain_v2_engine import get_brain_v2_portfolio
        p = dict(get_brain_v2_portfolio())
        for thesis in list(p.get("portfolio") or []):
            members = {int(x) for x in (thesis.get("member_candidate_ids") or []) if str(x).isdigit()}
            if int(candidate_id) not in members:
                continue
            addr = thesis.get("founder_addressability") or {}
            return {
                "status": "CAPTURED",
                "brain_engine_version": p.get("engine_version"),
                "thesis_id": thesis.get("thesis_id"),
                "strategic_track": thesis.get("strategic_track"),
                "zip2_readiness": thesis.get("zip2_readiness"),
                "first_person_addressability_state": addr.get("first_person_addressability_state"),
                "founder_addressability": addr,
                "fast_validation": thesis.get("fast_validation") or {},
                "best_next_action": thesis.get("best_next_action") or {},
                "truth_boundary": "Derived strategic snapshot only; it does not alter Radar market truth.",
            }
        return {"status": "NO_MATCHING_BRAIN_THESIS"}
    except Exception as exc:
        return {"status": "BRAIN_UNAVAILABLE", "reason": f"{type(exc).__name__}: {exc}"}


def get_validation_experiment(
    experiment_id: str,
) -> dict[str, Any] | None:
    for row in _load_rows():
        if str(row.get("experiment_id")) == str(experiment_id):
            return row
    return None


async def create_validation_experiment(
    *,
    case_id: int,
    claim_code: str,
    note: str | None = None,
    market_action_id: str | None = None,
) -> dict[str, Any]:
    claim_code = str(claim_code or "").upper()
    if claim_code not in CLAIM_EVENT:
        raise ValueError("claim_code must be C10, C11, or C14")

    from processors.opportunity_decision import run_opportunity_decision
    decision = await run_opportunity_decision(limit=50)
    row = next(
        (
            item for item in decision.get("rows", [])
            if int(item.get("case_id") or 0) == int(case_id)
        ),
        None,
    )
    if row is None:
        raise ValueError(f"case {case_id} not found")

    if str(row.get("market_validation_boundary") or "") != "FOUNDER_ACTION_NOW":
        raise ValueError(
            f"case {case_id} is not authorized for Founder market action; "
            f"current boundary={row.get('market_validation_boundary')} "
            f"gate={row.get('current_gate')}"
        )

    plan = (
        (row.get("prepared_validation_plans") or {}).get(claim_code)
        or (
            ((row.get("floor60_reality") or {}).get("packets") or {})
            .get(claim_code, {})
            .get("experiment")
        )
    )
    if not plan:
        raise ValueError(
            f"case {case_id} has no prepared {claim_code} validation plan"
        )

    experiment_id = (
        datetime.utcnow().strftime("%Y%m%dT%H%M%S")
        + "-"
        + secrets.token_hex(3)
    )

    record = {
        "engine_version": ENGINE_VERSION,
        "experiment_id": experiment_id,
        "created_at": datetime.utcnow().isoformat(),
        "case_id": int(case_id),
        "title": row.get("title"),
        "claim_code": claim_code,
        "event": CLAIM_EVENT[claim_code],
        "status": "PENDING",
        "pretest_snapshot": {
            "candidate_id": row.get("candidate_id"),
            "decision_verdict": row.get("decision_verdict"),
            "decision_reason": row.get("decision_reason"),
            "current_gate": row.get("current_gate"),
            "attention_score": int(row.get("attention_score", 0) or 0),
            "claims": dict(row.get("claims") or {}),
            "market_validation_boundary": row.get(
                "market_validation_boundary"
            ),
            "engine_version": decision.get("engine_version"),
            "strategic_snapshot": _brain_strategy_snapshot(int(row.get("candidate_id") or 0)),
        },
        "plan": plan,
        "note": note,
        "market_action_id": str(market_action_id or "").strip() or None,
        "result": None,
        "completed_at": None,
        "actor_label": None,
    }

    with cross_process_file_lock(REGISTRY_LOCK_PATH):
        rows = _load_rows()
        rows.append(record)
        _rewrite(rows)
    return record


def complete_validation_experiment(
    *,
    experiment_id: str,
    result: str,
    note: str,
    amount: float | None = None,
    currency: str | None = None,
    actor_label: str | None = None,
) -> dict[str, Any] | None:
    result = str(result or "").upper()
    if result not in {"PASS", "FAIL"}:
        raise ValueError("result must be PASS or FAIL")

    with cross_process_file_lock(REGISTRY_LOCK_PATH):
        rows = _load_rows()
        found = None

        for row in rows:
            if str(row.get("experiment_id")) != str(experiment_id):
                continue

            if str(row.get("status") or "").upper() != "PENDING":
                raise ValueError(
                    f"experiment {experiment_id} is already "
                    f"{row.get('status')}; results are immutable"
                )

            row["status"] = "COMPLETED"
            row["result"] = result
            row["result_note"] = note
            row["amount"] = amount
            row["currency"] = currency
            row["actor_label"] = actor_label
            row["completed_at"] = datetime.utcnow().isoformat()
            found = row
            break

        if found is not None:
            _rewrite(rows)
        return found


def validation_registry_report() -> dict[str, Any]:
    rows = _load_rows()
    pending = [row for row in rows if row.get("status") == "PENDING"]
    completed = [row for row in rows if row.get("status") == "COMPLETED"]
    return {
        "engine_version": ENGINE_VERSION,
        "total": len(rows),
        "pending": len(pending),
        "completed": len(completed),
        "rows": rows,
    }
