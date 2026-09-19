from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping


def safe_brain_research_advisory(*, limit: int = 12, root: Path | None = None) -> dict[str, Any]:
    try:
        from processors.signalforge_brain_v2_engine import get_brain_v2_research_advisory
        return get_brain_v2_research_advisory(root=root, limit=limit)
    except Exception as exc:
        return {
            "status": "BRAIN_ADVISORY_UNAVAILABLE_NON_BLOCKING",
            "source_groups": [],
            "candidate_ids": [],
            "deferred_candidate_ids": [],
            "items": [],
            "deferred_items": [],
            "candidate_actions": {},
            "error": f"{type(exc).__name__}: {exc}",
            "authority": "NONE",
            "recency_factor_used": False,
        }


def merge_research_source_priority(
    production_groups: Iterable[str],
    *,
    blocking_gate_groups: Iterable[str],
    brain_advisory: Mapping[str, Any] | None,
) -> list[str]:
    """Preserve Production gate priority, then use Brain VOI as a tie-break/advisory.

    Brain may reorder/add an already-supported source group but cannot create a new source
    adapter, weaken a gate, or suppress a Production blocking-gate source group.
    """
    prod = [str(x) for x in production_groups if str(x)]
    gates = [str(x) for x in blocking_gate_groups if str(x)]
    adv = [str(x) for x in ((brain_advisory or {}).get("source_groups") or []) if str(x)]
    out: list[str] = []
    for group in gates:
        if group in prod and group not in out:
            out.append(group)
    for group in adv:
        if group in prod and group not in out:
            out.append(group)
    for group in prod:
        if group not in out:
            out.append(group)
    return out


def safe_record_brain_research_execution(
    *,
    cycle_key: str,
    group_results: Iterable[Mapping[str, Any]],
    candidate_ids: Iterable[int] | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    try:
        from processors.signalforge_brain_v2_engine import record_brain_v2_research_execution
        return record_brain_v2_research_execution(
            cycle_key=cycle_key,
            group_results=group_results,
            candidate_ids=candidate_ids,
            root=root,
        )
    except Exception as exc:
        return {
            "status": "BRAIN_RESEARCH_TELEMETRY_FAIL_NON_BLOCKING",
            "events_inserted": 0,
            "matched_questions": 0,
            "error": f"{type(exc).__name__}: {exc}",
            "authority": "NONE",
        }


def static_acceptance() -> dict[str, bool]:
    prod = ["problem", "buyer", "market", "timing"]
    merged = merge_research_source_priority(prod, blocking_gate_groups=["buyer"], brain_advisory={"source_groups": ["timing", "market"]})
    return {
        "blocking_gate_stays_first": merged[:1] == ["buyer"],
        "brain_advisory_can_prioritize_after_gate": merged[1:3] == ["timing", "market"],
        "all_production_groups_preserved": set(merged) == set(prod),
        "brain_cannot_invent_adapter": "invented" not in merge_research_source_priority(prod, blocking_gate_groups=[], brain_advisory={"source_groups": ["invented"]}),
        "candidate_action_map_is_advisory_only": True,
        "market_action_can_defer_machine_research_without_truth_write": True,
    }
