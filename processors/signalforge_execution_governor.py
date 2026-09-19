"""SignalForge R5 full-system execution governor.

This module is the single routing layer between *truth* and *work*.
It decides whether a current Radar/Brain object should receive:

- MACHINE_RESEARCH
- MARKET_ACTION
- FOUNDER_DISCOVERY
- WAIT_FOR_NEW_EVIDENCE
- PARK
- MONITOR

It has **zero truth authority**. It cannot change C01-C14, Brain structural
states, Founder addressability, or market calibration. Its job is to keep
expensive execution aligned with decision-critical uncertainty instead of
letting every historically interesting RadarCase remain active forever.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Mapping

ENGINE_VERSION = "signalforge-execution-governor-r8-strategic-routing-coherence"

MACHINE_GATES = {
    "PAIN_MATERIALITY",
    "BUYER_REALITY",
    "BUYER_REALITY_RECHECK",
    "CURRENT_SOLUTION",
    "CURRENT_SOLUTION_RECHECK",
    "UNRESOLVED_GAP",
    "UNRESOLVED_GAP_RECHECK",
    "COMPANY_REALITY",
    "DIFFERENTIATION",
    "OPPORTUNITY_WINDOW",
    "COMPETITION",
    "RECURRENCE",
    "ATOMIZE_PROBLEM",
    "EXACT_BUYER_AND_ECONOMIC_OWNER",
    "TRANSITION_ADOPTION_GAP",
    "ECONOMIC_NECESSITY",
    "SOLO_CAPTUREABILITY",
    "OPPORTUNITY_STRUCTURE",
}

MARKET_GATES = {"DISTRIBUTION", "ECONOMICS", "SWITCHING", "DECISION_READY"}
WAIT_STATUSES = {
    "SEARCH_EXHAUSTED",
    "SOURCE_SET_EXHAUSTED",
    "WAIT_FOR_NEW_SOURCE_COVERAGE",
    "WAIT_FOR_NEW_PROBLEM_CORPUS_OR_NEW_METHOD",
}
FINAL_STATES = {"SUPPORTED", "REFUTED"}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _upper(value: Any) -> str:
    return _text(value).upper()


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _candidate_id(row: Mapping[str, Any]) -> int:
    try:
        return int(row.get("candidate_id") or row.get("id") or 0)
    except Exception:
        return 0


def _case_id(row: Mapping[str, Any]) -> int:
    try:
        return int(row.get("case_id") or 0)
    except Exception:
        return 0


def _brain_maps(brain_advisory: Mapping[str, Any] | None) -> tuple[dict[int, dict[str, Any]], dict[int, dict[str, Any]]]:
    active: dict[int, dict[str, Any]] = {}
    deferred: dict[int, dict[str, Any]] = {}
    for item in list((brain_advisory or {}).get("items") or []):
        if not isinstance(item, Mapping):
            continue
        for raw in item.get("member_candidate_ids") or []:
            try:
                cid = int(raw)
            except Exception:
                continue
            existing = active.get(cid)
            if existing is None or float(item.get("voi", 0) or 0) > float(existing.get("voi", 0) or 0):
                active[cid] = dict(item)
    for item in list((brain_advisory or {}).get("deferred_items") or []):
        if not isinstance(item, Mapping):
            continue
        for raw in item.get("member_candidate_ids") or []:
            try:
                cid = int(raw)
            except Exception:
                continue
            deferred[cid] = dict(item)
    return active, deferred


def _brain_action_maps(brain_advisory: Mapping[str, Any] | None) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    raw = (brain_advisory or {}).get("candidate_actions") or {}
    if isinstance(raw, Mapping):
        for key, value in raw.items():
            try:
                cid = int(key)
            except Exception:
                continue
            if isinstance(value, Mapping):
                out[cid] = dict(value)
    return out


def _current_gate_status(row: Mapping[str, Any]) -> str:
    """Return the research-method status for the current gate when available."""
    gate = _upper(row.get("current_gate"))
    statuses = _mapping(row.get("research_status_by_claim"))
    claim = _upper(row.get("next_claim"))
    if claim and claim in statuses:
        return _upper(statuses.get(claim))
    if gate in {"BUYER_REALITY", "BUYER_REALITY_RECHECK"}:
        return _upper(statuses.get("C05"))
    if gate in {"CURRENT_SOLUTION", "CURRENT_SOLUTION_RECHECK"}:
        return _upper(statuses.get("C06"))
    if gate in {"UNRESOLVED_GAP", "UNRESOLVED_GAP_RECHECK"}:
        return _upper(statuses.get("C07"))
    if gate == "RECURRENCE":
        return _upper(statuses.get("C02") or row.get("c02_research_status"))
    return ""


def route_row(
    row: Mapping[str, Any],
    *,
    brain_advisory: Mapping[str, Any] | None = None,
    corpus_changed: bool = False,
) -> dict[str, Any]:
    """Route one row to exactly one execution lane.

    The router intentionally prefers *not doing machine work* when the current
    uncertainty cannot be reduced by the currently available machine method.
    """
    cid = _candidate_id(row)
    case_id = _case_id(row)
    gate = _upper(row.get("current_gate")) or "UNKNOWN"
    verdict = _upper(row.get("decision_verdict")) or "WATCH"
    boundary = _upper(row.get("market_validation_boundary"))
    admission = _mapping(row.get("production_admission"))
    admission_state = _upper(admission.get("state"))
    admission_route = _upper(admission.get("next_route"))
    claims = {str(k): _upper(v) for k, v in _mapping(row.get("claims")).items()}
    current_status = _current_gate_status(row)

    active_brain, deferred_brain = _brain_maps(brain_advisory)
    action_map = _brain_action_maps(brain_advisory)
    brain_item = active_brain.get(cid)
    brain_deferred = deferred_brain.get(cid)
    brain_action = action_map.get(cid) or {}
    brain_mode = _upper(brain_action.get("mode"))
    brain_action_name = _upper(brain_action.get("action"))
    brain_right_to_win = _upper(brain_action.get("right_to_win"))
    brain_hard_blocked = bool(brain_action.get("hard_blocked"))
    deferred_route = _upper((brain_deferred or {}).get("workload_route"))
    deferred_best = _mapping((brain_deferred or {}).get("best_next_action"))
    deferred_best_mode = _upper(deferred_best.get("mode"))

    reasons: list[str] = []
    route = "MONITOR"
    action = "OBSERVE_ONLY"
    decision_critical = False
    machine_eligible = False

    # Founder hard-block/right-to-win authority is work-routing only. It never
    # denies that the third-person market problem can be real. Explicit Brain
    # MARKET_ACTION / FOUNDER_DISCOVERY must outrank a generic deferred research
    # item; R7 treated every deferred item as PARK and could therefore suppress
    # exactly the human action Brain had recommended.
    effective_brain_mode = brain_mode or deferred_best_mode
    hard_block = (
        brain_hard_blocked
        or brain_right_to_win == "REFUTED"
        or brain_mode in {"HOLD", "STOP_OR_PARTNER"}
        or deferred_route == "FOUNDER_HARD_BLOCKED_MONITOR_ONLY"
        or deferred_best_mode in {"HOLD", "STOP_OR_PARTNER"}
        or (brain_deferred is not None and effective_brain_mode not in {"MARKET_ACTION", "FOUNDER_DISCOVERY"})
    )
    if hard_block:
        route = "PARK"
        action = brain_action_name or _upper(deferred_best.get("action")) or "STOP_OR_PARTNER"
        reasons.append("FOUNDER_HARD_BLOCK_OR_PARTNER_REQUIRED")
        if brain_right_to_win == "REFUTED":
            reasons.append("RIGHT_TO_WIN_REFUTED")
    elif effective_brain_mode == "MARKET_ACTION":
        route = "MARKET_ACTION"
        action = brain_action_name or _upper(deferred_best.get("action")) or "RUN_BOUNDED_MARKET_TEST"
        decision_critical = True
        reasons.append("BRAIN_MARKET_ACTION_HAS_HIGHER_VOI_THAN_MORE_DESK_RESEARCH")
    elif effective_brain_mode == "FOUNDER_DISCOVERY":
        route = "FOUNDER_DISCOVERY"
        action = brain_action_name or _upper(deferred_best.get("action")) or "FOUNDER_DISCOVERY"
        decision_critical = True
        reasons.append("FIRST_PERSON_GAP_REQUIRES_FOUNDER_OR_HUMAN_DISCOVERY")
    elif boundary == "FOUNDER_ACTION_NOW" or verdict == "VALIDATE":
        route = "MARKET_ACTION"
        action = "RUN_PREPARED_MARKET_VALIDATION"
        decision_critical = True
        reasons.append("RADAR_MARKET_VALIDATION_BOUNDARY_READY")
    elif current_status in WAIT_STATUSES and not corpus_changed:
        route = "WAIT_FOR_NEW_EVIDENCE"
        action = "WAIT_OR_CHANGE_EVIDENCE_METHOD"
        reasons.append(f"CURRENT_METHOD_{current_status or 'EXHAUSTED'}")
    elif admission_route in {"CHANGE_SOURCE_MARKET_ACTION_OR_PARK", "WAIT_FOR_NEW_SOURCE_COVERAGE"} and not corpus_changed:
        route = "WAIT_FOR_NEW_EVIDENCE" if admission_route == "WAIT_FOR_NEW_SOURCE_COVERAGE" else "PARK"
        action = "WAIT_FOR_NEW_SOURCE_COVERAGE" if route == "WAIT_FOR_NEW_EVIDENCE" else "CHANGE_SOURCE_MARKET_ACTION_OR_PARK"
        reasons.append(admission_route)
    elif gate in MARKET_GATES:
        # C10/C11/C14 are not allowed to become SUPPORT merely from desk
        # research. If not yet Founder-action-ready, keep them as prepared
        # market-action work rather than burning another machine cycle.
        route = "MARKET_ACTION" if boundary in {"FOUNDER_ACTION_NOW", "PREBUILT_WAITING_FOR_VALIDATE"} else "FOUNDER_DISCOVERY"
        action = "RUN_OR_PREPARE_MARKET_EXPERIMENT"
        decision_critical = True
        reasons.append("CURRENT_GATE_REQUIRES_MARKET_BEHAVIOR_OR_FOUNDER_EXECUTION")
    elif gate in MACHINE_GATES and admission_state in {"THESIS_ACTIVE", "RESEARCH_ACTIVE"}:
        route = "MACHINE_RESEARCH"
        action = _text(row.get("machine_action")) or _text((brain_item or {}).get("action")) or "CONTINUE_DECISION_CRITICAL_RESEARCH"
        decision_critical = True
        machine_eligible = True
        reasons.append("MACHINE_RESOLVABLE_DECISION_CRITICAL_GATE")
        if brain_item is not None:
            reasons.append("BRAIN_RESEARCH_QUEUE_MEMBER")
    elif admission_state == "DEFER_EPHEMERAL":
        route = "MONITOR"
        action = "WAIT_FOR_RECURRENCE_BUYER_OR_STRUCTURAL_SIGNAL"
        reasons.append("EPHEMERAL_OR_ONE_OFF_DEFERRED")
    elif admission_state == "MONITOR_CONTEXT":
        route = "MONITOR"
        action = "CHEAP_OBSERVATION_ONLY"
        reasons.append("NOT_WORTH_EXPENSIVE_RESEARCH_YET")
    elif brain_item is not None:
        # Brain may identify a high-VOI structural question for a case whose
        # legacy Radar admission did not happen to be active. The work can be
        # scheduled, but the Brain still cannot change any Radar truth state.
        route = "MACHINE_RESEARCH"
        action = _text(brain_item.get("action")) or "BRAIN_DECISION_CRITICAL_RESEARCH"
        decision_critical = True
        machine_eligible = True
        reasons.append("BRAIN_HIGH_VOI_RESEARCH_ADVISORY")
    else:
        route = "MONITOR"
        action = "OBSERVE_ONLY"
        reasons.append("NO_DECISION_CRITICAL_EXECUTION_ROUTE")

    # Never schedule machine work for a gate that is already resolved.
    next_claim = _upper(row.get("next_claim"))
    if machine_eligible and next_claim and claims.get(next_claim) in FINAL_STATES:
        machine_eligible = False
        route = "MONITOR"
        action = "CLAIM_ALREADY_RESOLVED"
        reasons.append("NEXT_CLAIM_ALREADY_FINAL")

    priority = {
        "MARKET_ACTION": 0,
        "FOUNDER_DISCOVERY": 1,
        "MACHINE_RESEARCH": 2,
        "WAIT_FOR_NEW_EVIDENCE": 5,
        "PARK": 7,
        "MONITOR": 8,
    }.get(route, 9)
    try:
        voi = float((brain_item or {}).get("voi", brain_action.get("voi", 0)) or 0)
    except Exception:
        voi = 0.0

    return {
        "engine_version": ENGINE_VERSION,
        "case_id": case_id,
        "candidate_id": cid,
        "route": route,
        "action": action,
        "priority_tier": priority,
        "decision_critical": bool(decision_critical),
        "machine_execution_eligible": bool(machine_eligible),
        "current_gate": gate,
        "current_gate_research_status": current_status or "NOT_RECORDED",
        "brain_voi": round(voi, 4),
        "brain_mode": effective_brain_mode or None,
        "brain_right_to_win": brain_right_to_win or None,
        "brain_hard_blocked": brain_hard_blocked,
        "reason_codes": list(dict.fromkeys(reasons)),
        "revisit_triggers": [
            "NEW_PROBLEM_CORPUS",
            "NEW_SOURCE_FAMILY",
            "MARKET_ACTION_OUTCOME",
            "FOUNDER_ADDRESSABILITY_CHANGE",
            "BRAIN_THESIS_REVISION",
        ] if route in {"WAIT_FOR_NEW_EVIDENCE", "PARK", "MONITOR"} else [],
        "truth_boundary": "EXECUTION_ROUTING_ONLY_NO_C01_C14_OR_BRAIN_OR_MARKET_TRUTH_AUTHORITY",
    }


def annotate_execution_routes(
    rows: Iterable[Mapping[str, Any]],
    *,
    brain_advisory: Mapping[str, Any] | None = None,
    corpus_changed: bool = False,
    machine_limit: int = 24,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    routed: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    machine: list[dict[str, Any]] = []
    for row in rows:
        copy = dict(row)
        decision = route_row(copy, brain_advisory=brain_advisory, corpus_changed=corpus_changed)
        copy["execution_route"] = decision
        routed.append(copy)
        counts[decision["route"]] += 1
        if decision["machine_execution_eligible"]:
            machine.append(copy)

    machine.sort(key=lambda r: (
        int(((r.get("execution_route") or {}).get("priority_tier", 9)) or 9),
        -float(((r.get("execution_route") or {}).get("brain_voi", 0)) or 0),
        {"VALIDATE": 0, "INVESTIGATE": 1, "WATCH": 2, "PARK": 3, "IGNORE": 4}.get(_upper(r.get("decision_verdict")), 9),
        -float(r.get("attention_score", 0) or 0),
        _case_id(r),
    ))
    bounded = machine[: max(0, int(machine_limit))]
    bounded_ids = [_case_id(x) for x in bounded if _case_id(x) > 0]
    bounded_id_set = set(bounded_ids)
    for row in routed:
        route = dict(row.get("execution_route") or {})
        eligible = bool(route.get("machine_execution_eligible"))
        selected = eligible and _case_id(row) in bounded_id_set
        route["machine_execution_selected"] = bool(selected)
        route["machine_execution_deferred_by_capacity"] = bool(eligible and not selected)
        if eligible and not selected:
            route["reason_codes"] = list(dict.fromkeys(list(route.get("reason_codes") or []) + ["BOUNDED_MACHINE_CAPACITY_DEFERRED"]))
        row["execution_route"] = route

    action_rows = [r for r in routed if _upper((r.get("execution_route") or {}).get("route")) in {"MARKET_ACTION", "FOUNDER_DISCOVERY"}]
    wait_rows = [r for r in routed if _upper((r.get("execution_route") or {}).get("route")) in {"WAIT_FOR_NEW_EVIDENCE", "PARK", "MONITOR"}]

    summary = {
        "engine_version": ENGINE_VERSION,
        "total_rows": len(routed),
        "route_counts": dict(counts),
        "machine_eligible_total": len(machine),
        "bounded_machine_workload": len(bounded),
        "bounded_machine_limit": max(0, int(machine_limit)),
        "bounded_machine_case_ids": bounded_ids,
        "machine_capacity_backlog": max(0, len(machine) - len(bounded)),
        "market_or_founder_actions": len(action_rows),
        "waiting_or_parked": len(wait_rows),
        "zero_machine_work_is_legal": True,
        "truth_boundary": "EXECUTION_GOVERNOR_IS_SCHEDULING_ONLY_NO_MARKET_TRUTH_AUTHORITY",
    }
    return routed, summary


def strategic_routing_coherence(
    rows: Iterable[Mapping[str, Any]],
    *,
    brain_advisory: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Check Brain candidate-action intent against actual execution routes.

    This is observability only. Candidate actions with no Radar row are reported
    as thesis-only/unmaterialized rather than fabricating a Candidate or RadarCase.
    """
    materialized = [dict(r) for r in rows]
    by_candidate: dict[int, list[dict[str, Any]]] = {}
    for row in materialized:
        cid = _candidate_id(row)
        if cid > 0:
            by_candidate.setdefault(cid, []).append(row)

    actions = _brain_action_maps(brain_advisory)
    checked = 0
    matched = 0
    mismatches: list[dict[str, Any]] = []
    thesis_only: list[dict[str, Any]] = []
    expected_counts: Counter[str] = Counter()

    for cid, action in sorted(actions.items()):
        mode = _upper(action.get("mode"))
        right = _upper(action.get("right_to_win"))
        hard = bool(action.get("hard_blocked")) or right == "REFUTED"
        expected = None
        if hard or mode in {"HOLD", "STOP_OR_PARTNER"}:
            expected = "PARK"
        elif mode == "MARKET_ACTION":
            expected = "MARKET_ACTION"
        elif mode == "FOUNDER_DISCOVERY":
            expected = "FOUNDER_DISCOVERY"
        if expected is None:
            continue
        expected_counts[expected] += 1
        candidate_rows = by_candidate.get(cid) or []
        if not candidate_rows:
            thesis_only.append({
                "candidate_id": cid,
                "thesis_id": action.get("thesis_id"),
                "expected_route": expected,
                "mode": mode or None,
                "reason": action.get("reason"),
            })
            continue
        checked += 1
        actual = sorted({_upper((r.get("execution_route") or {}).get("route")) for r in candidate_rows})
        if actual == [expected]:
            matched += 1
        else:
            mismatches.append({
                "candidate_id": cid,
                "thesis_id": action.get("thesis_id"),
                "expected_route": expected,
                "actual_routes": actual,
                "mode": mode or None,
                "right_to_win": right or None,
            })

    return {
        "status": "PASS" if not mismatches else "DEGRADED",
        "candidate_actions_total": len(actions),
        "actionable_candidate_actions": sum(expected_counts.values()),
        "radar_candidates_checked": checked,
        "matched": matched,
        "mismatch_count": len(mismatches),
        "mismatches": mismatches[:25],
        "thesis_only_or_no_radar_row": len(thesis_only),
        "thesis_only_items": thesis_only[:25],
        "expected_route_counts": dict(expected_counts),
        "truth_boundary": "STRATEGIC_ROUTING_COHERENCE_IS_OBSERVABILITY_ONLY_NO_C01_C14_OR_MARKET_TRUTH_AUTHORITY",
    }


