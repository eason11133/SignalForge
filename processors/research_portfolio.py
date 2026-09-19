"""SignalForge portfolio-level research scheduler V2.

Ranks shared source groups by expected information value across the portfolio
and carries claim-specific query packets forward so one retrieval can unlock
multiple cases/claims without weakening evidence standards.

The scheduler still does not decide truth.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

ENGINE_VERSION = "research-portfolio-v2-query-dedup-quality"

GROUP_COST = {
    "timing": 1.0,
    "market": 1.2,
    "buyer": 1.5,
    "problem": 1.7,
}

GATE_GROUP = {
    "PAIN_MATERIALITY": "problem",
    "BUYER_REALITY": "buyer",
    "BUYER_REALITY_RECHECK": "buyer",
    "CURRENT_SOLUTION": "problem",
    "CURRENT_SOLUTION_RECHECK": "problem",
    "UNRESOLVED_GAP": "problem",
    "UNRESOLVED_GAP_RECHECK": "problem",
    "DIFFERENTIATION": "market",
    "DISTRIBUTION": "buyer",
    "ECONOMICS": "buyer",
    "OPPORTUNITY_WINDOW": "timing",
    "COMPETITION": "market",
    "SWITCHING": "market",
}

VERDICT_WEIGHT = {
    "VALIDATE": 5.0,
    "INVESTIGATE": 4.0,
    "WATCH": 2.0,
    "PARK": 0.5,
    "IGNORE": 0.0,
}


def _case_needs(row: dict[str, Any]) -> dict[str, set[str]]:
    needs: dict[str, set[str]] = defaultdict(set)

    gate = str(row.get("current_gate") or "").upper()
    group = GATE_GROUP.get(gate)
    if group:
        needs[group].add("blocking_gate")

    floor = row.get("floor60_reality") or {}
    for group in floor.get("source_needs", []) or []:
        if group in GROUP_COST:
            needs[group].add("floor60")

    commercial = row.get("commercial_reality") or {}
    for group in commercial.get("needed_source_groups", []) or []:
        if group in GROUP_COST:
            needs[group].add("commercial")

    matrix = commercial.get("claim_matrix") or {}
    if isinstance(matrix, dict):
        for code, detail in matrix.items():
            if not isinstance(detail, dict):
                continue
            for group in detail.get("needed_source_groups", []) or []:
                if group in GROUP_COST:
                    needs[group].add(str(code))

    progression = row.get("progression") or {}
    for group in progression.get("source_groups", []) or []:
        if group in GROUP_COST:
            needs[group].add("progression")

    return needs


def _query_jobs(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}

    for row in rows:
        case_id = int(row.get("case_id") or 0)
        verdict = str(row.get("decision_verdict") or "WATCH").upper()
        attention = int(row.get("attention_score", 0) or 0)
        base = VERDICT_WEIGHT.get(verdict, 1.0) + min(100, attention) / 50.0

        packets = (
            (row.get("progression") or {}).get("query_packets")
            or row.get("evidence_query_packets")
            or []
        )
        for packet in packets:
            fingerprint = str(packet.get("fingerprint") or "").strip()
            group = str(packet.get("source_group") or "").strip()
            if not fingerprint or group not in GROUP_COST:
                continue

            job = merged.setdefault(
                fingerprint,
                {
                    "fingerprint": fingerprint,
                    "source_group": group,
                    "query": packet.get("query"),
                    "purpose": packet.get("purpose"),
                    "claims": set(),
                    "case_ids": set(),
                    "quality_contract": [],
                    "raw_value": 0.0,
                },
            )
            job["case_ids"].add(case_id)
            job["claims"].update(packet.get("claims") or [])
            job["raw_value"] += base

            for rule in packet.get("quality_contract") or []:
                if rule not in job["quality_contract"]:
                    job["quality_contract"].append(rule)

    out = []
    for job in merged.values():
        cost = GROUP_COST.get(job["source_group"], 1.0)
        # Shared queries get extra value because one retrieval can unlock more
        # than one case without duplicate scraping.
        shared_bonus = 1.0 + 0.35 * max(0, len(job["case_ids"]) - 1)
        voi = job["raw_value"] * shared_bonus / max(0.1, cost)
        out.append({
            **job,
            "claims": sorted(job["claims"]),
            "case_ids": sorted(job["case_ids"]),
            "case_count": len(job["case_ids"]),
            "raw_value": round(job["raw_value"], 3),
            "voi": round(voi, 3),
            "support_not_inferred": True,
        })

    out.sort(
        key=lambda row: (
            -float(row["voi"]),
            -int(row["case_count"]),
            str(row["source_group"]),
            str(row["fingerprint"]),
        )
    )
    return out


def build_research_portfolio(
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    group_cases: dict[str, set[int]] = defaultdict(set)
    group_claims: dict[str, set[str]] = defaultdict(set)
    group_score: dict[str, float] = defaultdict(float)
    case_details = []

    for row in rows:
        case_id = int(row.get("case_id") or 0)
        if not case_id:
            continue

        verdict = str(row.get("decision_verdict") or "WATCH").upper()
        attention = int(row.get("attention_score", 0) or 0)
        base = VERDICT_WEIGHT.get(verdict, 1.0) + min(100, attention) / 50.0
        needs = _case_needs(row)

        for group, reasons in needs.items():
            group_cases[group].add(case_id)
            group_claims[group].update(reasons)
            group_score[group] += base + 0.6 * len(reasons)

        case_details.append({
            "case_id": case_id,
            "verdict": verdict,
            "attention": attention,
            "needs": {
                group: sorted(reasons)
                for group, reasons in needs.items()
            },
            "blocking_gate": row.get("current_gate"),
            "query_packet_count": len(
                (row.get("progression") or {}).get("query_packets") or []
            ),
        })

    ranked = []
    for group in GROUP_COST:
        cases = group_cases.get(group, set())
        if not cases:
            continue
        raw = group_score[group]
        cost = GROUP_COST[group]
        voi = raw / max(0.1, cost)
        ranked.append({
            "group": group,
            "case_count": len(cases),
            "unlock_dimensions": sorted(group_claims[group]),
            "raw_value": round(raw, 3),
            "cost_weight": cost,
            "voi": round(voi, 3),
        })

    ranked.sort(
        key=lambda row: (
            -float(row["voi"]),
            -int(row["case_count"]),
            str(row["group"]),
        )
    )

    jobs = _query_jobs(rows)

    return {
        "engine_version": ENGINE_VERSION,
        "ranked_groups": ranked,
        "ordered_groups": [row["group"] for row in ranked],
        "query_jobs": jobs,
        "top_query_jobs": jobs[:20],
        "case_details": case_details,
        "api_calls": 0,
        "llm_calls": 0,
    }


def prioritize_source_groups(
    rows: list[dict[str, Any]],
    *,
    include_groups: list[str] | None = None,
) -> list[str]:
    portfolio = build_research_portfolio(rows)
    ordered = list(portfolio["ordered_groups"])

    for group in include_groups or []:
        if group in GROUP_COST and group not in ordered:
            ordered.append(group)

    return ordered
