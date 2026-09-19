"""SignalForge live calibration infrastructure V2.

Reports preliminary calibration only from completed, pre-registered experiments
with enough case and actor diversity. It never turns a tiny or repeated sample
from one buyer into an accuracy percentage.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from processors.validation_registry import validation_registry_report
from processors.validation_cohort import load_validation_cohort

ENGINE_VERSION = "live-calibration-infra-v4-frozen-clean-controls"
MIN_REPORTABLE_EXPERIMENTS = 10
MIN_REPORTABLE_CASES = 5
MIN_REPORTABLE_ACTORS = 8


def _predicted_positive(row: dict[str, Any]) -> bool:
    snapshot = row.get("pretest_snapshot") or {}
    verdict = str(snapshot.get("decision_verdict") or "").upper()
    boundary = str(
        snapshot.get("market_validation_boundary") or ""
    ).upper()
    return verdict == "VALIDATE" or boundary == "FOUNDER_ACTION_NOW"


def calibration_report() -> dict[str, Any]:
    registry = validation_registry_report()
    cohort = load_validation_cohort()
    completed = [
        row for row in registry.get("rows", [])
        if row.get("status") == "COMPLETED"
        and str(row.get("result") or "").upper() in {"PASS", "FAIL"}
        and row.get("pretest_snapshot")
    ]

    by_event: dict[str, dict[str, int]] = defaultdict(
        lambda: {"PASS": 0, "FAIL": 0}
    )
    case_ids = set()
    actor_keys = set()
    confusion = {
        "predicted_positive_pass": 0,
        "predicted_positive_fail": 0,
        "not_predicted_pass": 0,
        "not_predicted_fail": 0,
    }

    for row in completed:
        event = str(row.get("event") or "UNKNOWN").upper()
        result = str(row.get("result") or "").upper()
        by_event[event][result] += 1

        case_id = int(row.get("case_id") or 0)
        if case_id:
            case_ids.add(case_id)

        actor = str(row.get("actor_label") or "").strip().lower()
        if actor:
            actor_keys.add((case_id, actor))

        pred = _predicted_positive(row)
        if pred and result == "PASS":
            confusion["predicted_positive_pass"] += 1
        elif pred and result == "FAIL":
            confusion["predicted_positive_fail"] += 1
        elif result == "PASS":
            confusion["not_predicted_pass"] += 1
        else:
            confusion["not_predicted_fail"] += 1

    enough = (
        len(completed) >= MIN_REPORTABLE_EXPERIMENTS
        and len(case_ids) >= MIN_REPORTABLE_CASES
        and len(actor_keys) >= MIN_REPORTABLE_ACTORS
    )

    if enough:
        predicted_n = (
            confusion["predicted_positive_pass"]
            + confusion["predicted_positive_fail"]
        )
        positive_precision = (
            confusion["predicted_positive_pass"] / predicted_n
            if predicted_n
            else None
        )
        credibility = {
            "status": "PRELIMINARY",
            "positive_precision": (
                round(positive_precision, 4)
                if positive_precision is not None
                else None
            ),
            "warning": (
                "Preliminary prospective calibration only. It still may be "
                "selection-biased and is not population-level accuracy."
            ),
        }
    else:
        credibility = {
            "status": "UNVALIDATED",
            "positive_precision": None,
            "warning": (
                f"Need at least {MIN_REPORTABLE_EXPERIMENTS} completed "
                f"pre-registered experiments across {MIN_REPORTABLE_CASES} "
                f"cases and {MIN_REPORTABLE_ACTORS} independent case/actor "
                "pairs before preliminary calibration is reported."
            ),
        }

    return {
        "engine_version": ENGINE_VERSION,
        "registered_experiments": registry.get("total", 0),
        "completed_experiments": len(completed),
        "completed_cases": len(case_ids),
        "independent_actor_pairs": len(actor_keys),
        "event_outcomes": {
            event: dict(counts)
            for event, counts in sorted(by_event.items())
        },
        "confusion": confusion,
        "prospective_controls": {
            "treatment_candidates": int(cohort.get("treatment_candidates", 0) or 0),
            "control_candidates": int(cohort.get("control_candidates", 0) or 0),
            "matched_pairs": len(cohort.get("matched_pairs", []) or []),
            "clean_matched_pairs": int(cohort.get("clean_matched_pairs", 0) or 0),
            "contaminated_pairs": int(cohort.get("contaminated_pairs", 0) or 0),
            "selection_snapshot_frozen": bool(cohort.get("selection_snapshot_frozen", False)),
            "selection_policy": cohort.get("selection_policy"),
            "outcomes_compared": 0,
            "clean_outcomes_compared": 0,
            "warning": (
                "Only frozen, uncontaminated treatment/control pairs may enter "
                "future comparative lift/accuracy analysis. No comparative metric "
                "is reported until real outcomes exist for both sides."
            ),
        },
        "credibility": credibility,
    }
