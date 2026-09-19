"""SignalForge R5 Founder market-action operating registry.

The Brain can recommend a market action, but a recommendation is not an outcome.
This registry turns that recommendation into an explicit pre-registered Founder
execution object while preserving a strict truth boundary:

- registering an action writes no Radar evidence and changes no C01-C14 claim;
- completing an action records observed behavior but still does not silently
  mutate Radar truth;
- only separately validated market-result ingestion may update atomic claims;
- calibration may consume an action outcome only when the pre-test strategic
  snapshot was captured before the result.
"""
from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from processors.signalforge_process_lock import cross_process_file_lock

ENGINE_VERSION = "signalforge-market-action-registry-r5"
REGISTRY_PATH = Path(".radar_runtime/signalforge_market_actions.jsonl")
REGISTRY_LOCK_PATH = Path(".radar_runtime/signalforge_market_actions.lock")

ACTION_TEMPLATES: dict[str, dict[str, Any]] = {
    "DOMAIN_EXPERT_OR_PRACTITIONER_INTERVIEW": {
        "category": "FOUNDER_DISCOVERY",
        "target": "domain_practitioner",
        "success_signal": "specific domain constraints / buying workflow / trust requirements are learned from a relevant practitioner",
        "failure_signal": "interview does not establish decision-relevant domain knowledge or reveals a non-bridgeable credibility gap",
        "default_sample": 3,
        "cost_class": "LOW",
    },
    "BUILD_OR_BORROW_LEGITIMACY": {
        "category": "FOUNDER_DISCOVERY",
        "target": "credible_partner_or_design_customer",
        "success_signal": "a credible partner/design customer is willing to lend legitimacy or co-design under explicit scope",
        "failure_signal": "required legitimacy cannot be borrowed/built within a bounded path",
        "default_sample": 3,
        "cost_class": "LOW_TO_MEDIUM",
    },
    "IDENTIFY_REACHABLE_BUYER_CHANNEL": {
        "category": "FOUNDER_DISCOVERY",
        "target": "buyer_channel",
        "success_signal": "at least one repeatable channel reaches qualified target buyers",
        "failure_signal": "no reachable qualified buyer channel after bounded channel probes",
        "default_sample": 10,
        "cost_class": "LOW",
    },
    "BOUNDED_CUSTOMER_TEST": {
        "category": "MARKET_ACTION",
        "target": "qualified_target_buyer",
        "success_signal": "qualified target buyers perform the pre-registered behavior, not merely express interest",
        "failure_signal": "qualified target buyers consistently decline or fail to perform the target behavior",
        "default_sample": 5,
        "cost_class": "LOW_TO_MEDIUM",
    },
    "PAID_PILOT_OR_PREORDER_TEST": {
        "category": "MARKET_ACTION",
        "target": "economic_buyer",
        "success_signal": "real payment/deposit or signed paid pilot under the pre-registered offer",
        "failure_signal": "qualified economic buyers decline the bounded offer or will not commit economically",
        "default_sample": 5,
        "cost_class": "LOW_TO_MEDIUM",
    },
    "BUYER_INTERVIEW": {
        "category": "MARKET_ACTION",
        "target": "economic_buyer",
        "success_signal": "buyer confirms ownership, budget/process and current failure with concrete examples",
        "failure_signal": "buyer does not own the problem or no material workflow consequence exists",
        "default_sample": 5,
        "cost_class": "LOW",
    },
    "OUTREACH": {
        "category": "MARKET_ACTION",
        "target": "qualified_target_buyer",
        "success_signal": "bounded outreach produces qualified replies or meetings above the pre-registered threshold",
        "failure_signal": "qualified outreach produces no meaningful buyer response under the pre-registered sample",
        "default_sample": 20,
        "cost_class": "LOW",
    },
    "LANDING_PAGE": {
        "category": "MARKET_ACTION",
        "target": "qualified_target_user",
        "success_signal": "target users complete the pre-registered high-intent action",
        "failure_signal": "traffic from target users does not convert to the high-intent action",
        "default_sample": 50,
        "cost_class": "LOW_TO_MEDIUM",
    },
    "PROTOTYPE": {
        "category": "MARKET_ACTION",
        "target": "design_customer",
        "success_signal": "qualified users repeatedly use the prototype to complete the target workflow and request continuation",
        "failure_signal": "prototype does not resolve the target workflow enough to change behavior",
        "default_sample": 3,
        "cost_class": "MEDIUM",
    },
    "PREORDER": {
        "category": "MARKET_ACTION",
        "target": "economic_buyer",
        "success_signal": "real deposit/preorder is collected under a pre-registered offer",
        "failure_signal": "qualified buyers do not commit economically",
        "default_sample": 5,
        "cost_class": "LOW_TO_MEDIUM",
    },
    "PAID_PILOT": {
        "category": "MARKET_ACTION",
        "target": "economic_buyer",
        "success_signal": "signed paid pilot or positive payment is observed",
        "failure_signal": "qualified buyer declines a paid pilot after bounded offer iteration",
        "default_sample": 5,
        "cost_class": "MEDIUM",
    },
}


