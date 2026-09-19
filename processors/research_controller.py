
"""Radar atomic-evidence Research Controller.

Algorithm-first planning only. This controller owns machine/local evidence acquisition
for Radar claims; it is no longer the canonical Founder next-action authority. Brain v2
Founder strategy may route a thesis to HUMAN/FOUNDER discovery or MARKET_ACTION instead.

This processor:
- reads V4.0 Case / Claim / Unknown state;
- finds the next decision-relevant unknown for each case;
- assigns the cheapest appropriate research method first;
- computes a deterministic research-priority score;
- creates/updates a research action;
- creates per-case AI budget ledgers;
- does NOT call any LLM;
- does NOT perform deep research yet.

The goal is to make "what should we learn next?" explicit before execution.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

import structlog
from sqlalchemy import select

from database.connection import (
    async_session,
    RadarCase,
    RadarClaim,
    RadarUnknown,
    RadarResearchAction,
    RadarAIBudgetLedger,
)

log = structlog.get_logger().bind(processor="research_controller")
ENGINE_VERSION = "radar-atomic-evidence-controller-v4.1-strategic-handoff-r1"

# Hard gate order. Later gates should not consume research budget while an
# earlier blocking gate remains unresolved.
GATE_ORDER = [
    "PROBLEM_REALITY",
    "MARKET_REALITY",
    "SOLUTION_REALITY",
    "COMPANY_REALITY",
    "DISTRIBUTION_REALITY",
    "BUILD_REALITY",
    "RACE_DURABILITY",
    "VALIDATION",
]

# Maximum AI budget per case per controller cycle.
# Budget != amount to spend. It is only the ceiling if AI becomes necessary.
VERDICT_AI_CAP_TWD = {
    "IGNORE": 0.00,
    "PARK": 0.00,
    "WATCH": 0.05,
    "INVESTIGATE": 0.30,
    "VALIDATE": 1.00,
    "BUILD": 1.00,
}

# Deterministic defaults. Later versions can learn these empirically.
CLAIM_POLICY = {
    "C01": dict(answerability=0.98, urgency=0.95, cost=0.00, method="existing_evidence_audit"),
    "C02": dict(answerability=0.90, urgency=1.00, cost=0.00, method="local_problem_recurrence_search"),
    "C03": dict(answerability=0.70, urgency=0.80, cost=0.00, method="local_consequence_evidence_search"),
    "C04": dict(answerability=0.90, urgency=0.70, cost=0.00, method="local_actor_resolution"),
    "C05": dict(answerability=0.65, urgency=0.85, cost=0.00, method="market_buyer_signal_search"),
    "C06": dict(answerability=0.75, urgency=0.90, cost=0.00, method="solution_complaint_search"),
    "C07": dict(answerability=0.60, urgency=0.95, cost=0.00, method="solution_gap_evidence_search"),
    "C08": dict(answerability=0.55, urgency=0.80, cost=0.00, method="differentiation_evidence_search"),
    "C09": dict(answerability=0.95, urgency=0.95, cost=0.00, method="company_profile_match"),
    "C10": dict(answerability=0.55, urgency=0.90, cost=0.00, method="distribution_channel_search"),
    "C11": dict(answerability=0.50, urgency=0.75, cost=0.00, method="reference_class_cost_model"),
    "C12": dict(answerability=0.45, urgency=1.00, cost=0.00, method="temporal_window_analysis"),
    "C13": dict(answerability=0.55, urgency=1.00, cost=0.00, method="competitive_velocity_analysis"),
    "C14": dict(answerability=0.25, urgency=1.00, cost=0.00, method="human_validation_required"),
}

# AI is a fallback only, never first choice.
AI_FALLBACK = {
    "local_problem_recurrence_search": "same_problem_verify",
    "solution_complaint_search": "customer_complaint_extract",
    "solution_gap_evidence_search": "claim_stance_classify",
    "differentiation_evidence_search": "solution_scope_extract",
    "market_buyer_signal_search": "claim_stance_classify",
}

CLAIM_TYPE_TO_CODE = {
    "problem_exists": "C01",
    "problem_recurs": "C02",
    "consequence_material": "C03",
    "target_user_identifiable": "C04",
    "buyer_exists": "C05",
    "current_solution_unsatisfactory": "C06",
    "unresolved_gap_exists": "C07",
    "differentiation_possible": "C08",
    "company_can_execute": "C09",
    "distribution_feasible": "C10",
    "economics_plausible": "C11",
    "window_outlasts_execution": "C12",
    "competition_survivable": "C13",
    "customer_switch_plausible": "C14",
}


def clamp01(v: float | None, default: float) -> float:
    try:
        n = float(v if v is not None else default)
    except Exception:
        n = default
    return max(0.0, min(1.0, n))


def coverage_gap_for_claim(claim: RadarClaim) -> float:
    """1 = almost no useful coverage, 0 = well covered."""
    if claim.state == "UNKNOWN":
        return 1.0
    if claim.state == "INSUFFICIENT":
        required = max(1, int(claim.required_support_groups or 1))
        strongest = max(
            int(claim.support_groups or 0),
            int(claim.direct_support_groups or 0),
            int(claim.refute_groups or 0),
        )
        return max(0.25, min(1.0, 1.0 - strongest / required))
    if claim.state == "CONFLICTED":
        return 0.85
    return 0.0


def research_priority(
    *,
    decision_impact: float,
    reducibility: float,
    answerability: float,
    urgency: float,
    coverage_gap: float,
    estimated_cost_twd: float,
    redundancy_penalty: float = 1.0,
) -> float:
    """Deterministic approximation of Value of Information per research cost.

    Cost uses a soft denominator so NT$0 algorithmic work remains finite.
    """
    soft_cost = 1.0 + max(0.0, estimated_cost_twd)
    raw = (
        decision_impact
        * reducibility
        * answerability
        * urgency
        * coverage_gap
        * max(0.1, redundancy_penalty)
    ) / soft_cost
    return round(raw, 6)


def gate_index(gate: str) -> int:
    try:
        return GATE_ORDER.index(gate)
    except ValueError:
        return 999


async def _one_or_none(session, stmt):
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def run_research_controller() -> dict[str, Any]:
    now = datetime.now()
    cycle_key = now.strftime("%Y-%m-%d")
    summary = Counter()
    top_rows: list[dict[str, Any]] = []

    async with async_session() as session:
        cases = list((await session.execute(
            select(RadarCase).order_by(RadarCase.id)
        )).scalars().all())

        for case in cases:
            claims = list((await session.execute(
                select(RadarClaim)
                .where(RadarClaim.case_id == case.id)
                .order_by(RadarClaim.id)
            )).scalars().all())

            unknowns = list((await session.execute(
                select(RadarUnknown)
                .where(
                    RadarUnknown.case_id == case.id,
                    RadarUnknown.state == "OPEN",
                )
                .order_by(RadarUnknown.id)
            )).scalars().all())

            claim_by_id = {c.id: c for c in claims}

            # Find earliest unresolved blocking gate.
            unresolved_blocking = [
                c for c in claims
                if c.is_blocking and c.state not in {"SUPPORTED", "REFUTED"}
            ]
            if unresolved_blocking:
                earliest_gate = min(
                    (c.gate_group for c in unresolved_blocking),
                    key=gate_index,
                )
            else:
                earliest_gate = "VALIDATION"

            case.current_gate = earliest_gate

            # Budget ledger exists even though this planner spends nothing.
            budget = await _one_or_none(
                session,
                select(RadarAIBudgetLedger).where(
                    RadarAIBudgetLedger.case_id == case.id,
                    RadarAIBudgetLedger.cycle_key == cycle_key,
                ),
            )
            cap = float(VERDICT_AI_CAP_TWD.get(case.system_verdict, 0.05))
            if budget is None:
                budget = RadarAIBudgetLedger(
                    case_id=case.id,
                    cycle_key=cycle_key,
                    verdict_state=case.system_verdict,
                    budget_cap_twd=cap,
                    reserved_twd=0.0,
                    spent_twd=0.0,
                )
                session.add(budget)
                summary["budget_ledgers_created"] += 1
            else:
                budget.verdict_state = case.system_verdict
                budget.budget_cap_twd = cap
                summary["budget_ledgers_reused"] += 1

            candidates = []
            for u in unknowns:
                claim = claim_by_id.get(u.claim_id)
                if claim is None:
                    continue

                # Do not research later gates while an earlier blocking gate is open.
                if gate_index(claim.gate_group) > gate_index(earliest_gate):
                    continue

                policy = CLAIM_POLICY.get(claim.claim_code, {})
                answerability = clamp01(
                    u.answerability,
                    float(policy.get("answerability", 0.5)),
                )
                urgency = clamp01(
                    u.urgency,
                    float(policy.get("urgency", 0.5)),
                )
                reducibility = clamp01(u.reducibility, 0.9)
                impact = clamp01(u.decision_impact, 0.75)
                coverage_gap = coverage_gap_for_claim(claim)
                est_cost = float(policy.get("cost", 0.0))

                # Human-only tasks are not auto-ranked as machine work unless
                # we have reached the VALIDATION gate.
                if policy.get("method") == "human_validation_required" and earliest_gate != "VALIDATION":
                    continue

                priority = research_priority(
                    decision_impact=impact,
                    reducibility=reducibility,
                    answerability=answerability,
                    urgency=urgency,
                    coverage_gap=coverage_gap,
                    estimated_cost_twd=est_cost,
                )

                candidates.append((
                    priority,
                    u,
                    claim,
                    policy,
                    dict(
                        impact=impact,
                        reducibility=reducibility,
                        answerability=answerability,
                        urgency=urgency,
                        coverage_gap=coverage_gap,
                        est_cost=est_cost,
                    ),
                ))

            if not candidates:
                summary["cases_no_machine_action"] += 1
                continue

            candidates.sort(key=lambda x: x[0], reverse=True)
            priority, u, claim, policy, metrics = candidates[0]
            method = str(policy["method"])

            # First planned method is deterministic/free.
            ai_task = AI_FALLBACK.get(method)
            ai_allowed = False
            ai_reason = (
                "DENY: local/deterministic method must be attempted first."
                if ai_task
                else "DENY: no approved AI task is needed for the first method."
            )

            action_key = f"{case.case_key}:{u.unknown_code}:{method}:v4.1"
            action = await _one_or_none(
                session,
                select(RadarResearchAction).where(
                    RadarResearchAction.action_key == action_key
                ),
            )

            plan_meta = {
                "engine_version": ENGINE_VERSION,
                "gate": claim.gate_group,
                "claim_state": claim.state,
                "claim_type": claim.claim_type,
                "unknown_type": u.uncertainty_type,
                "algorithm_first": True,
                "ai_fallback_task": ai_task,
                "ai_budget_cap_twd": cap,
                "selection_reason": (
                    "Highest decision-value open unknown within the earliest unresolved blocking gate."
                ),
            }

            if action is None:
                action = RadarResearchAction(
                    case_id=case.id,
                    unknown_id=u.id,
                    action_key=action_key,
                    claim_code=claim.claim_code,
                    action_type="RESEARCH",
                    method=method,
                    status="PLANNED",
                    priority_score=priority,
                    decision_impact=metrics["impact"],
                    reducibility=metrics["reducibility"],
                    answerability=metrics["answerability"],
                    urgency=metrics["urgency"],
                    coverage_gap=metrics["coverage_gap"],
                    estimated_cost_twd=metrics["est_cost"],
                    estimated_llm_cost_twd=0.0,
                    ai_allowed=ai_allowed,
                    ai_task_name=ai_task,
                    ai_gate_reason=ai_reason,
                    attempt_count=0,
                    max_attempts=3,
                    plan_metadata=plan_meta,
                )
                session.add(action)
                summary["actions_created"] += 1
            else:
                action.priority_score = priority
                action.decision_impact = metrics["impact"]
                action.reducibility = metrics["reducibility"]
                action.answerability = metrics["answerability"]
                action.urgency = metrics["urgency"]
                action.coverage_gap = metrics["coverage_gap"]
                action.estimated_cost_twd = metrics["est_cost"]
                action.ai_allowed = ai_allowed
                action.ai_task_name = ai_task
                action.ai_gate_reason = ai_reason
                action.plan_metadata = plan_meta
                summary["actions_reused"] += 1

            # Mirror planning values to Unknown for inspectability.
            u.answerability = metrics["answerability"]
            u.urgency = metrics["urgency"]
            u.coverage_gap = metrics["coverage_gap"]
            u.estimated_cost_twd = metrics["est_cost"]
            u.priority_score = priority
            u.recommended_method = method

            summary[f"method_{method}"] += 1
            summary[f"claim_{claim.claim_code}"] += 1

            top_rows.append({
                "case": case.case_key,
                "claim": claim.claim_code,
                "method": method,
                "priority": priority,
                "ai": ai_task or "-",
            })

        await session.commit()

    top_rows.sort(key=lambda r: r["priority"], reverse=True)

    print()
    print("=" * 100)
    print("RADAR V4.1 — RESEARCH CONTROLLER")
    print("=" * 100)
    print(f"Cases evaluated: {len(cases)}")
    print(f"Actions created/reused: {summary['actions_created']} / {summary['actions_reused']}")
    print(f"AI budget ledgers created/reused: {summary['budget_ledgers_created']} / {summary['budget_ledgers_reused']}")
    print(f"Cases with no machine action: {summary['cases_no_machine_action']}")
    print()
    print("Top planned research actions:")
    for row in top_rows[:12]:
        print(
            f"  {row['priority']:.4f} | {row['claim']:>3s} | "
            f"{row['method']:<34s} | AI fallback: {row['ai']}"
        )
    print()
    print("IMPORTANT")
    print("  AI calls executed: 0")
    print("  AI cost this run: NT$0.00")
    print("  Every planned action starts with a deterministic/local method.")
    print("  AI fallback is only metadata; it is NOT authorized until local execution is exhausted.")
    print("=" * 100)

    founder_handoff = {"status": "UNAVAILABLE", "count": 0, "items": []}
    try:
        from processors.signalforge_brain_v2_engine import get_brain_v2_portfolio
        p = dict(get_brain_v2_portfolio())
        rows = list(p.get("founder_action_queue") or [])
        founder_handoff = {
            "status": p.get("status"),
            "count": len(rows),
            "items": rows[:20],
            "authority": "BRAIN_V2_FOUNDER_STRATEGY",
        }
    except Exception as exc:
        founder_handoff = {"status": "UNAVAILABLE", "count": 0, "items": [], "reason": f"{type(exc).__name__}: {exc}"}

    return {
        "engine_version": ENGINE_VERSION,
        "cases_evaluated": len(cases),
        "actions_created": summary["actions_created"],
        "actions_reused": summary["actions_reused"],
        "budget_ledgers_created": summary["budget_ledgers_created"],
        "llm_calls": 0,
        "llm_cost_twd": 0.0,
        "top_actions": top_rows[:12],
        "founder_action_handoff": founder_handoff,
        "authority": {
            "radar_evidence_planning": "THIS_CONTROLLER",
            "founder_next_action": "BRAIN_V2_STRATEGIC_ACTION_QUEUE",
            "market_truth_write": "NONE",
        },
        "truth_boundary": "Machine evidence planning cannot override a Brain MARKET_ACTION/FOUNDER_DISCOVERY/STOP_OR_PARTNER recommendation and cannot manufacture market outcomes.",
    }
