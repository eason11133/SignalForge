from __future__ import annotations

import copy
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from processors.signalforge_brain_v2_engine import refresh_signalforge_brain_v2

ENGINE_VERSION = "signalforge-brain-v2-time-slice-benchmark-r1"


def _dt(v: Any) -> datetime | None:
    if not v:
        return None
    try:
        x = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        if x.tzinfo is None:
            x = x.replace(tzinfo=timezone.utc)
        return x.astimezone(timezone.utc)
    except Exception:
        return None


def _before(v: Any, cutoff: datetime) -> bool:
    d = _dt(v)
    return d is None or d <= cutoff


def filter_snapshot_as_of(snapshot: Mapping[str, Any], cutoff: str) -> dict[str, Any]:
    """Filter an already time-sliced truth snapshot without importing future evidence.

    IMPORTANT: Radar claim states themselves are not reconstructed from current production
    history here. A real retrospective dataset must supply the claim snapshot that was valid at
    the cutoff. This function only prevents evidence rows after cutoff from leaking into a
    benchmark fixture.
    """
    cut = _dt(cutoff)
    if cut is None:
        raise ValueError("invalid cutoff")
    out = copy.deepcopy(dict(snapshot))
    out["candidate_evidence"] = [
        x for x in out.get("candidate_evidence", [])
        if _before(x.get("observed_at") or x.get("created_at") or (x.get("metadata") or {}).get("published_at"), cut)
    ]
    out["validated_radar_links"] = [
        x for x in out.get("validated_radar_links", [])
        if _before(x.get("observed_at") or x.get("published_at"), cut)
    ]
    out.setdefault("benchmark", {})["as_of"] = cutoff
    out["benchmark"]["lookahead_forbidden"] = True
    return out


def benchmark_dataset_contract() -> dict[str, Any]:
    return {
        "engine_version": ENGINE_VERSION,
        "required_fields": {
            "case_id": "stable benchmark identity",
            "cutoff": "evidence availability cutoff",
            "snapshot": "truth state reconstructed as of cutoff; current claim states are forbidden",
            "expected_discovery": "whether structural thesis should be surfaced",
            "expected_failure_mode": "optional negative-control reason",
            "outcome_date": "must be after cutoff for predictive evaluation",
        },
        "metrics": [
            "discovery_recall", "false_positive_rate", "lead_time_days",
            "problem_lineage_precision", "transition_lineage_coherence",
            "buyer_gate_precision", "thesis_survival", "captureability_precision",
        ],
        "market_calibration_effect": "NONE_UNTIL_REAL_HISTORICAL_OR_LIVE_OUTCOMES_ARE_LOADED",
    }


async def synthetic_time_slice_acceptance() -> dict[str, bool]:
    # This is a regression harness, not market calibration. Each scenario has an early
    # snapshot and a later truth mutation representing one failure class.
    from run_signalforge_brain_v2_acceptance import fixture_snapshot

    base = fixture_snapshot()
    # Future transition evidence should not be visible at an earlier cutoff.
    future = copy.deepcopy(base)
    for row in future.get("candidate_evidence", []):
        if str(row.get("relation") or "") == "why_now":
            row["observed_at"] = "2027-01-01T00:00:00Z"
            row.setdefault("metadata", {})["published_at"] = "2027-01-01T00:00:00Z"
    early = filter_snapshot_as_of(future, "2026-01-01T00:00:00Z")

    with tempfile.TemporaryDirectory(prefix="sfbrain_benchmark_") as td:
        root = Path(td)
        e = await refresh_signalforge_brain_v2(root=root, snapshot=early)
        early_theses = list(e.get("portfolio", []) or [])

    # Negative control: explicit gap refutation must terminate thesis.
    dead_snap = fixture_snapshot(gap_refuted=True)
    with tempfile.TemporaryDirectory(prefix="sfbrain_benchmark_dead_") as td:
        d = await refresh_signalforge_brain_v2(root=Path(td), snapshot=dead_snap)
        deaths = [x.get("death_state") for x in d.get("portfolio", []) or []]

    return {
        "future_transition_evidence_filtered": not any(
            str(x.get("transition_lineage_id") or "") for x in early_theses
        ),
        "negative_gap_control_dies": "SOLVED_OR_NO_DURABLE_GAP" in deaths,
        "benchmark_contract_requires_cutoff": "cutoff" in benchmark_dataset_contract()["required_fields"],
        "benchmark_does_not_claim_calibration": benchmark_dataset_contract()["market_calibration_effect"].startswith("NONE"),
    }
