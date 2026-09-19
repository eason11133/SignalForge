
"""AI Budget Gate for Radar.

No code should call a Radar LLM task directly without passing this policy gate.

V4.1 defines the gate but does not wire it into the existing LLM client yet.
That happens only when a V4.x research executor actually needs an approved task.
"""

from __future__ import annotations

from dataclasses import dataclass

from processors.ai_task_registry import is_ai_task_approved


@dataclass(frozen=True)
class AIGateDecision:
    allowed: bool
    reason: str


def evaluate_ai_gate(
    *,
    task_name: str,
    local_attempted: bool,
    local_result: str | None,
    estimated_call_cost_twd: float,
    remaining_case_budget_twd: float,
    decision_impact: float,
) -> AIGateDecision:
    if not is_ai_task_approved(task_name):
        return AIGateDecision(False, "DENY_UNREGISTERED_TASK")

    if not local_attempted:
        return AIGateDecision(False, "DENY_ALGORITHM_FIRST")

    if str(local_result or "").upper() not in {
        "AMBIGUOUS",
        "INSUFFICIENT",
        "UNRESOLVED",
    }:
        return AIGateDecision(False, "DENY_LOCAL_RESULT_ALREADY_ACTIONABLE")

    if estimated_call_cost_twd < 0:
        return AIGateDecision(False, "DENY_INVALID_COST")

    if estimated_call_cost_twd > remaining_case_budget_twd:
        return AIGateDecision(False, "DENY_BUDGET")

    if float(decision_impact or 0) < 0.35:
        return AIGateDecision(False, "DENY_LOW_DECISION_VALUE")

    return AIGateDecision(True, "ALLOW_NARROW_AI_FALLBACK")
