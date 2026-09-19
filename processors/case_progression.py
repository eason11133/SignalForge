"""SignalForge quality-locked case progression V1.

Turns a decision row into an explicit progression contract:
- which gate is blocking,
- what evidence should be searched next,
- what can falsify the current hypothesis,
- when machine research must stop,
- when Founder market action becomes legal.

This module does not change a claim state. It makes the research path concrete
without lowering any evidence threshold.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from processors.evidence_query_planner import build_query_packets

ENGINE_VERSION = "case-progression-v2-go-live-diversity"

MACHINE_GATES = {
    "PAIN_MATERIALITY",
    "BUYER_REALITY",
    "BUYER_REALITY_RECHECK",
    "CURRENT_SOLUTION",
    "CURRENT_SOLUTION_RECHECK",
    "UNRESOLVED_GAP",
    "UNRESOLVED_GAP_RECHECK",
    "DIFFERENTIATION",
    "OPPORTUNITY_WINDOW",
    "COMPETITION",
}

FOUNDER_GATES = {
    "DISTRIBUTION",
    "ECONOMICS",
    "SWITCHING",
}

PREREQ_FOR_VALIDATE = ("C03", "C05", "C06", "C07", "C09")

GATE_URGENCY = {
    "UNRESOLVED_GAP": 100,
    "UNRESOLVED_GAP_RECHECK": 94,
    "CURRENT_SOLUTION": 92,
    "CURRENT_SOLUTION_RECHECK": 88,
    "BUYER_REALITY": 82,
    "BUYER_REALITY_RECHECK": 76,
    "PAIN_MATERIALITY": 70,
    "DIFFERENTIATION": 60,
    "COMPETITION": 56,
    "OPPORTUNITY_WINDOW": 52,
    "DISTRIBUTION": 45,
    "ECONOMICS": 45,
    "SWITCHING": 45,
}


def _state(row: dict[str, Any], code: str) -> str:
    return str((row.get("claims") or {}).get(code, "UNKNOWN")).upper()


def _promotion_contract(row: dict[str, Any]) -> dict[str, Any]:
    missing = [
        code for code in PREREQ_FOR_VALIDATE
        if _state(row, code) != "SUPPORTED"
    ]
    return {
        "validate_prerequisites": list(PREREQ_FOR_VALIDATE),
        "missing_validate_prerequisites": missing,
        "validate_allowed_now": not missing,
        "build_allowed_now": False,
        "thresholds_weakened": False,
    }


def _stop_condition(row: dict[str, Any]) -> str:
    gate = str(row.get("current_gate") or "").upper()
    if gate.endswith("_RECHECK"):
        return (
            "Do not repeat identical local research until the relevant source "
            "group is fresh or new evidence exists."
        )
    if gate in FOUNDER_GATES:
        return (
            "Stop desk research when the prepared market experiment is ready; "
            "do not search the web into fake acquisition/WTP/switch certainty."
        )
    if gate in MACHINE_GATES:
        return (
            "Stop when the claim is SUPPORTED/REFUTED, source-set exhaustion is "
            "documented, or the next uncertainty is inherently a market test."
        )
    return "Stop when additional research cannot change the next decision gate."


def progression_packet(row: dict[str, Any]) -> dict[str, Any]:
    gate = str(row.get("current_gate") or "").upper()
    verdict = str(row.get("decision_verdict") or "WATCH").upper()
    packets = build_query_packets(row)
    floor = row.get("floor60_reality") or {}

    if row.get("market_validation_boundary") == "FOUNDER_ACTION_NOW":
        boundary = "FOUNDER_ACTION_NOW"
    elif row.get("market_validation_boundary") == "PREBUILT_WAITING_FOR_VALIDATE":
        boundary = "PREBUILT_WAITING_FOR_VALIDATE"
    else:
        boundary = "MACHINE_RESEARCH_FIRST"

    return {
        "engine_version": ENGINE_VERSION,
        "case_id": int(row.get("case_id") or 0),
        "verdict": verdict,
        "blocking_gate": gate,
        "boundary": boundary,
        "machine_action": row.get("machine_action"),
        "founder_action": row.get("founder_action"),
        "query_packets": packets,
        "source_groups": sorted({
            str(p.get("source_group"))
            for p in packets
            if p.get("source_group")
        }),
        "floor60_source_needs": list(floor.get("source_needs") or []),
        "promotion_contract": _promotion_contract(row),
        "stop_condition": _stop_condition(row),
        "quality_contract": [
            "No attention score can override a blocking claim.",
            "No weak/RELATED evidence can manufacture SUPPORT.",
            "No market result can count as clean ground truth without pre-registration.",
            "Any new critical quality regression invalidates the research cycle.",
        ],
    }


def attach_progression_packets(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    for row in rows:
        row["progression"] = progression_packet(row)
    return rows


def select_progression_targets(
    rows: list[dict[str, Any]],
    *,
    limit: int = 8,
) -> list[dict[str, Any]]:
    """Expand focused research beyond INVESTIGATE without flooding all WATCH.

    INVESTIGATE/VALIDATE remain first. WATCH may enter only when its current gate
    is machine-researchable. A per-gate cap avoids spending an entire cycle on
    one repeated failure class.
    """

    candidates = []
    for row in rows:
        verdict = str(row.get("decision_verdict") or "").upper()
        gate = str(row.get("current_gate") or "").upper()

        if verdict in {"VALIDATE", "INVESTIGATE"}:
            tier = 0
        elif verdict == "WATCH" and gate in MACHINE_GATES:
            tier = 1
        else:
            continue

        candidates.append((
            tier,
            -int(GATE_URGENCY.get(gate, 0)),
            -int(row.get("attention_score", 0) or 0),
            int(row.get("case_id", 0) or 0),
            row,
        ))

    candidates.sort(key=lambda item: item[:4])

    selected = []
    per_gate: dict[str, int] = defaultdict(int)
    for _, _, _, _, row in candidates:
        gate = str(row.get("current_gate") or "").upper()
        # Keep diversity across C05/C06/C07 rather than burning a cycle on
        # many near-identical WATCH cases.
        gate_cap = 3 if gate in {
            "BUYER_REALITY",
            "BUYER_REALITY_RECHECK",
            "CURRENT_SOLUTION",
            "CURRENT_SOLUTION_RECHECK",
            "UNRESOLVED_GAP",
            "UNRESOLVED_GAP_RECHECK",
        } else (4 if gate == "PAIN_MATERIALITY" else 2)
        if per_gate[gate] >= gate_cap:
            continue
        selected.append(row)
        per_gate[gate] += 1
        if len(selected) >= max(1, int(limit)):
            break

    return selected
