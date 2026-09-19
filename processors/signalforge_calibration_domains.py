"""SignalForge split calibration domains.

Market outcomes are not interchangeable evidence. This module separates:
1) fast-validation behavior,
2) structural/Zip2 longitudinal validation,
3) Founder-addressability calibration.

It never manufactures accuracy. Existing experiments without the new pre-test strategic
snapshot remain usable for atomic market truth, but are excluded from the newer calibration
subsets whose prerequisites they do not satisfy.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from processors.validation_registry import validation_registry_report
from processors.structural_validation_registry import structural_registry_report
from processors.signalforge_market_action_registry import calibration_eligible_outcomes

ENGINE_VERSION = "signalforge-split-calibration-r2-r5-market-action-aware"
MIN_FAST_OUTCOMES = 8
MIN_FAST_CASES = 4
MIN_ADDRESSABILITY_OUTCOMES = 8
MIN_ADDRESSABILITY_CASES = 4


def _completed() -> list[dict[str, Any]]:
    rows = validation_registry_report().get("rows") or []
    return [
        row for row in rows
        if str(row.get("status") or "").upper() == "COMPLETED"
        and str(row.get("result") or "").upper() in {"PASS", "FAIL"}
        and isinstance(row.get("pretest_snapshot"), dict)
    ]


def calibration_domains_report() -> dict[str, Any]:
    validation_rows = _completed()
    action_rows = calibration_eligible_outcomes()

    fast_rows: list[dict[str, Any]] = []
    addressability_rows: list[dict[str, Any]] = []

    for row in validation_rows:
        snap = row.get("pretest_snapshot") or {}
        strategy = snap.get("strategic_snapshot") or {}
        track = str(strategy.get("strategic_track") or "").upper()
        wrapped = {**row, "calibration_source": "RADAR_VALIDATION_EXPERIMENT", "strategy_snapshot": strategy}
        if track in {"FAST_VALIDATION", "BOTH"}:
            fast_rows.append(wrapped)
        first_person = str(strategy.get("first_person_addressability_state") or "").upper()
        if first_person in {"SUPPORTED", "PARTIAL", "INSUFFICIENT", "UNKNOWN", "REFUTED"}:
            addressability_rows.append(wrapped)

    for row in action_rows:
        strategy = row.get("pretest_snapshot") or {}
        track = str(strategy.get("strategic_track") or "").upper()
        quality = row.get("outcome_quality") if isinstance(row.get("outcome_quality"), dict) else {}
        eligible_domains = {str(x).upper() for x in (quality.get("eligible_domains") or [])}
        wrapped = {**row, "calibration_source": "FOUNDER_MARKET_ACTION", "strategy_snapshot": strategy}
        if "FAST_VALIDATION" in eligible_domains and track in {"FAST_VALIDATION", "BOTH"}:
            fast_rows.append(wrapped)
        first_person = str(strategy.get("first_person_addressability_state") or "").upper()
        if "FOUNDER_ADDRESSABILITY" in eligible_domains and first_person in {"SUPPORTED", "PARTIAL", "INSUFFICIENT", "UNKNOWN", "REFUTED"}:
            addressability_rows.append(wrapped)

    def entity_key(r: dict[str, Any]) -> str:
        if r.get("calibration_source") == "FOUNDER_MARKET_ACTION":
            return f"thesis:{r.get('thesis_id') or (r.get('pretest_snapshot') or {}).get('thesis_id') or ''}"
        return f"case:{int(r.get('case_id') or 0)}"

    fast_entities = {entity_key(r) for r in fast_rows if entity_key(r) not in {"case:0", "thesis:"}}
    fast_counts = Counter(str(r.get("result") or "UNKNOWN").upper() for r in fast_rows)
    fast_enough = len(fast_rows) >= MIN_FAST_OUTCOMES and len(fast_entities) >= MIN_FAST_CASES

    addr_entities = {entity_key(r) for r in addressability_rows if entity_key(r) not in {"case:0", "thesis:"}}
    by_addr: dict[str, Counter] = {}
    for r in addressability_rows:
        strategy = r.get("strategy_snapshot") or {}
        state = str(strategy.get("first_person_addressability_state") or "UNKNOWN").upper()
        by_addr.setdefault(state, Counter())[str(r.get("result") or "UNKNOWN").upper()] += 1
    addr_enough = len(addressability_rows) >= MIN_ADDRESSABILITY_OUTCOMES and len(addr_entities) >= MIN_ADDRESSABILITY_CASES

    source_counts_fast = Counter(str(r.get("calibration_source") or "UNKNOWN") for r in fast_rows)
    source_counts_addr = Counter(str(r.get("calibration_source") or "UNKNOWN") for r in addressability_rows)

    # Current buyer experiments / market actions still cannot validate structural predictions.
    # Structural results enter only through separately pre-registered longitudinal checkpoints.
    structural_registry = structural_registry_report()
    structural_completed = list(structural_registry.get("rows") or [])
    structural_completed = [x for x in structural_completed if str(x.get("status") or "").upper() == "COMPLETED"]
    structural_counts = Counter(str(x.get("result") or "UNKNOWN").upper() for x in structural_completed)
    structural = {
        "status": "UNVALIDATED" if not structural_completed else "PARTIAL_LONGITUDINAL_OUTCOMES",
        "completed_structural_outcomes": len(structural_completed),
        "pending_structural_checkpoints": int(structural_registry.get("pending", 0) or 0),
        "result_counts": dict(structural_counts),
        "metric": None,
        "readiness": "READY_TO_REGISTER" if not structural_registry.get("total") else "CHECKPOINTS_REGISTERED",
        "required_observations": [
            "transition_strength_over_time",
            "legacy_system_mismatch_persistence",
            "buyer_formation_direction",
            "incumbent_response",
            "wedge_expansion_or_collapse",
        ],
        "truth_boundary": "Fast buyer experiments and Founder market actions cannot be relabeled as Zip2/structural predictive success.",
    }

    any_outcomes = bool(validation_rows or action_rows or structural_completed)
    return {
        "engine_version": ENGINE_VERSION,
        "fast_validation": {
            "status": "PRELIMINARY" if fast_enough else "UNVALIDATED",
            "completed_outcomes": len(fast_rows),
            "completed_cases": len(fast_entities),
            "result_counts": dict(fast_counts),
            "source_counts": dict(source_counts_fast),
            "positive_rate": (round(fast_counts.get("PASS", 0) / len(fast_rows), 4) if fast_enough and fast_rows else None),
            "minimum_policy": {"outcomes": MIN_FAST_OUTCOMES, "cases": MIN_FAST_CASES},
            "selection_censoring": "ONLY_PRE_REGISTERED_ACTIONS_THAT_FOUNDER_CHOSE_TO_RUN_ARE_OBSERVED",
            "truth_boundary": "Observed fast-test outcomes only; not general market accuracy and not structural calibration.",
        },
        "structural_opportunity": structural,
        "founder_addressability": {
            "status": "PRELIMINARY" if addr_enough else "UNVALIDATED",
            "completed_outcomes": len(addressability_rows),
            "completed_cases": len(addr_entities),
            "source_counts": dict(source_counts_addr),
            "outcomes_by_pretest_addressability": {k: dict(v) for k, v in sorted(by_addr.items())},
            "minimum_policy": {"outcomes": MIN_ADDRESSABILITY_OUTCOMES, "cases": MIN_ADDRESSABILITY_CASES},
            "selection_censoring": "ADDRESSABILITY_CALIBRATION_ONLY_SEES_PRE_REGISTERED_ACTIONS_WITH_FROZEN_PRETEST_STATE",
            "truth_boundary": "Only experiments/actions whose pre-test snapshot captured Founder addressability enter this domain.",
        },
        "overall_market_calibration": "UNVALIDATED" if not any_outcomes else "PARTIAL_OUTCOMES_EXIST_NO_GENERAL_ACCURACY",
        "market_action_outcomes_eligible": len(action_rows),
        "radar_validation_outcomes_eligible": len(validation_rows),
        "zero_is_valid": True,
    }


def static_acceptance() -> dict[str, bool]:
    r = calibration_domains_report()
    return {
        "calibration_domains_split": set(("fast_validation", "structural_opportunity", "founder_addressability")).issubset(r),
        "structural_not_inferred_from_fast_tests": r["structural_opportunity"]["completed_structural_outcomes"] == 0,
        "no_general_accuracy_claim": "accuracy" not in str(r.get("overall_market_calibration") or "").lower(),
        "zero_allowed": bool(r.get("zero_is_valid")),
    }
