"""SignalForge market-result closure readiness V1.

Inspects the real validation/result pipeline without creating synthetic outcomes.
It answers whether a future Founder experiment has a pre-registration path, a
quality-locked result-ingestion path, and a deterministic claim-mapping path.
"""
from __future__ import annotations

from typing import Any

from processors.market_ground_truth import ENGINE_VERSION as GROUND_TRUTH_ENGINE, EVENT_TO_CLAIMS
from processors.validation_registry import ENGINE_VERSION as REGISTRY_ENGINE, CLAIM_EVENT, validation_registry_report
from processors.validation_cohort import load_validation_cohort

ENGINE_VERSION = "market-closure-readiness-v1-preregistered-frozen-control"


def market_closure_readiness() -> dict[str, Any]:
    registry = validation_registry_report()
    cohort = load_validation_cohort()
    mapping = {
        code: {
            "event": event,
            "ground_truth_claims": list(EVENT_TO_CLAIMS.get(event, ())),
        }
        for code, event in sorted(CLAIM_EVENT.items())
    }
    mapping_complete = all(
        code in EVENT_TO_CLAIMS.get(event, ())
        for code, event in CLAIM_EVENT.items()
    )
    frozen = bool(cohort.get("selection_snapshot_frozen", False))
    clean = int(cohort.get("clean_matched_pairs", 0) or 0)
    matched = len(cohort.get("matched_pairs", []) or [])

    return {
        "engine_version": ENGINE_VERSION,
        "registry_engine": REGISTRY_ENGINE,
        "ground_truth_engine": GROUND_TRUTH_ENGINE,
        "registered_experiments": int(registry.get("total", 0) or 0),
        "pending_experiments": int(registry.get("pending", 0) or 0),
        "completed_experiments": int(registry.get("completed", 0) or 0),
        "claim_event_mapping": mapping,
        "mapping_complete": mapping_complete,
        "preregistration_required": True,
        "unregistered_result_bypass_allowed": False,
        "pass_requires_identified_actor": True,
        "price_pass_requires_positive_amount_currency": True,
        "negative_single_test_refutes_market": False,
        "selection_snapshot_frozen": frozen,
        "matched_control_pairs": matched,
        "clean_control_pairs": clean,
        "ready_for_first_real_result": bool(mapping_complete and frozen),
        "market_truth_claimed": False,
        "predictive_accuracy_claimed": False,
    }
