"""SignalForge Founder Daily Surface V1.

Produces one daily-use decision surface from the current Company Truth:
- what deserves attention,
- why it deserves attention,
- biggest unresolved gate,
- what the machine should do next,
- what commercial/timing reality is already prepared,
- whether Founder market action is actually allowed.

It writes a machine-readable JSON snapshot for the dashboard and prints a
compact terminal surface. No LLM is used.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from processors.opportunity_decision import run_opportunity_decision
from processors.calibration import calibration_report
from processors.quality_guard import audit_quality
from processors.validation_cohort import build_validation_cohort
from processors.research_portfolio import build_research_portfolio
from processors.signalforge_market_action_registry import build_market_action_queue, market_action_registry_report
from processors.signalforge_validation_workflow import claim_validation_report

ENGINE_VERSION = "founder-daily-surface-r5-operating-loop"
SNAPSHOT_PATH = Path(".radar_runtime/founder_daily.json")


def _biggest_unknown(row: dict[str, Any]) -> str:
    next_claim = str(row.get("next_claim") or "")
    gate = str(row.get("current_gate") or "")
    if next_claim:
        return f"{next_claim} / {gate}"
    unresolved = row.get("unresolved_claims") or []
    if unresolved:
        return str(unresolved[0])
    return "NONE"


def _floor_summary(row: dict[str, Any]) -> dict[str, Any]:
    floor = row.get("floor60_reality") or {}
    packets = floor.get("packets") or {}

    out = {}
    for code in ("C08", "C10", "C11", "C12", "C13", "C14"):
        packet = packets.get(code) or {}
        if not packet:
            continue
        out[code] = {
            "status": packet.get("status"),
            "next_boundary": packet.get("next_boundary"),
            "source_need": packet.get("source_need"),
        }
        if code == "C08":
            out[code]["wedge"] = packet.get("wedge_hypothesis")
            out[code]["competitors"] = (
                packet.get("named_competitor_context") or []
            )[:3]
        elif code == "C12":
            out[code]["technology_regime"] = packet.get(
                "technology_regime"
            )
        elif code == "C13":
            out[code]["competitors"] = (
                packet.get("named_competitor_context") or []
            )[:3]
        elif code == "C14":
            out[code]["friction"] = packet.get("friction_signals")
    return out


async def build_founder_daily_surface(
    *,
    limit: int = 10,
    save_snapshot: bool = True,
    decision: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if decision is None:
        decision = await run_opportunity_decision(limit=max(10, limit))
    rows = decision.get("rows", [])

    # Founder priority is intentionally sparse. A broad/high-attention research
    # theme is not promoted merely to fill the screen.
    founder_rows = [
        row for row in rows
        if (row.get("solo_transition") or {}).get("founder_surface_eligible")
    ]
    watch_rows = [
        row for row in rows
        if (row.get("solo_transition") or {}).get("classification") == "SOLO_WATCH"
    ]
    research_theme_count = sum(
        1 for row in rows
        if (row.get("solo_transition") or {}).get("classification") == "RESEARCH_THEME"
    )

    cards = []
    for row in founder_rows[: max(1, int(limit))]:
        progression = row.get("progression") or {}
        query_packets = progression.get("query_packets") or []
        company_reality = row.get("company_reality") or {}
        cards.append({
            "case_id": row.get("case_id"),
            "candidate_id": row.get("candidate_id"),
            "title": row.get("title"),
            "verdict": row.get("decision_verdict"),
            "attention_score": row.get("attention_score"),
            "why_now": row.get("why_now"),
            "decision_reason": row.get("decision_reason"),
            "biggest_unknown": _biggest_unknown(row),
            "machine_action": row.get("machine_action"),
            "founder_action": row.get("founder_action"),
            "market_validation_boundary": row.get(
                "market_validation_boundary"
            ),
            "buyer_organizations": row.get("buyer_organizations") or [],
            "claims": row.get("claims") or {},
            "reality": _floor_summary(row),
            "progression": progression,
            "next_evidence_queries": [
                {
                    "source_group": packet.get("source_group"),
                    "purpose": packet.get("purpose"),
                    "query": packet.get("query"),
                    "claims": packet.get("claims") or [],
                }
                for packet in query_packets[:2]
            ],
            "company_gap_plan": company_reality.get("capability_gap_plan") or [],
            "solo_transition": row.get("solo_transition") or {},
        })

    portfolio = build_research_portfolio(rows)
    cohort = build_validation_cohort(rows, save=save_snapshot)
    calibration = calibration_report()
    quality = await audit_quality(decision=decision)
    validate_now = sum(
        1 for row in rows
        if row.get("market_validation_boundary") == "FOUNDER_ACTION_NOW"
    )
    prebuilt = sum(
        1 for row in rows
        if row.get("market_validation_boundary")
        == "PREBUILT_WAITING_FOR_VALIDATE"
    )

    # Brain v2 is the canonical structural portfolio. The legacy Candidate surface remains
    # useful as atomic evidence drill-down, but no longer owns Founder strategy/ranking.
    try:
        from processors.signalforge_brain_v2_engine import get_brain_v2_portfolio
        brain = dict(get_brain_v2_portfolio())
    except Exception as exc:
        brain = {"status": "UNAVAILABLE", "error": f"{type(exc).__name__}: {exc}", "portfolio": [], "strategic_summary": {}}
    brain_items = list(brain.get("portfolio", []) or [])
    market_action_queue = build_market_action_queue(limit=50)
    market_action_registry = market_action_registry_report()
    claim_validation_registry = claim_validation_report()
    claim_validation_ready = [
        {
            "case_id": row.get("case_id"),
            "candidate_id": row.get("candidate_id"),
            "title": row.get("title"),
            "claim_states": row.get("claims") or {},
            "prepared_claims": row.get("prepared_validation_claims") or [],
            "events": {
                "C10": "ACQUISITION",
                "C11": "PRICE",
                "C14": "SWITCH",
            },
        }
        for row in rows
        if row.get("market_validation_boundary") == "FOUNDER_ACTION_NOW"
        and (row.get("prepared_validation_claims") or [])
    ]

    snapshot = {
        "engine_version": ENGINE_VERSION,
        "generated_at": datetime.utcnow().isoformat(),
        "verdict_counts": decision.get("verdict_counts", {}),
        "build_locked": decision.get("build_locked", True),
        "solo_founder_gate": {
            "ready": len(founder_rows),
            "watch": len(watch_rows),
            "research_themes_parked": research_theme_count,
            "definition": "Legacy candidate gate retained for compatibility only. Canonical Founder strategy is Brain v2 ZIP2_STRUCTURAL / FAST_VALIDATION / BOTH / NEITHER.",
            "decision_authority": False,
            "empty_is_valid": True,
        },
        "validation_boundary": {
            "founder_action_now": validate_now,
            "prebuilt_waiting": prebuilt,
            "machine_first": max(0, len(rows) - validate_now - prebuilt),
        },
        "calibration": calibration.get("credibility"),
        "founder_strategy": {
            "authority": "BRAIN_V2_DERIVED_STRATEGIC_PORTFOLIO",
            "strategic_summary": brain.get("strategic_summary") or {},
            "brain_status": brain.get("status"),
            "brain_refreshed_at": brain.get("refreshed_at"),
            "items": [
                {
                    "thesis_id": x.get("thesis_id"),
                    "representative_title": x.get("representative_title"),
                    "representative_problem": x.get("representative_problem"),
                    "strategic_track": x.get("strategic_track"),
                    "classification": x.get("classification"),
                    "zip2_readiness": x.get("zip2_readiness"),
                    "fast_validation": x.get("fast_validation") or {},
                    "founder_addressability": x.get("founder_addressability") or {},
                    "best_next_action": x.get("best_next_action") or {},
                    "member_candidate_ids": x.get("member_candidate_ids") or [],
                }
                for x in brain_items[:20]
            ],
            "action_queue": list(brain.get("founder_action_queue", []) or [])[:20],
            "candidate_surface_role": "ATOMIC_EVIDENCE_DRILLDOWN_NOT_STRATEGIC_AUTHORITY",
        },
        "execution_governor": decision.get("execution_governor") or {},
        "strategic_routing_coherence": decision.get("strategic_routing_coherence") or {},
        "operating_queue": decision.get("operating_queue") or {},
        "market_action_queue": market_action_queue,
        "market_action_registry": {
            "engine_version": market_action_registry.get("engine_version"),
            "total": market_action_registry.get("total", 0),
            "registered": market_action_registry.get("registered", 0),
            "running": market_action_registry.get("running", 0),
            "completed": market_action_registry.get("completed", 0),
            "calibration_eligible": market_action_registry.get("calibration_eligible", 0),
            "calibration_ineligible_recorded": market_action_registry.get("calibration_ineligible_recorded", 0),
            "truth_boundary": market_action_registry.get("truth_boundary"),
        },
        "claim_validation_ready": claim_validation_ready,
        "claim_validation_registry": {
            "engine_version": claim_validation_registry.get("engine_version"),
            "total": claim_validation_registry.get("total", 0),
            "pending": claim_validation_registry.get("pending", 0),
            "completed": claim_validation_registry.get("completed", 0),
            "truth_boundary": claim_validation_registry.get("truth_boundary"),
        },
        "research_portfolio": {
            "engine_version": portfolio.get("engine_version"),
            "ordered_groups": portfolio.get("ordered_groups") or [],
            "ranked_groups": portfolio.get("ranked_groups") or [],
            "query_jobs": len(portfolio.get("query_jobs") or []),
            "top_query_jobs": (portfolio.get("top_query_jobs") or [])[:5],
        },
        "validation_cohort": {
            "treatment_candidates": cohort.get("treatment_candidates", 0),
            "control_candidates": cohort.get("control_candidates", 0),
            "matched_pairs": len(cohort.get("matched_pairs", []) or []),
            "clean_matched_pairs": int(cohort.get("clean_matched_pairs", 0) or 0),
            "contaminated_pairs": int(cohort.get("contaminated_pairs", 0) or 0),
            "selection_snapshot_frozen": bool(cohort.get("selection_snapshot_frozen", False)),
            "predictive_accuracy_claimed": False,
        },
        "quality": {
            "status": quality.get("status"),
            "critical_count": quality.get("critical_count", 0),
            "warning_count": quality.get("warning_count", 0),
        },
        "cards": cards,
        "solo_watch_preview": [
            {
                "case_id": row.get("case_id"),
                "candidate_id": row.get("candidate_id"),
                "title": row.get("title"),
                "solo_transition": row.get("solo_transition") or {},
            }
            for row in watch_rows[:3]
        ],
        "api_calls": 0,
        "llm_calls": 0,
    }

    if save_snapshot:
        SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT_PATH.write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        snapshot["snapshot_path"] = str(SNAPSHOT_PATH)

    return snapshot


def print_founder_daily_surface(snapshot: dict[str, Any]) -> None:
    print("=" * 116)
    print("SIGNALFORGE FOUNDER DAILY — DECISION SURFACE")
    print("=" * 116)
    print(
        "Lanes: "
        + " | ".join(
            f"{k}={v}"
            for k, v in sorted(
                (snapshot.get("verdict_counts") or {}).items()
            )
        )
    )
    boundary = snapshot.get("validation_boundary") or {}
    quality = snapshot.get("quality") or {}
    print(
        "Quality gate: "
        f"{quality.get('status', 'UNKNOWN')} | "
        f"critical={quality.get('critical_count', 0)} | "
        f"warnings={quality.get('warning_count', 0)}"
    )
    print(
        "Boundary: "
        f"Founder action now={boundary.get('founder_action_now', 0)} | "
        f"Prebuilt waiting={boundary.get('prebuilt_waiting', 0)} | "
        f"Machine first={boundary.get('machine_first', 0)}"
    )
    calib = snapshot.get("calibration") or {}
    print(
        "Predictive credibility: "
        f"{calib.get('status', 'UNVALIDATED')}"
    )
    portfolio = snapshot.get("research_portfolio") or {}
    print(
        "Research priority: "
        + " -> ".join(portfolio.get("ordered_groups") or [])
        + f" | query jobs={portfolio.get('query_jobs', 0)}"
    )
    maq = snapshot.get("market_action_queue") or {}
    print(
        "Founder / market actions: "
        f"suggested={maq.get('count', 0)} | "
        f"registered_open={maq.get('registered_open', 0)} | completed={maq.get('completed', 0)}"
    )
    print("-" * 116)

    for idx, card in enumerate(snapshot.get("cards", []), start=1):
        print(
            f"#{idx:02d} [{card.get('verdict')}] "
            f"{card.get('title')} | attention={card.get('attention_score')}"
        )
        print(
            f"     biggest unknown: {card.get('biggest_unknown')}"
        )
        print(
            f"     machine next:    {card.get('machine_action')}"
        )
        next_queries = card.get("next_evidence_queries") or []
        if next_queries:
            first = next_queries[0]
            print(
                f"     evidence next:   [{first.get('source_group')}] "
                f"{first.get('purpose')} — {str(first.get('query') or '')[:180]}"
            )
        boundary = card.get("market_validation_boundary")
        if boundary != "MACHINE_RESEARCH_FIRST":
            print(
                f"     validation:      {boundary} | "
                f"Founder={card.get('founder_action')}"
            )

        reality = card.get("reality") or {}
        compact = []
        for code in ("C08", "C10", "C11", "C12", "C13", "C14"):
            block = reality.get(code) or {}
            if block:
                compact.append(
                    f"{code}={block.get('status')}"
                )
        if compact:
            print("     reality:         " + " | ".join(compact))
        print("-" * 116)

    if snapshot.get("snapshot_path"):
        print("JSON snapshot:", snapshot["snapshot_path"])
    print("=" * 116)
