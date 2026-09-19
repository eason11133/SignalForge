"""SignalForge prospective validation/control cohort V2.

Creates and *freezes* pre-outcome treatment/control assignments so future
market results can measure selection lift without silently rematching controls
on every Founder Daily refresh.

Rules:
- existing treatment/control pairs are never rewritten after creation;
- new treatment cases may receive a new unused WATCH control;
- a control that later becomes selected is marked contaminated, not deleted;
- controls are never authorized for Founder action by this module;
- no market outcome or predictive accuracy is inferred here.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

ENGINE_VERSION = "validation-cohort-v2-frozen-prospective-control"
PATH = Path(".radar_runtime/validation_cohort.json")


def _score(row: dict[str, Any]) -> float:
    return float(row.get("attention_score", 0) or 0)


def _read_existing() -> dict[str, Any]:
    if not PATH.exists():
        return {}
    try:
        raw = json.loads(PATH.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _pair_id(treatment_id: int, control_id: int, frozen_at: str) -> str:
    raw = f"{treatment_id}|{control_id}|{frozen_at}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def build_validation_cohort(rows: list[dict[str, Any]], *, save: bool = True) -> dict[str, Any]:
    selected = [
        r for r in rows
        if str(r.get("market_validation_boundary") or "") in {
            "FOUNDER_ACTION_NOW", "PREBUILT_WAITING_FOR_VALIDATE"
        }
    ]
    selected_ids = {int(r.get("case_id") or 0) for r in selected}
    controls = [
        r for r in rows
        if str(r.get("decision_verdict") or "").upper() == "WATCH"
        and int(r.get("case_id") or 0) not in selected_ids
    ]

    existing = _read_existing()
    initial_created_at = str(existing.get("created_at") or datetime.utcnow().isoformat())
    existing_pairs = [
        dict(pair)
        for pair in (existing.get("matched_pairs") or [])
        if isinstance(pair, dict)
        and int(pair.get("treatment_case_id") or 0) > 0
        and int(pair.get("control_case_id") or 0) > 0
    ]

    # Migrate V1 pairs into immutable V2 records without changing their match.
    for pair in existing_pairs:
        frozen_at = str(pair.get("frozen_at") or initial_created_at)
        pair["frozen_at"] = frozen_at
        pair.setdefault(
            "pair_id",
            _pair_id(
                int(pair.get("treatment_case_id") or 0),
                int(pair.get("control_case_id") or 0),
                frozen_at,
            ),
        )
        pair.setdefault("outcome_known", False)
        pair["pair_status"] = "FROZEN_PRE_OUTCOME"

    paired_treatments = {
        int(pair.get("treatment_case_id") or 0) for pair in existing_pairs
    }
    used_controls = {
        int(pair.get("control_case_id") or 0) for pair in existing_pairs
    }

    new_pairs = []
    now = datetime.utcnow().isoformat()
    for treatment in sorted(
        selected,
        key=lambda r: (-_score(r), int(r.get("case_id") or 0)),
    ):
        tid = int(treatment.get("case_id") or 0)
        if tid in paired_treatments:
            continue

        available = [
            r for r in controls
            if int(r.get("case_id") or 0) not in used_controls
            and int(r.get("case_id") or 0) not in paired_treatments
        ]
        if not available:
            break

        control = min(
            available,
            key=lambda r: (
                abs(_score(treatment) - _score(r)),
                int(r.get("case_id") or 0),
            ),
        )
        cid = int(control.get("case_id") or 0)
        used_controls.add(cid)
        paired_treatments.add(tid)
        pair = {
            "pair_id": _pair_id(tid, cid, now),
            "frozen_at": now,
            "pair_status": "FROZEN_PRE_OUTCOME",
            "treatment_case_id": tid,
            "treatment_verdict": treatment.get("decision_verdict"),
            "treatment_boundary": treatment.get("market_validation_boundary"),
            "treatment_attention_at_freeze": _score(treatment),
            "control_case_id": cid,
            "control_verdict": control.get("decision_verdict"),
            "control_attention_at_freeze": _score(control),
            "attention_gap": round(abs(_score(treatment) - _score(control)), 3),
            "outcome_known": False,
        }
        existing_pairs.append(pair)
        new_pairs.append(pair)

    # Never rewrite an old assignment when the control later becomes selected.
    # Flag it so future comparative calibration can exclude contaminated pairs.
    for pair in existing_pairs:
        cid = int(pair.get("control_case_id") or 0)
        contaminated = cid in selected_ids
        pair["control_contaminated_by_later_selection"] = contaminated
        if contaminated:
            pair["pair_status"] = "FROZEN_CONTROL_LATER_SELECTED"
        elif pair.get("pair_status") != "FROZEN_PRE_OUTCOME":
            pair["pair_status"] = "FROZEN_PRE_OUTCOME"

    clean_pairs = [
        pair for pair in existing_pairs
        if not pair.get("control_contaminated_by_later_selection")
    ]

    result = {
        "engine_version": ENGINE_VERSION,
        "created_at": initial_created_at,
        "updated_at": now,
        "selection_policy": (
            "Frozen pre-outcome matching: when a case first enters Founder-action/"
            "prebuilt selection, pair it once with the nearest-attention unused WATCH "
            "control. Existing assignments are immutable. Later-selected controls are "
            "flagged contaminated rather than rematched."
        ),
        "selection_snapshot_frozen": True,
        "treatment_candidates": len(selected),
        "control_candidates": len(controls),
        "matched_pairs": existing_pairs,
        "clean_matched_pairs": len(clean_pairs),
        "contaminated_pairs": len(existing_pairs) - len(clean_pairs),
        "new_pairs_added": len(new_pairs),
        "market_truth_claimed": False,
        "predictive_accuracy_claimed": False,
    }
    if save:
        PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(PATH)
        result["snapshot_path"] = str(PATH)
    return result


def load_validation_cohort() -> dict[str, Any]:
    if not PATH.exists():
        return {
            "engine_version": ENGINE_VERSION,
            "selection_snapshot_frozen": True,
            "treatment_candidates": 0,
            "control_candidates": 0,
            "matched_pairs": [],
            "clean_matched_pairs": 0,
            "contaminated_pairs": 0,
            "market_truth_claimed": False,
            "predictive_accuracy_claimed": False,
        }
    try:
        raw = json.loads(PATH.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}