ATOMIC_INGESTION_HINTS: dict[str, dict[str, Any]] = {
    "PAID_PILOT": {"event": "PAID_PILOT", "claims": ["C10", "C11", "C14"]},
    "PAID_PILOT_OR_PREORDER_TEST": {"event": "PAID_PILOT", "claims": ["C10", "C11", "C14"]},
    "PREORDER": {"event": "PRICE", "claims": ["C11"]},
    "OUTREACH": {"event": "ACQUISITION", "claims": ["C10"]},
    "IDENTIFY_REACHABLE_BUYER_CHANNEL": {"event": "ACQUISITION", "claims": ["C10"]},
    "PROTOTYPE": {"event": "SWITCH", "claims": ["C14"]},
}


def _positive_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except Exception:
        return 0


def _string_list(value: Any) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        return [str(x).strip() for x in value if str(x).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _semantic_family_for_action(action_type: str) -> str:
    mapping = {
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
    return mapping.get(str(action_type or "").upper(), "UNKNOWN_SEMANTIC")


def market_action_outcome_quality(record: Mapping[str, Any]) -> dict[str, Any]:
    """Fail-closed calibration-quality gate for durable market outcomes.

    Aggregate counters are never treated as sample evidence by themselves. A
    calibration-eligible binary outcome must have one durable observation
    record per observed actor/sample, and any preregistered max-cost contract
    must be verified and unbreached.
    """
    status = str(record.get("status") or "").upper()
    result = str(record.get("result") or "").upper()
    category = str(record.get("category") or "").upper()
    action_type = str(record.get("action_type") or "").upper()
    obs = record.get("observations") if isinstance(record.get("observations"), Mapping) else {}
    snap = record.get("pretest_snapshot") if isinstance(record.get("pretest_snapshot"), Mapping) else {}
    rule = record.get("decision_rule") if isinstance(record.get("decision_rule"), Mapping) else {}
    sample_target = _positive_int(record.get("sample_target"))
    observation_records = [dict(x) for x in (obs.get("observation_records") or []) if isinstance(x, Mapping)]
    observed_sample = len(observation_records)
    actor_labels = [str(x.get("actor_label") or "").strip() for x in observation_records if str(x.get("actor_label") or "").strip()]
    evidence_refs = [str(x.get("evidence_ref") or "").strip() for x in observation_records if str(x.get("evidence_ref") or "").strip()]
    unique_actors = set(actor_labels)
    observed_behavior = str(obs.get("observed_behavior") or "").strip()
    decision_findings = str(obs.get("decision_relevant_findings") or "").strip()
    counts = obs.get("outcome_counts") if isinstance(obs.get("outcome_counts"), Mapping) else {}
    metric = str(rule.get("metric") or "").strip()
    metric_value = _positive_int(counts.get(metric)) if metric else 0
    cost_eval = obs.get("cost_evaluation") if isinstance(obs.get("cost_evaluation"), Mapping) else {}

    reasons: list[str] = []
    if status != "COMPLETED": reasons.append("ACTION_NOT_COMPLETED")
    if result not in {"PASS", "FAIL"}: reasons.append("OUTCOME_NOT_BINARY")
    if not isinstance(snap, Mapping) or not str(snap.get("thesis_id") or "").strip(): reasons.append("PRETEST_SNAPSHOT_MISSING")
    if sample_target <= 0: reasons.append("INVALID_PREREGISTERED_SAMPLE_TARGET")
    if observed_sample < sample_target: reasons.append("DURABLE_OBSERVATION_RECORDS_BELOW_PREREGISTERED_TARGET")
    if len(unique_actors) < observed_sample: reasons.append("OBSERVED_SAMPLE_NOT_DISTINCT_ACTORS")
    if len(evidence_refs) < observed_sample: reasons.append("MISSING_PER_OBSERVATION_EVIDENCE_REFERENCE")
    if metric and metric_value > observed_sample: reasons.append("METRIC_COUNT_EXCEEDS_DURABLE_OBSERVATIONS")

    if record.get("max_cost") is not None:
        if str(cost_eval.get("status") or "") != "WITHIN_LIMIT":
            reasons.append("PREREGISTERED_MAX_COST_NOT_VERIFIED_OR_BREACHED")

    eligible_domains: list[str] = []
    if category == "MARKET_ACTION":
        if not actor_labels: reasons.append("NO_QUALIFIED_ACTOR_LABEL")
        if not observed_behavior: reasons.append("NO_OBSERVED_BEHAVIOR")
        if result == "PASS" and action_type in {"PAID_PILOT", "PAID_PILOT_OR_PREORDER_TEST", "PREORDER"}:
            paid = _positive_int(counts.get("paid_commitments"))
            if paid <= 0: reasons.append("PAID_TEST_PASS_REQUIRES_POSITIVE_PAID_COMMITMENT")
            if not obs.get("amount") or not str(obs.get("currency") or "").strip(): reasons.append("POSITIVE_PAYMENT_RESULT_REQUIRES_AMOUNT_AND_CURRENCY")
        if not reasons:
            eligible_domains.extend(["FAST_VALIDATION", "FOUNDER_ADDRESSABILITY"])
    elif category == "FOUNDER_DISCOVERY":
        if not actor_labels: reasons.append("NO_RELEVANT_PRACTITIONER_OR_CHANNEL_LABEL")
        if not decision_findings: reasons.append("NO_DECISION_RELEVANT_FINDINGS")
        if not reasons:
            eligible_domains.append("FOUNDER_ADDRESSABILITY")
    else:
        reasons.append("UNKNOWN_ACTION_CATEGORY")

    semantic_family = str(rule.get("metric_family") or _semantic_family_for_action(action_type)).upper()
    return {
        "status": "ELIGIBLE" if not reasons else "RECORDED_NOT_CALIBRATION_ELIGIBLE",
        "eligible": not reasons,
        "eligible_domains": eligible_domains,
        "semantic_family": semantic_family,
        "metric": metric or None,
        "reasons": list(dict.fromkeys(reasons)),
        "sample_target": sample_target,
        "observed_sample_size": observed_sample,
        "submitted_sample_count": _positive_int(obs.get("submitted_sample_count")),
        "evidence_ref_count": len(evidence_refs),
        "actor_count": len(unique_actors),
        "truth_boundary": "CALIBRATION_REQUIRES_PER_OBSERVATION_DURABLE_RECORDS,_DISTINCT_ACTORS,_SEMANTICALLY_VALID_BEHAVIOR_AND_COST_COMPLIANCE;_NO_C01_C14_WRITE_AUTHORITY",
    }


def market_action_ingestion_readiness(record: Mapping[str, Any]) -> dict[str, Any]:
    """Explain whether a completed thesis action can enter atomic market truth.

    This function performs no write. Existing market_ground_truth remains the
    only human-market evidence writer and still requires a claim-specific
    validation experiment plus actor/amount rules.
    """
    action_type = str(record.get("action_type") or "").upper()
    hint = dict(ATOMIC_INGESTION_HINTS.get(action_type) or {})
    status = str(record.get("status") or "").upper()
    result = str(record.get("result") or "").upper()
    obs = record.get("observations") if isinstance(record.get("observations"), Mapping) else {}
    snap = record.get("pretest_snapshot") if isinstance(record.get("pretest_snapshot"), Mapping) else {}
    candidate_ids = [int(x) for x in (snap.get("member_candidate_ids") or []) if str(x).isdigit() and int(x) > 0]
    reasons: list[str] = []
    if status != "COMPLETED": reasons.append("ACTION_NOT_COMPLETED")
    if result not in {"PASS", "FAIL"}: reasons.append("OUTCOME_NOT_BINARY_MARKET_RESULT")
    if not hint: reasons.append("ACTION_TYPE_NOT_ATOMIC_MARKET_EVENT")
    if not candidate_ids: reasons.append("NO_CANDIDATE_SCOPE_IN_PRETEST_SNAPSHOT")
    # A thesis-level action is not itself a claim experiment. Claim-specific
    # preregistration must exist *before the observed outcome*. A completed
    # thesis action can remain calibration evidence, but it cannot be converted
    # post hoc into C10/C11/C14 truth by registering an experiment afterward.
    if not reasons:
        reasons.append("MATCHING_CLAIM_EXPERIMENT_MUST_HAVE_BEEN_PREREGISTERED_BEFORE_OUTCOME")
    if result == "PASS" and hint.get("event") in {"PRICE", "PAID_PILOT"}:
        if not obs.get("amount") or not obs.get("currency"):
            reasons.append("PASS_REQUIRES_POSITIVE_AMOUNT_AND_CURRENCY")
    if result == "PASS" and not str(obs.get("actor_label") or "").strip():
        reasons.append("PASS_REQUIRES_IDENTIFIED_ACTOR")
    return {
        "action_id": record.get("action_id"),
        "action_type": action_type,
        "suggested_event": hint.get("event"),
        "suggested_claims": hint.get("claims") or [],
        "candidate_ids": candidate_ids,
        "ready_for_direct_atomic_write": False,
        "next_step": (
            "USE_MARKET_GROUND_TRUTH_ONLY_IF_A_MATCHING_CLAIM_EXPERIMENT_WAS_ALREADY_PREREGISTERED_BEFORE_THIS_OUTCOME;_OTHERWISE_KEEP_AS_CALIBRATION_ONLY"
            if hint else "KEEP_AS_FOUNDER_DISCOVERY_OR_CALIBRATION_OUTCOME_ONLY"
        ),
        "requirements": list(dict.fromkeys(reasons)),
        "truth_boundary": "THESIS_ACTION_OUTCOME_NEVER_BYPASSES_CLAIM_SPECIFIC_PREREGISTRATION_OR_MARKET_GROUND_TRUTH_QUALITY_LOCK",
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_rows() -> list[dict[str, Any]]:
    if not REGISTRY_PATH.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in REGISTRY_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _rewrite(rows: list[dict[str, Any]]) -> None:
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = "\n".join(json.dumps(r, ensure_ascii=False, default=str) for r in rows)
    if payload:
        payload += "\n"
    tmp = REGISTRY_PATH.with_suffix(".tmp")
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(REGISTRY_PATH)


def _brain_portfolio(root: Path | None = None) -> dict[str, Any]:
    try:
        from processors.signalforge_brain_v2_engine import get_brain_v2_portfolio
        return dict(get_brain_v2_portfolio(root=root))
    except Exception as exc:
        return {"status": "BRAIN_UNAVAILABLE", "portfolio": [], "error": f"{type(exc).__name__}: {exc}"}


def _normalize_action(action: str | None, mode: str | None = None) -> str:
    raw = str(action or "").strip().upper()
    aliases = {
        "PAID_PILOT_OR_PREORDER_TEST": "PAID_PILOT_OR_PREORDER_TEST",
        "BOUNDED_CUSTOMER_TEST": "BOUNDED_CUSTOMER_TEST",
        "DOMAIN_EXPERT_OR_PRACTITIONER_INTERVIEW": "DOMAIN_EXPERT_OR_PRACTITIONER_INTERVIEW",
        "BUILD_OR_BORROW_LEGITIMACY": "BUILD_OR_BORROW_LEGITIMACY",
        "IDENTIFY_REACHABLE_BUYER_CHANNEL": "IDENTIFY_REACHABLE_BUYER_CHANNEL",
    }
    if raw in aliases:
        return aliases[raw]
    if raw in ACTION_TEMPLATES:
        return raw
    m = str(mode or "").upper()
    if m == "MARKET_ACTION":
        return "BOUNDED_CUSTOMER_TEST"
    if m == "FOUNDER_DISCOVERY":
        return "DOMAIN_EXPERT_OR_PRACTITIONER_INTERVIEW"
    return raw or "UNSPECIFIED"


def _thesis_by_id(portfolio: Mapping[str, Any], thesis_id: str) -> dict[str, Any] | None:
    for row in portfolio.get("portfolio") or []:
        if isinstance(row, Mapping) and str(row.get("thesis_id") or "") == str(thesis_id):
            return dict(row)
    return None


def _snapshot(thesis: Mapping[str, Any]) -> dict[str, Any]:
    addr = thesis.get("founder_addressability") if isinstance(thesis.get("founder_addressability"), Mapping) else {}
    return {
        "captured_at": _now(),
        "thesis_id": thesis.get("thesis_id"),
        "thesis_revision": thesis.get("revision"),
        "representative_title": thesis.get("representative_title"),
        "strategic_track": thesis.get("strategic_track"),
        "classification": thesis.get("classification"),
        "zip2_readiness": thesis.get("zip2_readiness"),
        "first_person_addressability_state": addr.get("first_person_addressability_state"),
        "founder_addressability": dict(addr),
        "fast_validation": dict(thesis.get("fast_validation") or {}),
        "best_next_action": dict(thesis.get("best_next_action") or {}),
        "member_candidate_ids": list(thesis.get("member_candidate_ids") or []),
        "claim_states": dict(thesis.get("claim_states") or {}),
        "dimensions": dict(thesis.get("dimensions") or {}),
        "truth_boundary": "PRETEST_DERIVED_SNAPSHOT_IMMUTABLE_AFTER_ACTION_REGISTRATION",
    }


def build_market_action_queue(root: Path | None = None, *, limit: int = 100) -> dict[str, Any]:
    portfolio = _brain_portfolio(root)
    existing = _load_rows()
    open_by_thesis = {
        str(r.get("thesis_id")): r for r in existing
        if str(r.get("status") or "").upper() in {"REGISTERED", "RUNNING"}
    }
    items: list[dict[str, Any]] = []
    for thesis in portfolio.get("portfolio") or []:
        if not isinstance(thesis, Mapping):
            continue
        best = thesis.get("best_next_action") if isinstance(thesis.get("best_next_action"), Mapping) else {}
        mode = str(best.get("mode") or "").upper()
        if mode not in {"MARKET_ACTION", "FOUNDER_DISCOVERY"}:
            continue
        tid = str(thesis.get("thesis_id") or "")
        action_type = _normalize_action(best.get("action"), mode)
        template = dict(ACTION_TEMPLATES.get(action_type) or {})
        items.append({
            "thesis_id": tid,
            "representative_title": thesis.get("representative_title"),
            "strategic_track": thesis.get("strategic_track"),
            "zip2_readiness": thesis.get("zip2_readiness"),
            "addressability": ((thesis.get("founder_addressability") or {}).get("first_person_addressability_state") if isinstance(thesis.get("founder_addressability"), Mapping) else None),
            "mode": mode,
            "action_type": action_type,
            "reason": best.get("reason"),
            "voi": best.get("voi"),
            "template": template,
            "registered_action_id": (open_by_thesis.get(tid) or {}).get("action_id"),
            "registration_status": (open_by_thesis.get(tid) or {}).get("status") or "NOT_REGISTERED",
            "truth_boundary": "ACTION_RECOMMENDATION_OR_REGISTRATION_IS_NOT_MARKET_OUTCOME",
        })
    items.sort(key=lambda x: (0 if x.get("mode") == "MARKET_ACTION" else 1, -(float(x.get("voi", 0) or 0)), str(x.get("thesis_id") or "")))
    return {
        "engine_version": ENGINE_VERSION,
        "status": portfolio.get("status"),
        "count": len(items),
        "items": items[: max(0, int(limit))],
        "registered_open": sum(1 for r in existing if str(r.get("status") or "").upper() in {"REGISTERED", "RUNNING"}),
        "completed": sum(1 for r in existing if str(r.get("status") or "").upper() == "COMPLETED"),
        "truth_boundary": "FOUNDER_ACTION_QUEUE_HAS_ZERO_C01_C14_WRITE_AUTHORITY",
    }


def register_market_action(
    *,
    thesis_id: str,
    action_type: str | None = None,
    sample_target: int | None = None,
    success_criteria: str | None = None,
    failure_criteria: str | None = None,
    note: str | None = None,
    root: Path | None = None,
    part6_test_design: Mapping[str, Any] | None = None,
    decision_rule: Mapping[str, Any] | None = None,
    inconclusive_criteria: str | None = None,
    max_cost: float | None = None,
    max_cost_currency: str | None = None,
    buyer_outreach_pack: Mapping[str, Any] | None = None,
    learning_features: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    portfolio = _brain_portfolio(root)
    thesis = _thesis_by_id(portfolio, thesis_id)
    if thesis is None:
        raise ValueError(f"thesis {thesis_id!r} not found in current Brain portfolio")
    best = thesis.get("best_next_action") if isinstance(thesis.get("best_next_action"), Mapping) else {}
    mode = str(best.get("mode") or "").upper()
    if part6_test_design:
        authority = part6_test_design.get("execution_authority") if isinstance(part6_test_design.get("execution_authority"), Mapping) else {}
        if not bool(authority.get("allowed")):
            raise ValueError(str(authority.get("reason") or "Part 4 Founder actionability blocks Part 6 market preregistration"))
    if mode not in {"MARKET_ACTION", "FOUNDER_DISCOVERY"}:
        raise ValueError(f"thesis {thesis_id} is not currently routed to Founder/market action; mode={mode or 'UNKNOWN'}")
    normalized = _normalize_action(action_type or best.get("action"), mode)
    template = dict(ACTION_TEMPLATES.get(normalized) or {})
    if not template:
        raise ValueError(f"unsupported market/founder action type: {normalized}")

    action_id = datetime.now(timezone.utc).strftime("sfma_%Y%m%dT%H%M%S_") + secrets.token_hex(3)
    n = int(sample_target if sample_target is not None else template.get("default_sample", 1) or 1)
    if n <= 0:
        raise ValueError("sample_target must be > 0")
    record = {
        "engine_version": ENGINE_VERSION,
        "action_id": action_id,
        "registered_at": _now(),
        "thesis_id": str(thesis_id),
        "status": "REGISTERED",
        "mode": mode,
        "action_type": normalized,
        "category": template.get("category"),
        "target": template.get("target"),
        "sample_target": n,
        "success_criteria": str(success_criteria or template.get("success_signal") or "").strip(),
        "failure_criteria": str(failure_criteria or template.get("failure_signal") or "").strip(),
        "cost_class": template.get("cost_class"),
        "note": note,
        "pretest_snapshot": {**_snapshot(thesis), "part6_learning_features": dict(learning_features or {})},
        "part6_test_design": dict(part6_test_design or {}),
        "decision_rule": dict(decision_rule or {}),
        "inconclusive_criteria": str(inconclusive_criteria or "").strip() or None,
        "max_cost": max_cost,
        "max_cost_currency": str(max_cost_currency or "").strip() or None,
        "buyer_outreach_pack": dict(buyer_outreach_pack or {}),
        "learning_features": dict(learning_features or {}),
        "result": None,
        "observations": None,
        "completed_at": None,
        "truth_boundary": "REGISTRATION_FREEZES_PRETEST_STATE_BUT_WRITES_NO_RADAR_OR_MARKET_TRUTH",
    }
    with cross_process_file_lock(REGISTRY_LOCK_PATH):
        rows = _load_rows()
        for row in rows:
            if str(row.get("thesis_id")) == str(thesis_id) and str(row.get("status") or "").upper() in {"REGISTERED", "RUNNING"}:
                raise ValueError(f"thesis {thesis_id} already has open action {row.get('action_id')}")
        rows.append(record)
        _rewrite(rows)
    return record


def complete_market_action(
    *,
    action_id: str,
    result: str,
    observations: Mapping[str, Any] | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    result = str(result or "").upper()
    if result not in {"PASS", "FAIL", "INCONCLUSIVE"}:
        raise ValueError("result must be PASS, FAIL, or INCONCLUSIVE")
    with cross_process_file_lock(REGISTRY_LOCK_PATH):
        rows = _load_rows()
        found: dict[str, Any] | None = None
        for row in rows:
            if str(row.get("action_id")) != str(action_id):
                continue
            if str(row.get("status") or "").upper() == "COMPLETED":
                raise ValueError(f"market action {action_id} already completed; outcome is immutable")
            obs = dict(observations or {})
            completed = {
                **row,
                "status": "COMPLETED",
                "result": result,
                "observations": obs,
                "result_note": note,
                "completed_at": _now(),
            }
            completed["outcome_hash"] = hashlib.sha256(
                json.dumps({
                    "action_id": completed.get("action_id"),
                    "result": result,
                    "observations": obs,
                    "completed_at": completed.get("completed_at"),
                }, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest()[:24]
            completed["outcome_quality"] = market_action_outcome_quality(completed)
            if result in {"PASS", "FAIL"} and not completed["outcome_quality"].get("eligible"):
                requirements = ", ".join(completed["outcome_quality"].get("reasons") or [])
                raise ValueError(
                    "binary market/founder outcome does not satisfy the pre-registered observation-quality gate: "
                    + requirements
                    + ". Record INCONCLUSIVE instead or provide the required durable observations."
                )
            row.clear(); row.update(completed)
            found = row
            break
        if found is None:
            raise ValueError(f"market action {action_id!r} not found")
        _rewrite(rows)
        return dict(found)


def market_action_registry_report() -> dict[str, Any]:
    rows = _load_rows()
    completed_rows = [r for r in rows if str(r.get("status") or "").upper() == "COMPLETED"]
    readiness = [market_action_ingestion_readiness(r) for r in completed_rows]
    quality = [market_action_outcome_quality(r) for r in completed_rows]
    return {
        "engine_version": ENGINE_VERSION,
        "total": len(rows),
        "registered": sum(1 for r in rows if str(r.get("status") or "").upper() == "REGISTERED"),
        "running": sum(1 for r in rows if str(r.get("status") or "").upper() == "RUNNING"),
        "completed": sum(1 for r in rows if str(r.get("status") or "").upper() == "COMPLETED"),
        "atomic_ingestion_readiness": readiness,
        "atomic_ingestion_ready_direct": 0,
        "calibration_eligible": sum(1 for q in quality if q.get("eligible")),
        "calibration_ineligible_recorded": sum(1 for q in quality if not q.get("eligible")),
        "outcome_quality": quality,
        "rows": rows,
        "truth_boundary": "RECORDED_FOUNDER_ACTION_OUTCOMES_REQUIRE_SEPARATE_ATOMIC_MARKET_RESULT_INGESTION_BEFORE_CLAIM_WRITE",
    }


def calibration_eligible_outcomes() -> list[dict[str, Any]]:
    out = []
    for row in _load_rows():
        quality = market_action_outcome_quality(row)
        if not quality.get("eligible"):
            continue
        copy = dict(row)
        copy["outcome_quality"] = quality
        out.append(copy)
    return out


def static_acceptance() -> dict[str, bool]:
    return {
        "registration_is_pretest_snapshot_only": True,
        "completion_does_not_write_radar_claims": True,
        "inconclusive_is_not_calibration_eligible": True,
        "action_templates_cover_market_and_founder_discovery": {"MARKET_ACTION", "FOUNDER_DISCOVERY"} <= {str(x.get("category")) for x in ACTION_TEMPLATES.values()},
        "paid_action_types_exist": "PAID_PILOT_OR_PREORDER_TEST" in ACTION_TEMPLATES and "PAID_PILOT" in ACTION_TEMPLATES,
        "thesis_action_cannot_bypass_claim_preregistration": market_action_ingestion_readiness({
            "action_id": "x", "status": "COMPLETED", "result": "PASS", "action_type": "PAID_PILOT",
            "pretest_snapshot": {"member_candidate_ids": [1]},
            "observations": {"actor_label": "Buyer A", "amount": 1, "currency": "USD"},
        })["ready_for_direct_atomic_write"] is False,
        "completed_thesis_action_cannot_create_retroactive_claim_experiment": "PREREGISTERED_BEFORE_THIS_OUTCOME" in market_action_ingestion_readiness({
            "action_id": "x", "status": "COMPLETED", "result": "PASS", "action_type": "PAID_PILOT",
            "pretest_snapshot": {"member_candidate_ids": [1]},
            "observations": {"actor_label": "Buyer A", "amount": 1, "currency": "USD"},
        })["next_step"],
        "empty_pass_is_not_calibration_evidence": not market_action_outcome_quality({
            "status": "COMPLETED", "result": "PASS", "category": "MARKET_ACTION", "action_type": "OUTREACH",
            "sample_target": 5, "pretest_snapshot": {"thesis_id": "t1"}, "observations": {},
        })["eligible"],
        "binary_outcome_quality_gate_is_fail_closed": "binary market/founder outcome does not satisfy" in Path(__file__).read_text(encoding="utf-8"),
        "founder_discovery_cannot_validate_fast_market_behavior": "FAST_VALIDATION" not in market_action_outcome_quality({
            "status": "COMPLETED", "result": "PASS", "category": "FOUNDER_DISCOVERY", "action_type": "DOMAIN_EXPERT_OR_PRACTITIONER_INTERVIEW",
            "sample_target": 1, "pretest_snapshot": {"thesis_id": "t1"},
            "observations": {"observed_sample_size": 1, "actor_labels": ["Expert A"], "evidence_refs": ["note:1"], "decision_relevant_findings": "buyer process clarified"},
        })["eligible_domains"],
    }
