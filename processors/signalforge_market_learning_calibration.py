"""SignalForge Part 6 market-learning calibration — semantic closure.

Calibration is deliberately narrower than durable execution history:
- only quality-eligible preregistered outcomes enter learning;
- Founder-discovery outcomes cannot change FAST_VALIDATION market ranking;
- action/metric semantics are isolated (paid commitment != reply != interview != switch);
- repeated actions from one thesis are aggregated to one independent entity per segment;
- each feature bucket *and* its complement need independent thesis diversity;
- no C01-C14 writes and no general predictive accuracy claim.
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Mapping

ENGINE_VERSION = "signalforge-part6-market-learning-calibration-v2-domain-semantic-independent"
TRUTH_BOUNDARY = (
    "CALIBRATION_IS_DOMAIN_AND_ACTION_SEMANTIC_SCOPED,_AGGREGATES_REPEATED_ACTIONS_PER_THESIS,_"
    "AND_CONSUMES_ONLY_QUALITY_ELIGIBLE_PREREGISTERED_OUTCOMES;_NO_C01_C14_WRITES_OR_GENERAL_ACCURACY_CLAIM"
)
MIN_BUCKET_OUTCOMES = 4
MIN_COMPLEMENT_OUTCOMES = 4
MIN_DISTINCT_ENTITIES_PER_SIDE = 4
Z_95 = 1.959963984540054

FEATURE_KEYS = (
    "existing_spend_present",
    "paid_dissatisfaction_present",
    "manual_labor_spend_present",
    "distribution_gate_pass",
    "market_track",
    "founder_action",
)

ACTION_SEMANTIC = {
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


def _upper(v: Any) -> str:
    return str(v or "").strip().upper()


def _mapping(v: Any) -> Mapping[str, Any]:
    return v if isinstance(v, Mapping) else {}


def _semantic_for_action(action: Any) -> str:
    return ACTION_SEMANTIC.get(_upper(action), "UNKNOWN_SEMANTIC")


def learning_features_from_projection(thesis: Mapping[str, Any], trail: Mapping[str, Any], decision_item: Mapping[str, Any]) -> dict[str, Any]:
    """Freeze coarse, auditable decision-time features.

    The recommended action semantic/domain is frozen too, so future calibration
    compares like-for-like outcomes rather than mixing replies, interviews and payments.
    """
    wedge = _mapping(trail.get("revenue_wedge"))
    current_spend = _mapping(trail.get("current_spend"))
    paid = _mapping(trail.get("paid_dissatisfaction"))
    spend_rows = current_spend.get("observations") or current_spend.get("items") or []
    if not isinstance(spend_rows, list):
        spend_rows = []
    manual = any(_upper(_mapping(x).get("bucket")) == "LABOR_SPEND" for x in spend_rows if isinstance(x, Mapping))
    gate = _mapping(decision_item.get("founder_actionability"))
    market_track = _upper(decision_item.get("market_track") or decision_item.get("current_track") or thesis.get("strategic_track")) or "UNKNOWN"
    founder_action = _upper(decision_item.get("founder_action")) or "UNKNOWN"
    spend_state = _upper(wedge.get("existing_spend"))
    best = _mapping(thesis.get("best_next_action"))
    founder_action = _upper(decision_item.get("founder_action")) or "UNKNOWN"
    if founder_action == "VALIDATE_DISTRIBUTION":
        action_type, mode = "IDENTIFY_REACHABLE_BUYER_CHANNEL", "FOUNDER_DISCOVERY"
    elif founder_action == "INVESTIGATE":
        action_type, mode = "DOMAIN_EXPERT_OR_PRACTITIONER_INTERVIEW", "FOUNDER_DISCOVERY"
    elif founder_action == "NARROW_WEDGE":
        action_type, mode = "BUYER_INTERVIEW", "MARKET_ACTION"
    else:
        action_type = _upper(best.get("action")) or "UNKNOWN"
        mode = _upper(best.get("mode"))
    domain = "FOUNDER_ADDRESSABILITY" if mode == "FOUNDER_DISCOVERY" else "FAST_VALIDATION"
    return {
        "existing_spend_present": spend_state in {"STRONG", "PARTIAL", "SUPPORTED", "KNOWN"},
        "paid_dissatisfaction_present": int(paid.get("count") or 0) > 0,
        "manual_labor_spend_present": bool(manual),
        "distribution_gate_pass": bool(gate.get("gate_pass")),
        "market_track": market_track,
        "founder_action": founder_action,
        "recommended_action_type": action_type,
        "action_semantic_family": _semantic_for_action(action_type),
        "calibration_domain": domain,
        "feature_source": "FROZEN_PRETEST_PROJECTION",
    }


def _wilson(pass_n: int, total_n: int) -> tuple[float, float] | None:
    if total_n <= 0:
        return None
    p = pass_n / total_n
    z2 = Z_95 * Z_95
    denom = 1 + z2 / total_n
    center = (p + z2 / (2 * total_n)) / denom
    half = Z_95 * math.sqrt((p * (1 - p) + z2 / (4 * total_n)) / total_n) / denom
    return max(0.0, center - half), min(1.0, center + half)


def _entity_key(row: Mapping[str, Any]) -> str:
    return str(row.get("thesis_id") or _mapping(row.get("pretest_snapshot")).get("thesis_id") or "")


def _feature_value(row: Mapping[str, Any], key: str) -> Any:
    features = _mapping(row.get("learning_features")) or _mapping(_mapping(row.get("pretest_snapshot")).get("part6_learning_features"))
    return features.get(key)


def _row_domains(row: Mapping[str, Any]) -> set[str]:
    q = _mapping(row.get("outcome_quality"))
    raw = q.get("eligible_domains") or row.get("eligible_domains") or []
    if isinstance(raw, str):
        raw = [raw]
    domains = {_upper(x) for x in raw if _upper(x)} if isinstance(raw, (list, tuple, set)) else set()
    if domains:
        return domains
    features = _mapping(row.get("learning_features")) or _mapping(_mapping(row.get("pretest_snapshot")).get("part6_learning_features"))
    if _upper(features.get("calibration_domain")):
        return {_upper(features.get("calibration_domain"))}
    category = _upper(row.get("category"))
    if category == "FOUNDER_DISCOVERY":
        return {"FOUNDER_ADDRESSABILITY"}
    if category == "MARKET_ACTION":
        return {"FAST_VALIDATION", "FOUNDER_ADDRESSABILITY"}
    return set()


def _row_semantic(row: Mapping[str, Any]) -> str:
    q = _mapping(row.get("outcome_quality"))
    if _upper(q.get("semantic_family")):
        return _upper(q.get("semantic_family"))
    features = _mapping(row.get("learning_features")) or _mapping(_mapping(row.get("pretest_snapshot")).get("part6_learning_features"))
    return _upper(features.get("action_semantic_family") or features.get("metric_family")) or _semantic_for_action(row.get("action_type"))


def _outcome_rows() -> list[dict[str, Any]]:
    try:
        from processors.signalforge_market_action_registry import calibration_eligible_outcomes
        rows = calibration_eligible_outcomes()
    except Exception:
        return []
    return [dict(r) for r in rows if _upper(r.get("result")) in {"PASS", "FAIL"}]


def _bucket_key(value: Any) -> str:
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    return _upper(value) or "UNKNOWN"


def _aggregate_independent_entities(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """One independent outcome per thesis within a domain+semantic segment.

    Repeated actions that all agree collapse to one thesis observation. Mixed
    results are excluded as conflicted rather than cherry-picked.
    """
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = _entity_key(row)
        if key:
            grouped[key].append(row)
    aggregated: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    for entity, vals in grouped.items():
        results = {_upper(x.get("result")) for x in vals if _upper(x.get("result")) in {"PASS", "FAIL"}}
        if len(results) != 1:
            conflicts.append({"entity": entity, "results": sorted(results), "actions": len(vals), "reason": "REPEATED_THESIS_OUTCOMES_CONFLICT"})
            continue
        # Features were frozen at action time. A changed feature within the same
        # thesis/segment is ambiguous for this aggregation and is excluded.
        feature_snapshots = [
            _mapping(x.get("learning_features")) or _mapping(_mapping(x.get("pretest_snapshot")).get("part6_learning_features"))
            for x in vals
        ]
        feature_signature = {
            tuple((k, _bucket_key(f.get(k))) for k in FEATURE_KEYS)
            for f in feature_snapshots
        }
        if len(feature_signature) != 1:
            conflicts.append({"entity": entity, "actions": len(vals), "reason": "FEATURES_CHANGED_ACROSS_REPEATED_TESTS"})
            continue
        row = dict(vals[-1])
        row["result"] = next(iter(results))
        row["independent_entity"] = entity
        row["aggregated_action_count"] = len(vals)
        aggregated.append(row)
    return aggregated, conflicts


def _segment_report(rows: list[dict[str, Any]], *, domain: str, semantic_family: str) -> dict[str, Any]:
    independent, conflicts = _aggregate_independent_entities(rows)
    feature_results: dict[str, list[dict[str, Any]]] = {}
    for key in FEATURE_KEYS:
        buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in independent:
            value = _feature_value(row, key)
            if value is not None:
                buckets[_bucket_key(value)].append(row)
        all_rows = [r for vals in buckets.values() for r in vals]
        rows_for_key: list[dict[str, Any]] = []
        for bucket, selected in sorted(buckets.items()):
            complement = [r for r in all_rows if r not in selected]
            selected_pass = sum(_upper(r.get("result")) == "PASS" for r in selected)
            complement_pass = sum(_upper(r.get("result")) == "PASS" for r in complement)
            selected_entities = {_entity_key(r) for r in selected if _entity_key(r)}
            complement_entities = {_entity_key(r) for r in complement if _entity_key(r)}
            s_ci = _wilson(selected_pass, len(selected))
            c_ci = _wilson(complement_pass, len(complement))
            enough = (
                len(selected) >= MIN_BUCKET_OUTCOMES
                and len(complement) >= MIN_COMPLEMENT_OUTCOMES
                and len(selected_entities) >= MIN_DISTINCT_ENTITIES_PER_SIDE
                and len(complement_entities) >= MIN_DISTINCT_ENTITIES_PER_SIDE
                and s_ci is not None and c_ci is not None
            )
            action = "UNVALIDATED"
            if enough:
                if s_ci[0] > c_ci[1]: action = "UPWEIGHT"
                elif s_ci[1] < c_ci[0]: action = "DOWNWEIGHT"
                else: action = "NEUTRAL"
            rows_for_key.append({
                "feature": key,
                "bucket": bucket,
                "domain": domain,
                "semantic_family": semantic_family,
                "outcomes": len(selected),
                "passes": selected_pass,
                "fails": len(selected)-selected_pass,
                "entities": len(selected_entities),
                "complement_outcomes": len(complement),
                "complement_passes": complement_pass,
                "complement_entities": len(complement_entities),
                "wilson95": [round(s_ci[0],4), round(s_ci[1],4)] if s_ci else None,
                "complement_wilson95": [round(c_ci[0],4), round(c_ci[1],4)] if c_ci else None,
                "ranking_adjustment": action,
                "eligible": enough,
            })
        feature_results[key] = rows_for_key
    actionable = [r for vals in feature_results.values() for r in vals if r.get("ranking_adjustment") in {"UPWEIGHT","DOWNWEIGHT"}]
    return {
        "domain": domain,
        "semantic_family": semantic_family,
        "raw_outcomes": len(rows),
        "independent_entities": len(independent),
        "excluded_conflicts": conflicts,
        "features": feature_results,
        "actionable_adjustments": actionable,
        "status": "PRELIMINARY_SIGNAL_CALIBRATION" if actionable else "UNVALIDATED",
    }


def market_learning_calibration_report(
    rows: list[Mapping[str, Any]] | None = None,
    *,
    domain: str = "FAST_VALIDATION",
    semantic_family: str | None = None,
) -> dict[str, Any]:
    """Domain- and semantic-scoped calibration report.

    The default is FAST_VALIDATION because only market-behavior outcomes may be
    used as a Part 4 market-ranking tie-breaker. Founder-discovery learning is
    still reportable under FOUNDER_ADDRESSABILITY but never leaks into ranking.
    """
    source = [dict(x) for x in (rows if rows is not None else _outcome_rows()) if _upper(x.get("result")) in {"PASS","FAIL"}]
    domain = _upper(domain) or "FAST_VALIDATION"
    scoped = [x for x in source if domain in _row_domains(x)]
    semantic_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in scoped:
        semantic_groups[_row_semantic(row)].append(row)
    if semantic_family:
        wanted = _upper(semantic_family)
        semantic_groups = defaultdict(list, {wanted: semantic_groups.get(wanted, [])})
    segments = {sem: _segment_report(vals, domain=domain, semantic_family=sem) for sem, vals in sorted(semantic_groups.items())}
    actionable = [r for seg in segments.values() for r in seg.get("actionable_adjustments") or []]
    # Backward-compatible top-level features only when exactly one semantic is requested/resolved.
    top_features: dict[str, Any] = {}
    if len(segments) == 1:
        top_features = next(iter(segments.values())).get("features") or {}
    return {
        "engine_version": ENGINE_VERSION,
        "status": "PRELIMINARY_SIGNAL_CALIBRATION" if actionable else "UNVALIDATED",
        "domain": domain,
        "semantic_family": _upper(semantic_family) or "SEPARATED_NOT_MIXED",
        "eligible_outcomes": len(scoped),
        "raw_outcomes_all_domains": len(source),
        "segments": segments,
        "features": top_features,
        "actionable_adjustments": actionable,
        "minimum_policy": {
            "bucket_outcomes": MIN_BUCKET_OUTCOMES,
            "complement_outcomes": MIN_COMPLEMENT_OUTCOMES,
            "distinct_entities_per_bucket": MIN_DISTINCT_ENTITIES_PER_SIDE,
            "distinct_entities_per_complement": MIN_DISTINCT_ENTITIES_PER_SIDE,
            "repeated_actions_per_thesis": "AGGREGATED_TO_ONE_INDEPENDENT_ENTITY_OR_EXCLUDED_IF_CONFLICTED",
            "domain_isolation": True,
            "action_semantic_isolation": True,
            "interval": "WILSON_95",
            "requires_non_overlapping_bucket_vs_complement_intervals": True,
        },
        "general_predictive_accuracy": "UNVALIDATED",
        "market_truth_writes": 0,
        "truth_boundary": TRUTH_BOUNDARY,
    }


def calibration_adjustment_for_features(features: Mapping[str, Any], report: Mapping[str, Any] | None = None) -> dict[str, Any]:
    domain = _upper(features.get("calibration_domain")) or "FAST_VALIDATION"
    semantic = _upper(features.get("action_semantic_family") or features.get("metric_family")) or "UNKNOWN_SEMANTIC"
    # Market ranking may only consume FAST_VALIDATION. Founder-addressability
    # learning belongs to the Founder actionability layer, not market success.
    if domain != "FAST_VALIDATION":
        return {
            "adjustment": "UNVALIDATED",
            "signals": [],
            "applied_to_ranking": False,
            "domain": domain,
            "semantic_family": semantic,
            "reason": "FOUNDER_DISCOVERY_CALIBRATION_CANNOT_CHANGE_MARKET_RANKING",
            "general_predictive_accuracy": "UNVALIDATED",
            "market_truth_writes": 0,
            "truth_boundary": TRUTH_BOUNDARY,
        }
    report = dict(report or market_learning_calibration_report(domain=domain, semantic_family=semantic))
    segment = _mapping(_mapping(report.get("segments")).get(semantic))
    features_report = _mapping(segment.get("features")) or _mapping(report.get("features"))
    hits: list[dict[str, Any]] = []
    for key in FEATURE_KEYS:
        if key not in features:
            continue
        bucket = _bucket_key(features.get(key))
        for row in features_report.get(key, []) or []:
            if str(row.get("bucket")) == bucket and str(row.get("ranking_adjustment")) in {"UPWEIGHT","DOWNWEIGHT"}:
                hits.append(dict(row))
    up = sum(x.get("ranking_adjustment") == "UPWEIGHT" for x in hits)
    down = sum(x.get("ranking_adjustment") == "DOWNWEIGHT" for x in hits)
    if up and not down: adjustment = "UPWEIGHT"
    elif down and not up: adjustment = "DOWNWEIGHT"
    elif up or down: adjustment = "MIXED"
    else: adjustment = "UNVALIDATED"
    return {
        "adjustment": adjustment,
        "signals": hits,
        "applied_to_ranking": adjustment in {"UPWEIGHT","DOWNWEIGHT"},
        "domain": domain,
        "semantic_family": semantic,
        "general_predictive_accuracy": "UNVALIDATED",
        "market_truth_writes": 0,
        "truth_boundary": "ONLY_FAST_VALIDATION_AND_MATCHING_ACTION_SEMANTIC_CAN_BE_A_TRANSPARENT_PART4_TIEBREAKER;_FOUNDER_DISCOVERY_NEVER_BECOMES_MARKET_SUCCESS",
    }