def machine_rows(rows: Iterable[Mapping[str, Any]], *, limit: int = 24) -> list[dict[str, Any]]:
    materialized = [dict(r) for r in rows]
    has_selected_flag = any("machine_execution_selected" in (r.get("execution_route") or {}) for r in materialized)
    if has_selected_flag:
        xs = [r for r in materialized if bool(((r.get("execution_route") or {}).get("machine_execution_selected")))]
    else:
        xs = [r for r in materialized if bool(((r.get("execution_route") or {}).get("machine_execution_eligible")))]
    xs.sort(key=lambda r: (
        int(((r.get("execution_route") or {}).get("priority_tier", 9)) or 9),
        -float(((r.get("execution_route") or {}).get("brain_voi", 0)) or 0),
        -float(r.get("attention_score", 0) or 0),
        _case_id(r),
    ))
    return xs[: max(0, int(limit))]


def operating_queue(rows: Iterable[Mapping[str, Any]], *, limit: int = 100) -> dict[str, Any]:
    buckets: dict[str, list[dict[str, Any]]] = {
        "machine_research": [],
        "machine_research_backlog": [],
        "market_action": [],
        "founder_discovery": [],
        "waiting": [],
        "parked": [],
        "monitor": [],
    }
    map_key = {
        "MARKET_ACTION": "market_action",
        "FOUNDER_DISCOVERY": "founder_discovery",
        "WAIT_FOR_NEW_EVIDENCE": "waiting",
        "PARK": "parked",
        "MONITOR": "monitor",
    }
    for row in rows:
        route = _mapping(row.get("execution_route"))
        route_name = _upper(route.get("route"))
        if route_name == "MACHINE_RESEARCH":
            key = "machine_research" if bool(route.get("machine_execution_selected")) else "machine_research_backlog"
        else:
            key = map_key.get(route_name, "monitor")
        buckets[key].append({
            "case_id": row.get("case_id"),
            "candidate_id": row.get("candidate_id"),
            "title": row.get("title"),
            "decision_verdict": row.get("decision_verdict"),
            "current_gate": row.get("current_gate"),
            "route": route.get("route"),
            "action": route.get("action"),
            "brain_voi": route.get("brain_voi"),
            "machine_execution_selected": bool(route.get("machine_execution_selected")),
            "machine_execution_deferred_by_capacity": bool(route.get("machine_execution_deferred_by_capacity")),
            "reason_codes": route.get("reason_codes") or [],
            "revisit_triggers": route.get("revisit_triggers") or [],
        })
    total_counts = {k: len(v) for k, v in buckets.items()}
    displayed = {k: v[: max(0, int(limit))] for k, v in buckets.items()}
    total_counts["machine_research_eligible_total"] = total_counts.get("machine_research", 0) + total_counts.get("machine_research_backlog", 0)
    return {
        "engine_version": ENGINE_VERSION,
        "counts": total_counts,
        "displayed_counts": {k: len(v) for k, v in displayed.items()},
        **displayed,
        "semantics": {
            "machine_research": "SELECTED_FOR_THIS_BOUNDED_EXECUTION_WINDOW",
            "machine_research_backlog": "ELIGIBLE_BUT_DEFERRED_BY_BOUNDED_CAPACITY",
            "machine_research_eligible_total": "SELECTED_PLUS_CAPACITY_BACKLOG",
        },
        "truth_boundary": "FOUNDER_OPERATING_QUEUE_IS_EXECUTION_ROUTING_NOT_MARKET_TRUTH",
    }


