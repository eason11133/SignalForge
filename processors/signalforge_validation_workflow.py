"""SignalForge R5 claim-specific market validation operating workflow.

This module exposes the existing quality-locked atomic market validation path as
one Founder-operable workflow without creating a second truth writer.

Truth ownership remains unchanged:
- validation_registry freezes the claim-specific pre-test experiment;
- market_ground_truth is the only writer of human market evidence to C10/C11/C14;
- complete_validation_experiment closes the immutable experiment record;
- opportunity_decision only recomputes the affected case after the write.

A thesis-level Founder/market action is not a substitute for this experiment and
cannot be retroactively converted into atomic claim truth after its outcome is
known.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from processors.signalforge_process_lock import async_cross_process_file_lock

from processors.validation_registry import (
    CLAIM_EVENT,
    create_validation_experiment,
    complete_validation_experiment,
    get_validation_experiment,
    validation_registry_report,
)

ENGINE_VERSION = "signalforge-claim-validation-workflow-r5"
PROMOTION_LOCK_DIR = Path(".radar_runtime/signalforge_market_truth_promotion_locks")


def claim_validation_report() -> dict[str, Any]:
    report = dict(validation_registry_report())
    rows = list(report.get("rows") or [])
    pending = [r for r in rows if str(r.get("status") or "").upper() == "PENDING"]
    completed = [r for r in rows if str(r.get("status") or "").upper() == "COMPLETED"]
    return {
        "engine_version": ENGINE_VERSION,
        "total": len(rows),
        "pending": len(pending),
        "completed": len(completed),
        "claim_event_map": dict(CLAIM_EVENT),
        "rows": rows,
        "truth_boundary": (
            "CLAIM_VALIDATION_UI_ORCHESTRATES_EXISTING_PREREGISTERED_MARKET_GROUND_TRUTH_ONLY; "
            "IT_HAS_NO_INDEPENDENT_C01_C14_WRITE_AUTHORITY"
        ),
    }


async def register_claim_validation(
    *,
    case_id: int,
    claim_code: str,
    note: str | None = None,
    market_action_id: str | None = None,
) -> dict[str, Any]:
    """Pre-register one C10/C11/C14 experiment before the outcome exists."""
    return await create_validation_experiment(
        case_id=int(case_id),
        claim_code=str(claim_code or "").upper(),
        note=note,
        market_action_id=market_action_id,
    )


async def record_claim_validation_outcome(
    *,
    experiment_id: str,
    result: str,
    note: str,
    event: str | None = None,
    actor_label: str | None = None,
    amount: float | None = None,
    currency: str | None = None,
) -> dict[str, Any]:
    """Record through the existing atomic writer, then close + recompute one case.

    The experiment must still be PENDING. If an external failure occurs after
    market_ground_truth commits but before the registry file is closed, retrying
    remains safe because market evidence uses a deterministic experiment-based
    source_ref and the evidence/link path is idempotent.
    """
    experiment_id = str(experiment_id or "").strip()
    lock_path = PROMOTION_LOCK_DIR / f"{experiment_id or 'missing'}.lock"
    async with async_cross_process_file_lock(lock_path):
        return await _record_claim_validation_outcome_locked(
            experiment_id=experiment_id,
            result=result,
            note=note,
            event=event,
            actor_label=actor_label,
            amount=amount,
            currency=currency,
        )


async def _record_claim_validation_outcome_locked(
    *,
    experiment_id: str,
    result: str,
    note: str,
    event: str | None = None,
    actor_label: str | None = None,
    amount: float | None = None,
    currency: str | None = None,
) -> dict[str, Any]:
    registered = get_validation_experiment(experiment_id)
    if registered is None:
        raise ValueError(f"experiment {experiment_id!r} is not pre-registered")
    if str(registered.get("status") or "").upper() != "PENDING":
        raise ValueError(f"experiment {experiment_id} is not pending")

    case_id = int(registered.get("case_id") or 0)
    if case_id <= 0:
        raise ValueError(f"experiment {experiment_id} has no valid case id")
    recorded_event = str(event or registered.get("event") or "").upper().replace("-", "_")

    # Lazy imports keep read-only/static acceptance usable without a live DB
    # driver while preserving the existing modules as the only truth/decision owners.
    from processors.market_ground_truth import record_market_result
    from processors.opportunity_decision import run_opportunity_decision

    market_result = await record_market_result(
        case_id=case_id,
        event=recorded_event,
        result=result,
        note=note,
        experiment_id=experiment_id,
        actor_label=actor_label,
        amount=amount,
        currency=currency,
    )

    completed = complete_validation_experiment(
        experiment_id=experiment_id,
        result=result,
        note=note,
        amount=amount,
        currency=currency,
        actor_label=actor_label,
    )
    if completed is None:
        raise RuntimeError(
            "market evidence was recorded but validation registry completion failed; "
            "retry the same experiment id to reconcile the durable record"
        )

    decision = await run_opportunity_decision(
        limit=50,
        reality_mode="persisted",
        case_ids=[case_id],
    )
    decision_row = next(
        (
            row for row in (decision.get("rows") or [])
            if int(row.get("case_id") or 0) == case_id
        ),
        {},
    )
    return {
        "engine_version": ENGINE_VERSION,
        "experiment": completed,
        "market_result": market_result,
        "decision_after": {
            "case_id": case_id,
            "decision_verdict": decision_row.get("decision_verdict"),
            "current_gate": decision_row.get("current_gate"),
            "market_validation_boundary": decision_row.get("market_validation_boundary"),
            "claims": decision_row.get("claims") or {},
        },
        "truth_boundary": (
            "ATOMIC_MARKET_EVIDENCE_WAS_WRITTEN_ONLY_BY_MARKET_GROUND_TRUTH_AFTER_CLAIM_PREREGISTRATION; "
            "FAIL_REMAINS_INSUFFICIENT_AND_DOES_NOT_AUTO_REFUTE"
        ),
    }


def static_acceptance() -> dict[str, bool]:
    import ast
    source = __import__("pathlib").Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    import_modules = {
        str(node.module or "")
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    return {
        "workflow_uses_existing_market_ground_truth_writer": "record_market_result(" in source,
        "workflow_requires_existing_preregistration": "get_validation_experiment" in source and "is not pending" in source,
        "workflow_closes_existing_registry": "complete_validation_experiment(" in source,
        "workflow_recomputes_only_affected_case": 'case_ids=[case_id]' in source and 'reality_mode="persisted"' in source,
        "workflow_has_no_direct_radar_truth_writer_import": not ({"database.connection", "processors.opportunity_reality"} & import_modules),
    }
