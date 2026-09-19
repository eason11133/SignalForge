"""SignalForge Part 6 — Market Execution & Learning.

Founder-facing closure from a selected thesis to a pre-registered market test,
structured real-world outcome, explicit evidence promotion, and conservative
prospective calibration.

This module intentionally does *not* create a new Market Truth writer.  Atomic
C10/C11/C14 promotion is delegated to the existing quality-locked
`signalforge_validation_workflow`, which itself delegates to `market_ground_truth`.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from processors.signalforge_market_action_registry import (
    ACTION_TEMPLATES,
    ATOMIC_INGESTION_HINTS,
    complete_market_action,
    market_action_registry_report,
    register_market_action,
)
from processors.signalforge_market_learning_calibration import (
    learning_features_from_projection,
    market_learning_calibration_report,
)
from processors.signalforge_validation_workflow import (
    claim_validation_report,
    register_claim_validation,
    record_claim_validation_outcome,
)

ENGINE_VERSION = "signalforge-market-execution-learning-part6-v1"
TRUTH_BOUNDARY = (
    "PART6_ORCHESTRATES_TEST_DESIGN,_PREREGISTRATION,_OUTCOME_CAPTURE,_EXPLICIT_PROMOTION_AND_CALIBRATION;_"
    "ONLY_EXISTING_MARKET_GROUND_TRUTH_WORKFLOW_CAN_WRITE_C10_C11_C14"
)
MARKET_TRUTH_WRITES_DIRECT = 0

# Part 6 semantic closure: an action type may vary its threshold/sample before
# preregistration, but it may not redefine what kind of behavior counts as success.
ACTION_METRIC_POLICY: dict[str, tuple[str, ...]] = {
    "PAID_PILOT": ("paid_commitments",),
    "PAID_PILOT_OR_PREORDER_TEST": ("paid_commitments",),
    "PREORDER": ("paid_commitments",),
    "OUTREACH": ("qualified_replies",),
    "IDENTIFY_REACHABLE_BUYER_CHANNEL": ("qualified_replies",),
    "BUYER_INTERVIEW": ("decision_relevant_interviews",),
    "DOMAIN_EXPERT_OR_PRACTITIONER_INTERVIEW": ("decision_relevant_interviews",),
    "PROTOTYPE": ("repeat_workflow_users",),
    "BUILD_OR_BORROW_LEGITIMACY": ("credible_partner_commitments",),
    "BOUNDED_CUSTOMER_TEST": ("target_behavior_count",),
    "LANDING_PAGE": ("high_intent_actions",),
}

ACTION_SEMANTIC_FAMILY: dict[str, str] = {
    "PAID_PILOT": "PAID_COMMITMENT",
    "PAID_PILOT_OR_PREORDER_TEST": "PAID_COMMITMENT",
    "PREORDER": "PAID_COMMITMENT",
    "OUTREACH": "QUALIFIED_RESPONSE",
    "IDENTIFY_REACHABLE_BUYER_CHANNEL": "FOUNDER_BUYER_ACCESS",
    "BUYER_INTERVIEW": "BUYER_DISCOVERY",
    "DOMAIN_EXPERT_OR_PRACTITIONER_INTERVIEW": "FOUNDER_DOMAIN_DISCOVERY",
    "PROTOTYPE": "WORKFLOW_USAGE",
    "BUILD_OR_BORROW_LEGITIMACY": "FOUNDER_LEGITIMACY",
    "BOUNDED_CUSTOMER_TEST": "TARGET_BEHAVIOR",
    "LANDING_PAGE": "HIGH_INTENT_CONVERSION",
}

FOUNDER_DISCOVERY_ACTIONS = {
    "IDENTIFY_REACHABLE_BUYER_CHANNEL",
    "DOMAIN_EXPERT_OR_PRACTITIONER_INTERVIEW",
    "BUILD_OR_BORROW_LEGITIMACY",
}


def _clean(v: Any, limit: int = 6000) -> str:
    return " ".join(str(v or "").split())[:limit]


def _upper(v: Any) -> str:
    return _clean(v, 240).upper()


def _mapping(v: Any) -> Mapping[str, Any]:
    return v if isinstance(v, Mapping) else {}


def _list(v: Any) -> list[Any]:
    return list(v) if isinstance(v, (list, tuple, set)) else []


def _positive_int(v: Any, default: int = 0) -> int:
    try:
        return max(0, int(v))
    except Exception:
        return max(0, int(default))


def _positive_float(v: Any) -> float | None:
    if v in (None, ""):
        return None
    try:
        x = float(v)
    except Exception:
        return None
    return x if x > 0 else None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _portfolio_thesis(thesis_id: str) -> dict[str, Any]:
    from processors.signalforge_brain_v2_engine import get_brain_v2_portfolio
    portfolio = dict(get_brain_v2_portfolio())
    for row in portfolio.get("portfolio") or []:
        if isinstance(row, Mapping) and str(row.get("thesis_id") or "") == str(thesis_id):
            return dict(row)
    raise ValueError(f"thesis {thesis_id!r} not found in current Brain portfolio")


def _decision_rule(action_type: str, sample_target: int) -> dict[str, Any]:
    """Return a semantic-locked preregistration heuristic, never Market Truth."""
    action = _upper(action_type)
    n = max(1, int(sample_target or 1))
    metric = (ACTION_METRIC_POLICY.get(action) or ("target_behavior_count",))[0]
    if action in {"PAID_PILOT", "PAID_PILOT_OR_PREORDER_TEST", "PREORDER"}:
        success_min = 1
    elif action in {"OUTREACH", "IDENTIFY_REACHABLE_BUYER_CHANNEL"}:
        success_min = max(1, math.ceil(n * 0.10))
    elif action in {"BUYER_INTERVIEW", "DOMAIN_EXPERT_OR_PRACTITIONER_INTERVIEW"}:
        success_min = max(1, math.ceil(n * 0.50))
    elif action == "PROTOTYPE":
        success_min = max(1, math.ceil(n * 0.50))
    elif action == "BUILD_OR_BORROW_LEGITIMACY":
        success_min = 1
    else:
        success_min = max(1, math.ceil(n * 0.40))
    category = _mapping(ACTION_TEMPLATES.get(action)).get("category")
    return {
        "metric": metric,
        "metric_family": ACTION_SEMANTIC_FAMILY.get(action, "TARGET_BEHAVIOR"),
        "operator": ">=",
        "success_min": int(success_min),
        "failure_rule": "SAMPLE_TARGET_REACHED_AND_SUCCESS_THRESHOLD_NOT_MET",
        "inconclusive_rule": "SAMPLE_TARGET_NOT_REACHED_OR_REQUIRED_OBSERVATION_QUALITY_MISSING_OR_PREREGISTERED_COST_BREACH",
        "sample_target": n,
        "allowed_metrics": list(ACTION_METRIC_POLICY.get(action) or (metric,)),
        "calibration_domain": "FOUNDER_ADDRESSABILITY" if category == "FOUNDER_DISCOVERY" else "FAST_VALIDATION",
        "authority": "FOUNDER_EDITABLE_THRESHOLD_WITH_ACTION_SEMANTICS_LOCKED_NOT_MARKET_TRUTH",
    }


def buyer_outreach_pack(thesis: Mapping[str, Any], trail: Mapping[str, Any], action_type: str) -> dict[str, Any]:
    playbook = _mapping(trail.get("founder_playbook"))
    segment = _mapping(trail.get("buyer_segment"))
    wedge = _mapping(trail.get("possible_revenue_wedge"))
    action = _upper(action_type)
    who = segment.get("label") or segment.get("segment") or _mapping(trail.get("buyer")).get("segment") or "UNKNOWN_TARGET_BUYER"
    channels = _list(playbook.get("channels"))
    if not channels:
        channels = _list(_mapping(trail.get("cheapest_test")).get("channels"))
    questions = _list(playbook.get("behavior_questions")) or _list(playbook.get("questions"))
    if not questions:
        questions = [
            "Show the current workflow and where time/money is actually spent.",
            "What happens if this problem is not solved this month?",
            "What have you already tried or paid for?",
            "Who owns the budget or approval for changing this workflow?",
            "What concrete action would you take next if this solved the problem?",
        ]
    evidence = [
        "identified actor / role",
        "current spend or labor workaround",
        "observed workflow behavior",
        "failed/current solutions",
        "actual willingness to act or pay",
        "durable evidence reference (note, screenshot, invoice, signed pilot, receipt, or equivalent)",
    ]
    if action in {"PAID_PILOT", "PAID_PILOT_OR_PREORDER_TEST", "PREORDER"}:
        evidence += ["actual amount", "currency", "payment/deposit/signed paid-pilot evidence"]
    return {
        "who": who,
        "where": channels or ["NO_EVIDENCE_BACKED_CHANNEL_YET — validate buyer access before broad outreach"],
        "what_to_ask": questions[:8],
        "what_not_to_say": [
            "Do not lead with 'Would you use this?' or ask for compliments.",
            "Do not disclose the desired success threshold before observing current behavior.",
            "Do not convert interest, likes, or 'sounds useful' into willingness-to-pay evidence.",
            "Do not claim the structural thesis is proven by one wedge test.",
        ],
        "evidence_to_capture": evidence,
        "offer_or_wedge": wedge.get("statement") or "UNKNOWN — test the smallest current wedge, not a full platform story",
        "truth_boundary": "OUTREACH_PACK_IS_EXECUTION_GUIDANCE;_BUYER_REPLIES_BECOME_EVIDENCE_ONLY_THROUGH_STRUCTURED_OUTCOME_AND_EXISTING_VALIDATION_AUTHORITY",
    }


def _execution_authority_for_founder_action(founder_action: str, action_type: str) -> dict[str, Any]:
    founder_action = _upper(founder_action)
    action_type = _upper(action_type)
    category = _upper(_mapping(ACTION_TEMPLATES.get(action_type)).get("category"))
    if founder_action == "ACTION_NOW":
        return {"allowed": True, "mode": "MARKET_EXECUTION", "reason": "Part 4 Founder actionability explicitly authorizes action now."}
    if founder_action == "VALIDATE_DISTRIBUTION" and action_type in FOUNDER_DISCOVERY_ACTIONS:
        return {"allowed": True, "mode": "FOUNDER_DISCOVERY", "reason": "Only distribution/addressability discovery is allowed while the Part 4 distribution gate is unresolved."}
    if founder_action == "INVESTIGATE" and category == "FOUNDER_DISCOVERY":
        return {"allowed": True, "mode": "FOUNDER_DISCOVERY", "reason": "Investigation may run only as Founder discovery, not as a paid-market success test."}
    return {
        "allowed": False,
        "mode": "BLOCKED_BY_PART4_FOUNDER_ACTIONABILITY",
        "reason": f"Part 4 Founder Action={founder_action or 'UNKNOWN'} does not authorize formal Part 6 market preregistration for {action_type or 'UNKNOWN'}.",
    }


def _action_for_founder_projection(thesis: Mapping[str, Any], decision_item: Mapping[str, Any]) -> str:
    founder_action = _upper(decision_item.get("founder_action"))
    best = _mapping(thesis.get("best_next_action"))
    brain_action = _upper(best.get("action"))
    if founder_action == "VALIDATE_DISTRIBUTION":
        return "IDENTIFY_REACHABLE_BUYER_CHANNEL"
    if founder_action == "INVESTIGATE":
        return "DOMAIN_EXPERT_OR_PRACTITIONER_INTERVIEW"
    if founder_action in {"PARK", "PARK_OR_PARTNER", "WATCH"}:
        # Keep a non-executable design object so Founder can see why execution is blocked.
        return brain_action if brain_action in ACTION_TEMPLATES else "BUYER_INTERVIEW"
    if founder_action == "NARROW_WEDGE":
        return "BUYER_INTERVIEW"
    return brain_action if brain_action in ACTION_TEMPLATES else ("BOUNDED_CUSTOMER_TEST" if _upper(best.get("mode")) == "MARKET_ACTION" else "DOMAIN_EXPERT_OR_PRACTITIONER_INTERVIEW")


def build_market_test_design_from_projection(
    thesis: Mapping[str, Any],
    trail: Mapping[str, Any],
    decision_item: Mapping[str, Any],
    *,
    max_sample: int | None = None,
    max_cost: float | None = None,
    cost_currency: str | None = None,
) -> dict[str, Any]:
    best = _mapping(thesis.get("best_next_action"))
    founder_action = _upper(decision_item.get("founder_action")) or "UNKNOWN"
    action_type = _action_for_founder_projection(thesis, decision_item)
    template = _mapping(ACTION_TEMPLATES.get(action_type))
    sample = max_sample if max_sample is not None else _positive_int(template.get("default_sample"), 1)
    sample = max(1, min(int(sample or 1), 500))
    rule = _decision_rule(action_type, sample)
    hypothesis = (
        _mapping(trail.get("possible_revenue_wedge")).get("statement")
        or thesis.get("representative_problem")
        or thesis.get("representative_title")
        or "UNKNOWN_HYPOTHESIS"
    )
    target = _mapping(trail.get("buyer_segment")).get("label") or template.get("target") or "UNKNOWN_TARGET"
    current_track = decision_item.get("market_track") or decision_item.get("current_track") or "UNKNOWN"
    founder_action = decision_item.get("founder_action") or "UNKNOWN"
    atomic_hint = dict(ATOMIC_INGESTION_HINTS.get(action_type) or {})
    features = learning_features_from_projection(thesis, trail, decision_item)
    features = {
        **features,
        "recommended_action_type": action_type,
        "action_semantic_family": ACTION_SEMANTIC_FAMILY.get(action_type, "TARGET_BEHAVIOR"),
        "calibration_domain": rule.get("calibration_domain"),
        "metric_family": rule.get("metric_family"),
    }
    execution_authority = _execution_authority_for_founder_action(founder_action, action_type)
    return {
        "engine_version": ENGINE_VERSION,
        "thesis_id": thesis.get("thesis_id"),
        "title": thesis.get("representative_title"),
        "market_track": current_track,
        "founder_action": founder_action,
        "execution_authority": execution_authority,
        "hypothesis": _clean(hypothesis),
        "target": _clean(target),
        "test": {
            "action_type": action_type,
            "category": template.get("category"),
            "instruction": _mapping(trail.get("cheapest_test")).get("instruction") or best.get("reason") or f"Run a bounded {action_type} test.",
            "offer": _mapping(trail.get("possible_revenue_wedge")).get("statement"),
        },
        "success": {
            "criterion": template.get("success_signal"),
            "decision_rule": rule,
        },
        "failure": {
            "criterion": template.get("failure_signal"),
            "decision_rule": rule.get("failure_rule"),
        },
        "inconclusive": {
            "criterion": "Sample/evidence quality is insufficient to apply the pre-registered decision rule.",
            "decision_rule": rule.get("inconclusive_rule"),
        },
        "max_sample": sample,
        "max_cost": _positive_float(max_cost),
        "max_cost_currency": _clean(cost_currency, 12) or None,
        "cost_boundary": "FOUNDER_SET" if _positive_float(max_cost) is not None else "NOT_SET — SignalForge does not invent a numeric budget",
        "buyer_outreach_pack": buyer_outreach_pack(thesis, trail, action_type),
        "atomic_promotion_hint": {
            "event": atomic_hint.get("event"),
            "claims": atomic_hint.get("claims") or [],
            "requires_claim_specific_preregistration_before_outcome": bool(atomic_hint),
        },
        "learning_features": features,
        "frozen_on_preregistration": False,
        "market_truth_writes": 0,
        "truth_boundary": "TEST_DESIGN_IS_A_FOUNDER_EXECUTION_PLAN_NOT_MARKET_EVIDENCE;_OUTCOME_THRESHOLDS_ARE_EDITABLE_ONLY_BEFORE_PREREGISTRATION",
    }


async def design_market_test(*, thesis_id: str, max_sample: int | None = None, max_cost: float | None = None, cost_currency: str | None = None) -> dict[str, Any]:
    from processors.signalforge_money_trail import build_money_trail_for_thesis
    from processors.signalforge_opportunity_decision import build_decision_item
    from processors.signalforge_opportunity_decision_closure import decorate_item
    thesis = _portfolio_thesis(thesis_id)
    trail = await build_money_trail_for_thesis(thesis)
    decision_item = decorate_item(thesis, trail, build_decision_item(thesis, trail))
    return build_market_test_design_from_projection(thesis, trail, decision_item, max_sample=max_sample, max_cost=max_cost, cost_currency=cost_currency)


def _override_rule(design: Mapping[str, Any], override: Mapping[str, Any] | None) -> dict[str, Any]:
    base = dict(_mapping(_mapping(design.get("success")).get("decision_rule")))
    ov = _mapping(override)
    action_type = _upper(_mapping(design.get("test")).get("action_type"))
    allowed = set(ACTION_METRIC_POLICY.get(action_type) or (base.get("metric"),))
    if ov:
        requested_metric = _clean(ov.get("metric"), 120)
        if requested_metric and requested_metric not in allowed:
            raise ValueError(
                f"decision metric {requested_metric!r} is not valid for action {action_type}; "
                f"allowed={sorted(x for x in allowed if x)}. Thresholds may change before preregistration; action semantics may not."
            )
        success_min = _positive_int(ov.get("success_min"))
        if requested_metric:
            base["metric"] = requested_metric
        if success_min > 0:
            sample_target = _positive_int(base.get("sample_target"), 1)
            if success_min > sample_target:
                raise ValueError(f"success_min={success_min} cannot exceed preregistered sample_target={sample_target}")
            base["success_min"] = success_min
        base["authority"] = "FOUNDER_CONFIRMED_THRESHOLD_ACTION_SEMANTICS_LOCKED"
    base["allowed_metrics"] = sorted(x for x in allowed if x)
    return base


async def preregister_market_test(
    *,
    thesis_id: str,
    max_sample: int | None = None,
    max_cost: float | None = None,
    cost_currency: str | None = None,
    decision_rule_override: Mapping[str, Any] | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    design = await design_market_test(thesis_id=thesis_id, max_sample=max_sample, max_cost=max_cost, cost_currency=cost_currency)
    authority = _mapping(design.get("execution_authority"))
    if not bool(authority.get("allowed")):
        raise ValueError(str(authority.get("reason") or "Part 4 Founder actionability does not authorize Part 6 execution"))
    rule = _override_rule(design, decision_rule_override)
    design = {**design, "success": {**_mapping(design.get("success")), "decision_rule": rule}, "frozen_on_preregistration": True, "preregistered_at": _now()}
    action_type = _upper(_mapping(design.get("test")).get("action_type"))
    outreach = _mapping(design.get("buyer_outreach_pack"))
    record = register_market_action(
        thesis_id=thesis_id,
        action_type=action_type,
        sample_target=int(design.get("max_sample") or 1),
        success_criteria=_mapping(design.get("success")).get("criterion"),
        failure_criteria=_mapping(design.get("failure")).get("criterion"),
        note=note,
        part6_test_design=design,
        decision_rule=rule,
        inconclusive_criteria=_mapping(design.get("inconclusive")).get("criterion"),
        max_cost=design.get("max_cost"),
        max_cost_currency=design.get("max_cost_currency"),
        buyer_outreach_pack=outreach,
        learning_features=_mapping(design.get("learning_features")),
    )
    return {
        "engine_version": ENGINE_VERSION,
        "status": "PREREGISTERED",
        "action": record,
        "design": design,
        "next_step": "Run the bounded test. If atomic C10/C11/C14 promotion may matter, pre-register a matching claim experiment before observing the outcome.",
        "market_truth_writes": 0,
        "truth_boundary": "PREREGISTRATION_FREEZES_DECISION_RULE_AND_PRETEST_FEATURES_BUT_CREATES_NO_MARKET_EVIDENCE",
    }


def _find_action(action_id: str) -> dict[str, Any]:
    for row in market_action_registry_report().get("rows") or []:
        if str(row.get("action_id") or "") == str(action_id):
            return dict(row)
    raise ValueError(f"market action {action_id!r} not found")


async def claim_preregistration_options(action_id: str) -> dict[str, Any]:
    action = _find_action(action_id)
    if _upper(action.get("status")) == "COMPLETED":
        return {"action_id": action_id, "status": "CLOSED", "items": [], "reason": "Outcome already exists; claim experiments cannot be created retroactively for this action."}
    hint = dict(ATOMIC_INGESTION_HINTS.get(_upper(action.get("action_type"))) or {})
    wanted_claims = set(hint.get("claims") or [])
    candidates = {int(x) for x in _list(_mapping(action.get("pretest_snapshot")).get("member_candidate_ids")) if str(x).isdigit() and int(x) > 0}
    items: list[dict[str, Any]] = []
    if candidates and wanted_claims:
        try:
            from processors.opportunity_decision import run_opportunity_decision
            decision = await run_opportunity_decision(limit=200, reality_mode="persisted")
            for row in decision.get("rows") or []:
                cid = int(row.get("candidate_id") or 0)
                case_id = int(row.get("case_id") or 0)
                if cid not in candidates or case_id <= 0:
                    continue
                prepared = _mapping(row.get("prepared_validation_plans"))
                for claim in sorted(wanted_claims):
                    if claim in prepared:
                        items.append({
                            "case_id": case_id,
                            "candidate_id": cid,
                            "claim_code": claim,
                            "event": {"C10": "ACQUISITION", "C11": "PRICE", "C14": "SWITCH"}.get(claim),
                            "already_pending": False,
                        })
        except Exception as exc:
            return {"action_id": action_id, "status": "DECISION_DATA_UNAVAILABLE", "items": [], "error": f"{type(exc).__name__}: {exc}", "truth_boundary": "NO_OPTION_IS_INFERRED_WHEN_CASE_MAPPING_IS_UNAVAILABLE"}
    pending = [x for x in claim_validation_report().get("rows") or [] if _upper(x.get("status")) == "PENDING"]
    for item in items:
        item["already_pending"] = any(
            int(x.get("case_id") or 0) == item["case_id"]
            and _upper(x.get("claim_code")) == item["claim_code"]
            and str(x.get("market_action_id") or "") == str(action_id)
            for x in pending
        )
    return {
        "action_id": action_id,
        "status": "READY" if items else "NO_ATOMIC_PREREGISTRATION_OPTION",
        "suggested_event": hint.get("event"),
        "suggested_claims": sorted(wanted_claims),
        "items": items,
        "truth_boundary": "OPTIONS_ONLY_EXPOSE_EXISTING_CASES_AND_PREPARED_CLAIM_VALIDATION_PATHS;_THEY_DO_NOT_CREATE_EVIDENCE",
    }


async def preregister_claim_for_action(*, action_id: str, case_id: int, claim_code: str, note: str | None = None) -> dict[str, Any]:
    action = _find_action(action_id)
    if _upper(action.get("status")) == "COMPLETED":
        raise ValueError("claim experiment must be pre-registered before the market action outcome")
    candidates = {int(x) for x in _list(_mapping(action.get("pretest_snapshot")).get("member_candidate_ids")) if str(x).isdigit() and int(x) > 0}
    options = await claim_preregistration_options(action_id)
    allowed = {(int(x.get("case_id") or 0), _upper(x.get("claim_code"))) for x in options.get("items") or []}
    key = (int(case_id), _upper(claim_code))
    if key not in allowed:
        raise ValueError("requested case/claim is not an evidence-backed preregistration option for this action")
    matching_option = next((x for x in options.get("items") or [] if (int(x.get("case_id") or 0), _upper(x.get("claim_code"))) == key), {})
    if bool(matching_option.get("already_pending")):
        raise ValueError("this market action already has a pending experiment for the requested case/claim")
    exp = await register_claim_validation(
        case_id=int(case_id),
        claim_code=_upper(claim_code),
        note=note or f"Part 6 linked to market action {action_id}",
        market_action_id=str(action_id),
    )
    return {
        "engine_version": ENGINE_VERSION,
        "status": "CLAIM_EXPERIMENT_PREREGISTERED",
        "action_id": action_id,
        "experiment": exp,
        "candidate_scope": sorted(candidates),
        "market_truth_writes": 0,
        "truth_boundary": "CLAIM_EXPERIMENT_IS_FROZEN_BEFORE_OUTCOME;_NO_MARKET_EVIDENCE_EXISTS_YET",
    }


def _observation_records(
    *,
    actor_labels: Sequence[str] | None,
    evidence_refs: Sequence[str] | None,
    observation_records: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    explicit = [dict(x) for x in (observation_records or []) if isinstance(x, Mapping)]
    if explicit:
        rows = []
        for i, row in enumerate(explicit, 1):
            actor = _clean(row.get("actor_label"), 240)
            ref = _clean(row.get("evidence_ref"), 1000)
            if not actor or not ref:
                continue
            rows.append({
                "observation_id": _clean(row.get("observation_id"), 160) or f"obs-{i}",
                "actor_label": actor,
                "evidence_ref": ref,
                "observed_behavior": _clean(row.get("observed_behavior")),
                "decision_relevant_finding": _clean(row.get("decision_relevant_finding")),
                "signals": dict(_mapping(row.get("signals"))),
            })
        return rows
    actors = [_clean(x, 240) for x in (actor_labels or []) if _clean(x, 240)]
    refs = [_clean(x, 1000) for x in (evidence_refs or []) if _clean(x, 1000)]
    # Backward-compatible transport, but sample size is derived only from paired durable records.
    return [
        {"observation_id": f"obs-{i+1}", "actor_label": actor, "evidence_ref": refs[i], "signals": {}}
        for i, actor in enumerate(actors[: len(refs)])
    ]


def _cost_evaluation(action: Mapping[str, Any], *, actual_cost: float | None, actual_cost_currency: str | None) -> dict[str, Any]:
    maximum = _positive_float(action.get("max_cost"))
    max_currency = _clean(action.get("max_cost_currency"), 20).upper() or None
    if maximum is None:
        return {"status": "NO_PREREGISTERED_MAX_COST", "breached": False, "max_cost": None, "actual_cost": _positive_float(actual_cost)}
    actual = _positive_float(actual_cost)
    currency = _clean(actual_cost_currency, 20).upper() or None
    if actual is None:
        return {"status": "ACTUAL_COST_REQUIRED", "breached": None, "max_cost": maximum, "max_currency": max_currency, "actual_cost": None}
    if max_currency and currency != max_currency:
        return {"status": "CURRENCY_MISMATCH", "breached": None, "max_cost": maximum, "max_currency": max_currency, "actual_cost": actual, "actual_currency": currency}
    breached = actual > maximum
    return {"status": "BREACHED" if breached else "WITHIN_LIMIT", "breached": breached, "max_cost": maximum, "max_currency": max_currency, "actual_cost": actual, "actual_currency": currency or max_currency}


def evaluate_outcome_against_preregistered_rule(
    action: Mapping[str, Any],
    outcome_counts: Mapping[str, Any],
    *,
    observed_sample_size: int | None = None,
    actual_cost: float | None = None,
    actual_cost_currency: str | None = None,
) -> dict[str, Any]:
    rule = _mapping(action.get("decision_rule")) or _mapping(_mapping(_mapping(action.get("part6_test_design")).get("success")).get("decision_rule"))
    if not rule:
        return {"result": "INCONCLUSIVE", "reason": "NO_STRUCTURED_PREREGISTERED_RULE", "rule": {}, "metric_value": None}
    action_type = _upper(action.get("action_type"))
    allowed = set(ACTION_METRIC_POLICY.get(action_type) or _list(rule.get("allowed_metrics")) or [rule.get("metric")])
    metric = _clean(rule.get("metric"), 120)
    if metric not in allowed:
        return {"result": "INCONCLUSIVE", "reason": "PREREGISTERED_METRIC_VIOLATES_ACTION_SEMANTICS", "rule": dict(rule), "metric": metric}
    sample_target = _positive_int(action.get("sample_target") or rule.get("sample_target"), 1)
    observed = (
        _positive_int(observed_sample_size, 0)
        if observed_sample_size is not None
        else _positive_int(outcome_counts.get("contacted") or outcome_counts.get("observed_sample_size") or outcome_counts.get("sample"), 0)
    )
    metric_value = _positive_int(outcome_counts.get(metric), 0)
    success_min = _positive_int(rule.get("success_min"), 1)
    cost_eval = _cost_evaluation(action, actual_cost=actual_cost, actual_cost_currency=actual_cost_currency)
    if cost_eval.get("status") in {"ACTUAL_COST_REQUIRED", "CURRENCY_MISMATCH", "BREACHED"}:
        result, reason = "INCONCLUSIVE", f"PREREGISTERED_COST_CONTRACT_{cost_eval.get('status')}"
    elif observed < sample_target:
        result, reason = "INCONCLUSIVE", f"OBSERVED_DURABLE_RECORDS_{observed}_BELOW_PREREGISTERED_{sample_target}"
    elif metric_value > observed:
        result, reason = "INCONCLUSIVE", f"METRIC_{metric}_COUNT_{metric_value}_EXCEEDS_DURABLE_OBSERVATIONS_{observed}"
    elif metric_value >= success_min:
        result, reason = "PASS", f"{metric}={metric_value} >= preregistered {success_min}"
    else:
        result, reason = "FAIL", f"sample target reached and {metric}={metric_value} < preregistered {success_min}"
    return {
        "result": result,
        "reason": reason,
        "rule": dict(rule),
        "metric": metric,
        "metric_value": metric_value,
        "success_min": success_min,
        "observed_sample_size": observed,
        "sample_target": sample_target,
        "cost_evaluation": cost_eval,
        "retrospective_result_override_allowed": False,
    }


def capture_market_outcome(
    *,
    action_id: str,
    outcome_counts: Mapping[str, Any],
    actor_labels: Sequence[str] | None = None,
    evidence_refs: Sequence[str] | None = None,
    observation_records: Sequence[Mapping[str, Any]] | None = None,
    observed_behavior: str | None = None,
    decision_relevant_findings: str | None = None,
    reason_counts: Mapping[str, Any] | None = None,
    amount: float | None = None,
    currency: str | None = None,
    actual_cost: float | None = None,
    actual_cost_currency: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    action = _find_action(action_id)
    if _upper(action.get("status")) == "COMPLETED":
        raise ValueError(f"market action {action_id} already completed; outcome is immutable")
    records = _observation_records(actor_labels=actor_labels, evidence_refs=evidence_refs, observation_records=observation_records)
    actors = [str(x.get("actor_label")) for x in records]
    refs = [str(x.get("evidence_ref")) for x in records]
    evaluated = evaluate_outcome_against_preregistered_rule(
        action, outcome_counts, observed_sample_size=len(records), actual_cost=actual_cost, actual_cost_currency=actual_cost_currency
    )
    observations = {
        "observed_sample_size": len(records),
        "submitted_sample_count": _positive_int(outcome_counts.get("contacted") or outcome_counts.get("observed_sample_size") or outcome_counts.get("sample"), 0),
        "observation_records": records,
        "actor_labels": actors,
        "actor_label": actors[0] if actors else None,
        "evidence_refs": refs,
        "observed_behavior": _clean(observed_behavior),
        "decision_relevant_findings": _clean(decision_relevant_findings),
        "outcome_counts": dict(outcome_counts),
        "reason_counts": dict(reason_counts or {}),
        "decision_rule_evaluation": evaluated,
        "amount": _positive_float(amount),
        "currency": _clean(currency, 20) or None,
        "actual_cost": _positive_float(actual_cost),
        "actual_cost_currency": _clean(actual_cost_currency, 20) or None,
        "cost_evaluation": dict(_mapping(evaluated.get("cost_evaluation"))),
        "captured_at": _now(),
    }
    completed = complete_market_action(
        action_id=action_id, result=str(evaluated.get("result")), observations=observations, note=note or evaluated.get("reason")
    )
    return {
        "engine_version": ENGINE_VERSION,
        "status": "OUTCOME_CAPTURED",
        "action": completed,
        "decision_rule_evaluation": evaluated,
        "atomic_market_truth_promoted": False,
        "next_step": "Review claim-specific promotion options. Market Truth is unchanged until Founder explicitly promotes a semantically matching pre-registered claim experiment.",
        "market_truth_writes": 0,
        "truth_boundary": "OUTCOME_SAMPLE_IS_DERIVED_FROM_DURABLE_PER_OBSERVATION_RECORDS;_COST_BREACHES_CANNOT_ENTER_CALIBRATION_AS_CLEAN_PASS;_NO_AUTO_C10_C11_C14_PROMOTION",
    }


def _claim_promotion_condition(action: Mapping[str, Any], claim: str) -> tuple[bool, str]:
    obs = _mapping(action.get("observations"))
    counts = _mapping(obs.get("outcome_counts"))
    if _upper(action.get("result")) != "PASS":
        return False, "ACTION_NOT_PASS"
    if claim == "C10":
        acquisition = max(_positive_int(counts.get("qualified_replies")), _positive_int(counts.get("paid_commitments")), _positive_int(counts.get("target_behavior_count")))
        return (acquisition > 0, "ACQUISITION_BEHAVIOR_REQUIRED" if acquisition <= 0 else "MATCH")
    if claim == "C11":
        paid = _positive_int(counts.get("paid_commitments"))
        ok = paid > 0 and _positive_float(obs.get("amount")) is not None and bool(_clean(obs.get("currency"), 20))
        return (ok, "POSITIVE_PAID_COMMITMENT_WITH_AMOUNT_AND_CURRENCY_REQUIRED" if not ok else "MATCH")
    if claim == "C14":
        switches = _positive_int(counts.get("switches"))
        return (switches > 0, "OBSERVED_SWITCH_BEHAVIOR_REQUIRED" if switches <= 0 else "MATCH")
    return False, "UNSUPPORTED_CLAIM"


def promotion_options(action_id: str) -> dict[str, Any]:
    action = _find_action(action_id)
    if _upper(action.get("status")) != "COMPLETED" or _upper(action.get("result")) not in {"PASS", "FAIL"}:
        return {"action_id": action_id, "status": "NO_BINARY_COMPLETED_OUTCOME", "items": [], "market_truth_writes": 0}
    obs = _mapping(action.get("observations"))
    completed_at = str(action.get("completed_at") or "")
    thesis_id = str(action.get("thesis_id") or "")
    member_candidates = {int(x) for x in _list(_mapping(action.get("pretest_snapshot")).get("member_candidate_ids")) if str(x).isdigit() and int(x) > 0}
    hint = dict(ATOMIC_INGESTION_HINTS.get(_upper(action.get("action_type"))) or {})
    allowed_claims = set(hint.get("claims") or [])
    rows = claim_validation_report().get("rows") or []
    items = []
    excluded = []
    for exp in rows:
        if _upper(exp.get("status")) != "PENDING" or str(exp.get("market_action_id") or "") != str(action_id):
            continue
        snap = _mapping(exp.get("pretest_snapshot"))
        strategy = _mapping(snap.get("strategic_snapshot"))
        candidate_id = int(snap.get("candidate_id") or 0)
        claim = _upper(exp.get("claim_code"))
        created_at = str(exp.get("created_at") or "")
        if claim not in allowed_claims:
            continue
        if member_candidates and candidate_id not in member_candidates:
            continue
        if strategy.get("thesis_id") and str(strategy.get("thesis_id")) != thesis_id:
            continue
        if completed_at and created_at and created_at > completed_at:
            continue
        semantic_ok, semantic_reason = _claim_promotion_condition(action, claim)
        if not semantic_ok:
            excluded.append({"experiment_id": exp.get("experiment_id"), "claim_code": claim, "reason": semantic_reason})
            continue
        items.append({
            "experiment_id": exp.get("experiment_id"),
            "market_action_id": exp.get("market_action_id"),
            "case_id": exp.get("case_id"),
            "candidate_id": candidate_id,
            "claim_code": claim,
            "registered_event": exp.get("event"),
            "registered_at": created_at,
            "action_result": action.get("result"),
            # Promotion is claim-specific. A paid pilot does not magically become a switch event.
            "suggested_record_event": exp.get("event"),
            "actor_label": obs.get("actor_label") or (obs.get("actor_labels") or [None])[0],
            "amount": obs.get("amount") if claim == "C11" else None,
            "currency": obs.get("currency") if claim == "C11" else None,
            "semantic_condition": semantic_reason,
            "explicit_founder_promotion_required": True,
        })
    return {
        "action_id": action_id,
        "status": "READY" if items else "NO_SEMANTICALLY_MATCHING_PRE_OUTCOME_CLAIM_EXPERIMENT",
        "items": items,
        "excluded": excluded,
        "market_truth_writes": 0,
        "truth_boundary": "PROMOTION_REQUIRES_SAME_ACTION,_PRE_OUTCOME_PREREGISTRATION,_SAME_THESIS/CANDIDATE/CLAIM_AND_CLAIM_SPECIFIC_OBSERVED_BEHAVIOR;_NO_RETROACTIVE_OR_CROSS_ACTION_PREREGISTRATION;_PAID_PILOT_DOES_NOT_IMPLY_SWITCH",
    }


async def promote_market_outcome(*, action_id: str, experiment_id: str, note: str | None = None) -> dict[str, Any]:
    options = promotion_options(action_id)
    match = next((x for x in options.get("items") or [] if str(x.get("experiment_id")) == str(experiment_id)), None)
    if match is None:
        raise ValueError("experiment is not an eligible pre-outcome promotion option for this action")
    action = _find_action(action_id)
    obs = _mapping(action.get("observations"))
    result = _upper(action.get("result"))
    promoted = await record_claim_validation_outcome(
        experiment_id=str(experiment_id),
        result=result,
        note=note or f"Promoted from Part 6 market action {action_id}: {action.get('result_note') or ''}",
        event=str(match.get("suggested_record_event") or match.get("registered_event") or ""),
        actor_label=str(match.get("actor_label") or "") or None,
        amount=_positive_float(match.get("amount")),
        currency=_clean(match.get("currency"), 20) or None,
    )
    return {
        "engine_version": ENGINE_VERSION,
        "status": "PROMOTED_THROUGH_EXISTING_MARKET_GROUND_TRUTH_AUTHORITY",
        "action_id": action_id,
        "experiment_id": experiment_id,
        "promotion": promoted,
        "direct_part6_market_truth_writer": False,
        "truth_boundary": "PART6_NEVER_WRITES_RADAR_CLAIMS_DIRECTLY;_PROMOTION_USES_EXISTING_CLAIM_PREREGISTRATION_AND_MARKET_GROUND_TRUTH_QUALITY_LOCK",
    }


async def market_execution_dashboard(*, limit: int = 30) -> dict[str, Any]:
    from processors.signalforge_opportunity_decision_closure import build_opportunity_decision_portfolio_closure
    decisions = await build_opportunity_decision_portfolio_closure(limit=max(1, min(int(limit or 30), 100)))
    registry = market_action_registry_report()
    calibration = market_learning_calibration_report()
    candidates = []
    for row in decisions.get("items") or []:
        if row.get("founder_action") in {"ACTION_NOW", "VALIDATE_DISTRIBUTION", "NARROW_WEDGE", "INVESTIGATE"}:
            candidates.append({
                "thesis_id": row.get("thesis_id"),
                "title": row.get("title"),
                "market_track": row.get("market_track"),
                "founder_action": row.get("founder_action"),
                "decision_frontier": row.get("decision_frontier"),
                "hard_kill": row.get("hard_kill"),
            })
    return {
        "engine_version": ENGINE_VERSION,
        "status": "PASS",
        "candidates": candidates,
        "registry": registry,
        "claim_validation": claim_validation_report(),
        "learning_calibration": calibration,
        "market_calibration_state": "UNVALIDATED" if calibration.get("status") == "UNVALIDATED" else "PARTIAL_PROSPECTIVE_SIGNAL_CALIBRATION",
        "market_truth_writes_on_read": 0,
        "truth_boundary": TRUTH_BOUNDARY,
    }