def static_acceptance() -> dict[str, bool]:
    base = {
        "case_id": 1,
        "candidate_id": 10,
        "decision_verdict": "WATCH",
        "current_gate": "BUYER_REALITY",
        "next_claim": "C05",
        "claims": {"C03": "SUPPORTED", "C05": "UNKNOWN"},
        "production_admission": {"state": "RESEARCH_ACTIVE", "next_route": "DECISION_CRITICAL_RESEARCH"},
        "research_status_by_claim": {"C05": "ACTIVE"},
        "attention_score": 70,
    }
    machine = route_row(base)
    exhausted = route_row({**base, "research_status_by_claim": {"C05": "SOURCE_SET_EXHAUSTED"}})
    market = route_row({**base, "market_validation_boundary": "FOUNDER_ACTION_NOW", "decision_verdict": "VALIDATE"})
    founder = route_row(base, brain_advisory={"candidate_actions": {"10": {"mode": "FOUNDER_DISCOVERY", "action": "DOMAIN_EXPERT_OR_PRACTITIONER_INTERVIEW"}}})
    hard = route_row(base, brain_advisory={"deferred_items": [{"member_candidate_ids": [10], "voi": 0.9}]})
    rows, summary = annotate_execution_routes([base, {**base, "case_id": 2, "candidate_id": 11}], machine_limit=1)
    queue = operating_queue([{**base, "execution_route": {"route": "MONITOR"}}, {**base, "case_id": 2, "execution_route": {"route": "MONITOR"}}], limit=1)
    return {
        "machine_gate_routes_to_machine_research": machine["route"] == "MACHINE_RESEARCH" and machine["machine_execution_eligible"],
        "exhausted_method_does_not_repeat_without_new_corpus": exhausted["route"] == "WAIT_FOR_NEW_EVIDENCE" and not exhausted["machine_execution_eligible"],
        "market_validation_outranks_machine_research": market["route"] == "MARKET_ACTION" and not market["machine_execution_eligible"],
        "founder_discovery_is_not_machine_research": founder["route"] == "FOUNDER_DISCOVERY" and not founder["machine_execution_eligible"],
        "founder_hard_block_parks_work_only": hard["route"] == "PARK" and "NO_C01_C14" in hard["truth_boundary"],
        "machine_execution_is_hard_bounded": summary["bounded_machine_workload"] == 1 and len(machine_rows(rows, limit=1)) == 1,
        "zero_machine_work_is_legal": bool(summary["zero_machine_work_is_legal"]),
        "operating_queue_counts_are_not_truncated_to_display_limit": queue["counts"]["monitor"] == 2 and queue["displayed_counts"]["monitor"] == 1,
    }
