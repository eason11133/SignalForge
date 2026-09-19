"""Pre-registered longitudinal validation for SignalForge structural/Zip2 theses.

Structural predictions require time. A paid pilot can validate buyer behavior, but it cannot
prove that a technology/demand/institutional window persisted or that a Zip2-class thesis
was directionally correct. This registry freezes structural expectations before observation.
It never writes Radar C01-C14 truth.
"""
from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REGISTRY_PATH = Path(".radar_runtime/structural_validation_checkpoints.jsonl")
ENGINE_VERSION = "structural-validation-registry-r1"
RESULTS = {"STRENGTHENED", "PERSISTED", "WEAKENED", "INVALIDATED"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _load() -> list[dict[str, Any]]:
    if not REGISTRY_PATH.exists():
        return []
    out = []
    for line in REGISTRY_PATH.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
            if isinstance(row, dict): out.append(row)
        except Exception:
            pass
    return out


def _write(rows: list[dict[str, Any]]) -> None:
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text("".join(json.dumps(r, ensure_ascii=False, default=str)+"\n" for r in rows), encoding="utf-8")


def create_structural_checkpoint(*, thesis_id: str, horizon_days: int = 30, note: str | None = None) -> dict[str, Any]:
    if int(horizon_days) < 30:
        raise ValueError("structural horizon_days must be >= 30; short market tests belong to Fast Validation")
    from processors.signalforge_brain_v2_engine import get_thesis
    thesis = get_thesis(str(thesis_id))
    if not isinstance(thesis, dict):
        raise ValueError(f"thesis {thesis_id} not found")
    if str(thesis.get("zip2_readiness") or "").upper() not in {"ZIP2_HIGH_CONVICTION", "ZIP2_CANDIDATE"}:
        raise ValueError("structural checkpoint requires a current Zip2 candidate/high-conviction thesis")
    created = _now()
    cid = created.strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(3)
    dims = thesis.get("dimensions") or {}
    frozen = {
        "thesis_id": thesis.get("thesis_id"),
        "strategic_track": thesis.get("strategic_track"),
        "zip2_readiness": thesis.get("zip2_readiness"),
        "classification": thesis.get("classification"),
        "problem_lineage_id": thesis.get("problem_lineage_id"),
        "transition_lineage_id": thesis.get("transition_lineage_id"),
        "dimensions": {k: (v.get("state") if isinstance(v, dict) else v) for k, v in dims.items()},
        "founder_addressability_state": (thesis.get("founder_addressability") or {}).get("first_person_addressability_state"),
    }
    record = {
        "engine_version": ENGINE_VERSION,
        "checkpoint_id": cid,
        "created_at": created.isoformat(),
        "due_at": (created + timedelta(days=int(horizon_days))).isoformat(),
        "horizon_days": int(horizon_days),
        "status": "PENDING",
        "thesis_id": str(thesis_id),
        "pre_observation_snapshot": frozen,
        "observables": [
            "transition_strength_over_time",
            "legacy_system_mismatch_persistence",
            "buyer_formation_direction",
            "incumbent_response",
            "wedge_expansion_or_collapse",
        ],
        "note": note,
        "result": None,
        "evidence_refs": [],
        "truth_boundary": "Longitudinal calibration only; never writes atomic Radar market claims.",
    }
    rows = _load(); rows.append(record); _write(rows); return record


def complete_structural_checkpoint(*, checkpoint_id: str, result: str, evidence_refs: list[str], note: str) -> dict[str, Any]:
    result = str(result or "").upper()
    if result not in RESULTS:
        raise ValueError("result must be one of: " + ", ".join(sorted(RESULTS)))
    refs = [str(x).strip() for x in evidence_refs if str(x).strip()]
    if not refs:
        raise ValueError("at least one evidence_ref is required")
    if not str(note or "").strip():
        raise ValueError("note is required")
    rows = _load(); target = None
    for row in rows:
        if str(row.get("checkpoint_id")) != str(checkpoint_id): continue
        if str(row.get("status") or "").upper() != "PENDING":
            raise ValueError("structural checkpoint is already completed; outcomes are immutable")
        due = datetime.fromisoformat(str(row.get("due_at")))
        if _now() < due:
            raise ValueError(f"structural checkpoint is not due until {row.get('due_at')}")
        row.update({
            "status": "COMPLETED",
            "completed_at": _now().isoformat(),
            "result": result,
            "evidence_refs": refs,
            "result_note": str(note).strip(),
        })
        target = row; break
    if target is None: raise ValueError(f"checkpoint {checkpoint_id} not found")
    _write(rows); return target


def structural_registry_report() -> dict[str, Any]:
    rows = _load(); pending=[x for x in rows if x.get("status")=="PENDING"]; completed=[x for x in rows if x.get("status")=="COMPLETED"]
    return {"engine_version":ENGINE_VERSION,"total":len(rows),"pending":len(pending),"completed":len(completed),"rows":rows}


def static_acceptance() -> dict[str, bool]:
    return {"pre_registration_required": True, "minimum_horizon_enforced": True, "evidence_refs_required": True, "immutable_after_completion": True, "no_radar_truth_write": True}
