from __future__ import annotations

import asyncio
import re
from collections import Counter
from typing import Any, Mapping, Sequence

ENGINE_VERSION = "signalforge-opportunity-decision-part4-v1"
TRUTH_BOUNDARY = (
    "PART4_IS_A_READ_ONLY_FOUNDER_DECISION_PROJECTION_OVER_PUBLISHED_BRAIN,_MONEY_TRAIL,_"
    "FOUNDER_ADDRESSABILITY,_AND_PART3_DISPOSITION;_IT_HAS_ZERO_C01_C14_OR_MARKET_TRUTH_WRITE_AUTHORITY"
)

TRACKS = ("CASH", "BOTH", "ZIP2", "PARK")
_TRACK_MAP = {
    "FAST_VALIDATION": "CASH",
    "BOTH": "BOTH",
    "ZIP2_STRUCTURAL": "ZIP2",
    "NEITHER": "PARK",
}
_STATE_OK = {"SUPPORTED", "KNOWN"}
_STATE_PARTIAL = {"PARTIAL"}
_STATE_BAD = {"REFUTED", "CONTRADICTED", "BLOCKED"}
_STATE_OPEN = {"UNKNOWN", "INSUFFICIENT", "NOT_READY", "UNASSESSED", ""}


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _upper(value: Any) -> str:
    return _clean(value).upper()


def _state(value: Any) -> str:
    v = _upper(value)
    if v in _STATE_OK | _STATE_PARTIAL | _STATE_BAD | _STATE_OPEN:
        return v or "UNKNOWN"
    return v or "UNKNOWN"


def _dim(thesis: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    dims = thesis.get("dimensions") if isinstance(thesis.get("dimensions"), Mapping) else {}
    row = dims.get(name)
    return row if isinstance(row, Mapping) else {}


def _dim_state(thesis: Mapping[str, Any], name: str) -> str:
    return _state(_dim(thesis, name).get("state"))


def _claim_state(thesis: Mapping[str, Any], code: str) -> str:
    claims = thesis.get("claim_states") if isinstance(thesis.get("claim_states"), Mapping) else {}
    return _state(claims.get(code))


def _founder_dims(thesis: Mapping[str, Any]) -> Mapping[str, Any]:
    fa = thesis.get("founder_addressability") if isinstance(thesis.get("founder_addressability"), Mapping) else {}
    return fa.get("dimensions") if isinstance(fa.get("dimensions"), Mapping) else {}


def _founder_dim_state(thesis: Mapping[str, Any], name: str) -> str:
    row = _founder_dims(thesis).get(name)
    return _state(row.get("state")) if isinstance(row, Mapping) else "UNKNOWN"


def _wedge(trail: Mapping[str, Any]) -> Mapping[str, Any]:
    return trail.get("revenue_wedge") if isinstance(trail.get("revenue_wedge"), Mapping) else {}


def _pd_count(trail: Mapping[str, Any]) -> int:
    pd = trail.get("paid_dissatisfaction") if isinstance(trail.get("paid_dissatisfaction"), Mapping) else {}
    try:
        return int(pd.get("count") or 0)
    except Exception:
        return 0


def _evidence_count(trail: Mapping[str, Any]) -> int:
    try:
        return int(trail.get("published_evidence_count") or 0)
    except Exception:
        return 0


def founder_track(thesis: Mapping[str, Any], trail: Mapping[str, Any]) -> str:
    """Map canonical strategy to the Founder-facing CASH/BOTH/ZIP2/PARK vocabulary.

    This is projection only. It intentionally does not rewrite `strategic_track`.
    """
    strategic = _upper(thesis.get("strategic_track") or trail.get("strategic_track"))
    return _TRACK_MAP.get(strategic, "PARK")


def founder_fit_projection(thesis: Mapping[str, Any]) -> dict[str, Any]:
    fa = thesis.get("founder_addressability") if isinstance(thesis.get("founder_addressability"), Mapping) else {}
    dims = _founder_dims(thesis)
    names = ("task_capability", "domain_knowledge", "buyer_access", "legitimacy", "bridgeability", "right_to_win")
    out: dict[str, Any] = {}
    for name in names:
        row = dims.get(name) if isinstance(dims.get(name), Mapping) else {}
        out[name] = {
            "state": _state(row.get("state")),
            "basis": row.get("basis"),
            "evidence_refs": list(row.get("evidence_refs") or [])[:12],
        }
    return {
        "state": out["right_to_win"]["state"],
        "trust_burden": fa.get("trust_burden") or "UNKNOWN",
        "learning_distance": fa.get("learning_distance") or "UNKNOWN",
        "domains": list(fa.get("domains") or []),
        "blocking_unknowns": list(fa.get("blocking_unknowns") or []),
        "dimensions": out,
        "truth_boundary": "FOUNDER_FIT_IS_EXISTING_FIRST_PERSON_DERIVED_TRUTH;_IT_DOES_NOT_CHANGE_OBJECTIVE_MARKET_CLAIMS",
    }


def structural_mapper(thesis: Mapping[str, Any]) -> dict[str, Any]:
    names = (
        "problem_persistence", "transition_strength", "system_mismatch", "economic_materiality",
        "workaround_intensity", "buyer_formation", "gap_durability", "asset_accessibility",
        "distribution_leverage", "incumbent_response_power", "captureability", "expansion_surface",
    )
    rows: list[dict[str, Any]] = []
    for name in names:
        row = _dim(thesis, name)
        rows.append({
            "dimension": name,
            "state": _state(row.get("state")),
            "basis": row.get("basis"),
            "evidence_refs": list(row.get("evidence_refs") or row.get("evidence") or [])[:12],
            "metrics": dict(row.get("metrics") or {}) if isinstance(row.get("metrics"), Mapping) else {},
            "truth_owner": row.get("truth_owner"),
        })
    open_rows = [x for x in rows if x["state"] in _STATE_OPEN | _STATE_PARTIAL]
    bad_rows = [x for x in rows if x["state"] in _STATE_BAD]
    structural = thesis.get("structural_thesis") if isinstance(thesis.get("structural_thesis"), Mapping) else {}
    return {
        "zip2_readiness": thesis.get("zip2_readiness") or "NOT_ZIP2_CLASS",
        "opportunity_class": thesis.get("opportunity_class"),
        "structural_thesis": dict(structural),
        "dimensions": rows,
        "open_dimensions": [x["dimension"] for x in open_rows],
        "refuted_dimensions": [x["dimension"] for x in bad_rows],
        "truth_boundary": "STRUCTURAL_MAPPER_REPLAYS_EXISTING_BRAIN_DIMENSIONS;_NO_STRUCTURAL_FACT_IS_INVENTED_HERE",
    }


def _ladder_state(raw: str) -> str:
    s = _state(raw)
    if s in _STATE_OK:
        return "SUPPORTED"
    if s in _STATE_PARTIAL:
        return "PARTIAL"
    if s in _STATE_BAD:
        return "REFUTED"
    return "UNKNOWN"


def wedge_ladder(thesis: Mapping[str, Any], trail: Mapping[str, Any]) -> dict[str, Any]:
    wedge = _wedge(trail)
    spend = _upper(wedge.get("existing_spend")) or "UNKNOWN"
    reach = _upper(wedge.get("buyer_reachability")) or "UNKNOWN"
    decision = _upper(wedge.get("decision")) or "NOT_NOW"
    market_validation = thesis.get("market_validation") if isinstance(thesis.get("market_validation"), Mapping) else {}
    paid_state = _upper(market_validation.get("state") or market_validation.get("status")) or "UNVALIDATED"

    stages = [
        {"stage": "PROBLEM", "state": _ladder_state(_claim_state(thesis, "C03")), "basis": "Published C03 / economic-materiality context"},
        {"stage": "BUYER", "state": _ladder_state(_claim_state(thesis, "C05")), "basis": "Published C05"},
        {"stage": "UNRESOLVED_GAP", "state": _ladder_state(_claim_state(thesis, "C07")), "basis": "Published C07"},
        {"stage": "EXISTING_SPEND", "state": "SUPPORTED" if spend == "STRONG" else ("PARTIAL" if spend == "PARTIAL" else "UNKNOWN"), "basis": "Money Trail validated spend reconstruction"},
        {"stage": "REACHABLE_BUYER", "state": "SUPPORTED" if reach in {"STRONG", "SUPPORTED"} else ("PARTIAL" if reach in {"PARTIAL", "MEDIUM"} else "UNKNOWN"), "basis": "Founder addressability / Revenue Wedge"},
        {"stage": "TESTABLE_WEDGE", "state": "SUPPORTED" if decision == "TRY_NOW" else ("PARTIAL" if decision == "INVESTIGATE" else ("REFUTED" if decision == "KILL" else "UNKNOWN")), "basis": "Revenue Wedge decision"},
        {"stage": "REAL_PAID_OUTCOME", "state": "SUPPORTED" if paid_state in {"PASS", "VALIDATED", "SUPPORTED"} else ("REFUTED" if paid_state in {"FAIL", "REFUTED"} else "UNKNOWN"), "basis": "Market outcome only; engineering/research cannot promote this stage"},
    ]
    blocker = next((x for x in stages if x["state"] in {"UNKNOWN", "PARTIAL", "REFUTED"}), None)
    return {
        "stages": stages,
        "next_blocker": blocker,
        "revenue_wedge_decision": decision,
        "paid_outcome_authority": "REAL_MARKET_OUTCOME_ONLY",
        "truth_boundary": "WEDGE_LADDER_IS_A_PROJECTION;_REAL_PAID_OUTCOME_NEVER_INFERRED_FROM_RESEARCH_OR_FOUNDER_BELIEF",
    }


def _part3_disposition(trail: Mapping[str, Any]) -> dict[str, Any]:
    try:
        from processors.signalforge_trust_falsification import evaluate_kill_advance_park
        return dict(evaluate_kill_advance_park(trail))
    except Exception as exc:
        return {"current_disposition": "CONTINUE", "basis": f"Part 3 disposition unavailable: {type(exc).__name__}", "fresh_search_can_trigger_disposition": False}


def promotion_demotion_watch(thesis: Mapping[str, Any], trail: Mapping[str, Any], track: str) -> dict[str, Any]:
    fast = thesis.get("fast_validation") if isinstance(thesis.get("fast_validation"), Mapping) else {}
    fast_state = _upper(fast.get("state")) or "NOT_READY"
    zip2 = _upper(thesis.get("zip2_readiness")) or "NOT_ZIP2_CLASS"
    wedge = _wedge(trail)
    spend = _upper(wedge.get("existing_spend")) or "UNKNOWN"
    wedge_decision = _upper(wedge.get("decision")) or "NOT_NOW"
    buyer = _claim_state(thesis, "C05")
    gap = _claim_state(thesis, "C07")
    transition = _dim_state(thesis, "transition_strength")
    mismatch = _dim_state(thesis, "system_mismatch")
    incumbent = _dim_state(thesis, "incumbent_response_power")
    right = _founder_dim_state(thesis, "right_to_win")

    promote: list[dict[str, str]] = []
    demote: list[dict[str, str]] = []
    watch: list[dict[str, str]] = []

    if track == "ZIP2":
        promote.append({"to": "BOTH", "if": "Fast validation becomes READY/RESEARCH_READY, Published buyer+gap remain non-refuted, and a defensible existing-spend path appears."})
        watch.extend([
            {"trigger": "BUYER_BEHAVIOR", "for": "Published buyer formation / actual budget owner becomes supported"},
            {"trigger": "EXISTING_SPEND", "for": "Validated current spend or paid dissatisfaction appears"},
            {"trigger": "FAST_VALIDATION", "for": "A bounded first-dollar test becomes available"},
        ])
        demote.append({"to": "PARK", "if": "Published transition strength or system mismatch is REFUTED, or incumbent response becomes unsurvivable."})
    elif track == "CASH":
        promote.append({"to": "BOTH", "if": "ZIP2 readiness becomes ZIP2_CANDIDATE/HIGH_CONVICTION while the cash wedge remains actionable."})
        watch.extend([
            {"trigger": "STRUCTURAL_TRANSITION", "for": "Verified transition strength / system mismatch emerges"},
            {"trigger": "EXPANSION_SURFACE", "for": "Verified expansion surface appears without losing cash readiness"},
        ])
        demote.append({"to": "PARK", "if": "Published buyer or unresolved gap is REFUTED, Founder right-to-win is REFUTED, or Revenue Wedge becomes KILL."})
    elif track == "BOTH":
        demote.extend([
            {"to": "CASH", "if": "Structural thesis is refuted/stalls but the Revenue Wedge and buyer remain actionable."},
            {"to": "ZIP2", "if": "First-dollar validation becomes blocked but structural transition evidence remains valid."},
            {"to": "PARK", "if": "Both commercial wedge and structural thesis lose their Published basis."},
        ])
        watch.extend([
            {"trigger": "CASH_BREAK", "for": "Spend / buyer / WTP evidence weakens or incumbent solves the wedge"},
            {"trigger": "STRUCTURAL_BREAK", "for": "Transition/system mismatch/expansion evidence weakens"},
        ])
    else:
        promote.extend([
            {"to": "CASH", "if": "Fast validation becomes READY/RESEARCH_READY with a reachable buyer and defensible current spend."},
            {"to": "ZIP2", "if": "ZIP2 readiness becomes ZIP2_CANDIDATE/HIGH_CONVICTION from verified structural evidence."},
            {"to": "BOTH", "if": "Both conditions become true at the same time."},
        ])
        watch.extend([
            {"trigger": "CASH_FORMATION", "for": "Buyer + gap + existing spend become decision-ready"},
            {"trigger": "ZIP2_FORMATION", "for": "Transition + system mismatch + asset/expansion evidence becomes decision-ready"},
        ])

    current_facts = {
        "fast_validation": fast_state,
        "zip2_readiness": zip2,
        "existing_spend": spend,
        "revenue_wedge": wedge_decision,
        "buyer": buyer,
        "gap": gap,
        "transition_strength": transition,
        "system_mismatch": mismatch,
        "incumbent_response_power": incumbent,
        "founder_right_to_win": right,
    }
    return {
        "current_track": track,
        "promote_if": promote,
        "demote_if": demote,
        "kill_if": [
            "Published critical pain/buyer/gap/buildability truth is REFUTED or Part 3 disposition reaches KILL.",
            "Real market outcomes satisfy a pre-registered kill condition (Part 6 authority, not Part 4).",
        ],
        "watch_for": watch,
        "current_facts": current_facts,
        "truth_boundary": "TRIGGERS_STATE_WHAT_MUST_CHANGE_BEFORE_REVIEW;_THEY_ARE_NOT_MONITORING_RESULTS_AND_DO_NOT_AUTO_PROMOTE_OR_DEMOTE_TRUTH",
    }


def do_not_research(thesis: Mapping[str, Any], trail: Mapping[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    best = thesis.get("best_next_action") if isinstance(thesis.get("best_next_action"), Mapping) else {}
    mode = _upper(best.get("mode"))
    if mode == "MARKET_ACTION":
        rows.append({"topic": "MORE_GENERIC_DESK_RESEARCH", "reason": "Current Brain route says the decision-critical uncertainty is better reduced by bounded market action."})
    for code, label in (("C03", "problem/economic pain"), ("C05", "buyer formation"), ("C07", "unresolved gap"), ("C09", "buildability"), ("C13", "competition/incumbent survivability")):
        state = _claim_state(thesis, code)
        if state == "SUPPORTED":
            rows.append({"topic": f"MORE_{code}_{label.upper().replace('/', '_').replace(' ', '_')}", "reason": f"{code} is already Published SUPPORTED; do not collect more of the same unless new contradiction could change the decision."})
    if _upper(thesis.get("zip2_readiness")) not in {"ZIP2_CANDIDATE", "ZIP2_HIGH_CONVICTION"} and _upper(_wedge(trail).get("decision")) in {"TRY_NOW", "INVESTIGATE"}:
        rows.append({"topic": "GENERIC_LONG_TERM_TAM_STORY", "reason": "Current first-dollar decision does not require a larger long-term narrative."})
    if not rows:
        rows.append({"topic": "NO_BLANKET_STOP", "reason": "No research area is currently safe to suppress categorically; follow only the decision-changing frontier."})
    return rows[:8]


def what_changes_rank(thesis: Mapping[str, Any], trail: Mapping[str, Any], track: str) -> list[str]:
    wedge = _wedge(trail)
    changes: list[str] = []
    if _upper(wedge.get("existing_spend")) == "UNKNOWN":
        changes.append("Validated evidence of existing spend would materially raise cash priority.")
    if _pd_count(trail) == 0:
        changes.append("Independent paid-dissatisfaction evidence would strengthen the first-dollar wedge.")
    if _founder_dim_state(thesis, "buyer_access") in _STATE_OPEN | _STATE_BAD:
        changes.append("A reachable buyer channel becoming SUPPORTED/PARTIAL would raise Founder addressability.")
    if track in {"ZIP2", "PARK"} and _upper(thesis.get("fast_validation", {}).get("state") if isinstance(thesis.get("fast_validation"), Mapping) else "") not in {"READY", "RESEARCH_READY"}:
        changes.append("A bounded fast-validation route becoming READY/RESEARCH_READY could promote this toward CASH/BOTH.")
    if track in {"CASH", "PARK"} and _upper(thesis.get("zip2_readiness")) not in {"ZIP2_CANDIDATE", "ZIP2_HIGH_CONVICTION"}:
        changes.append("Verified transition/system-mismatch evidence strong enough for ZIP2_CANDIDATE could raise long-term priority.")
    if _claim_state(thesis, "C05") in _STATE_BAD or _claim_state(thesis, "C07") in _STATE_BAD:
        changes.append("Published buyer/gap refutation must be reversed by valid new evidence before this can rank as active.")
    return changes[:6]


def _priority_band(item: Mapping[str, Any], *, cash_need: str, long_term: str) -> str:
    if bool(item.get("hard_kill")):
        return "PARK_OR_KILL"
    track = _upper(item.get("current_track"))
    wedge = _upper(item.get("revenue_wedge_decision"))
    fit = _upper((item.get("founder_fit") or {}).get("state")) if isinstance(item.get("founder_fit"), Mapping) else "UNKNOWN"
    if fit == "REFUTED":
        return "PARK_OR_PARTNER"
    if track == "BOTH" and wedge == "TRY_NOW":
        return "ACTION_NOW"
    if track == "CASH" and wedge == "TRY_NOW":
        return "ACTION_NOW"
    if track in {"BOTH", "CASH"}:
        return "VALIDATE_NOW"
    if track == "ZIP2":
        return "STRUCTURAL_WATCH" if long_term != "LOW" else "LOWER_PRIORITY_WATCH"
    return "PARK"


def _rank_key(item: Mapping[str, Any], *, cash_need: str, long_term: str) -> tuple[Any, ...]:
    band_order = {"ACTION_NOW": 0, "VALIDATE_NOW": 1, "STRUCTURAL_WATCH": 2, "LOWER_PRIORITY_WATCH": 3, "PARK_OR_PARTNER": 4, "PARK_OR_KILL": 5, "PARK": 6}
    band = _priority_band(item, cash_need=cash_need, long_term=long_term)
    track = _upper(item.get("current_track"))
    if cash_need == "HIGH":
        track_order = {"BOTH": 0, "CASH": 1, "ZIP2": 2, "PARK": 3}
    elif long_term == "HIGH" and cash_need == "LOW":
        track_order = {"BOTH": 0, "ZIP2": 1, "CASH": 2, "PARK": 3}
    else:
        track_order = {"BOTH": 0, "CASH": 1, "ZIP2": 1, "PARK": 3}
    wedge_order = {"TRY_NOW": 0, "INVESTIGATE": 1, "NOT_NOW": 2, "KILL": 3}
    spend_order = {"STRONG": 0, "PARTIAL": 1, "UNKNOWN": 2}
    fit_order = {"SUPPORTED": 0, "PARTIAL": 1, "INSUFFICIENT": 2, "UNKNOWN": 3, "REFUTED": 4}
    return (
        band_order.get(band, 9),
        track_order.get(track, 9),
        wedge_order.get(_upper(item.get("revenue_wedge_decision")), 9),
        spend_order.get(_upper(item.get("existing_spend")), 9),
        fit_order.get(_upper((item.get("founder_fit") or {}).get("state")), 9),
        -int(item.get("paid_dissatisfaction_count") or 0),
        -int(item.get("published_evidence_count") or 0),
        _clean(item.get("thesis_id")),
    )


def build_decision_item(thesis: Mapping[str, Any], trail: Mapping[str, Any]) -> dict[str, Any]:
    track = founder_track(thesis, trail)
    disposition = _part3_disposition(trail)
    wedge = _wedge(trail)
    fit = founder_fit_projection(thesis)
    structure = structural_mapper(thesis)
    ladder = wedge_ladder(thesis, trail)
    hard_kill = _upper(disposition.get("current_disposition")) == "KILL" or _upper(wedge.get("decision")) == "KILL"
    trigger = promotion_demotion_watch(thesis, trail, track)
    return {
        "engine_version": ENGINE_VERSION,
        "thesis_id": thesis.get("thesis_id") or trail.get("thesis_id"),
        "title": thesis.get("representative_title") or trail.get("title"),
        "problem": thesis.get("representative_problem") or trail.get("problem"),
        "current_track": "PARK" if hard_kill else track,
        "canonical_strategic_track": thesis.get("strategic_track") or trail.get("strategic_track"),
        "classification": thesis.get("classification"),
        "zip2_readiness": thesis.get("zip2_readiness"),
        "revenue_wedge_decision": _upper(wedge.get("decision")) or "NOT_NOW",
        "existing_spend": _upper(wedge.get("existing_spend")) or "UNKNOWN",
        "paid_dissatisfaction_count": _pd_count(trail),
        "published_evidence_count": _evidence_count(trail),
        "founder_fit": fit,
        "structural_mapper": structure,
        "wedge_ladder": ladder,
        "best_next_action": dict(thesis.get("best_next_action") or {}) if isinstance(thesis.get("best_next_action"), Mapping) else {},
        "decision_frontier": trail.get("decision_frontier") or thesis.get("best_next_evidence") or ladder.get("next_blocker"),
        "part3_disposition": disposition,
        "hard_kill": hard_kill,
        "promotion_demotion_watch": trigger,
        "do_not_research": do_not_research(thesis, trail),
        "what_changes_rank": what_changes_rank(thesis, trail, track),
        "market_truth_writes": 0,
        "truth_boundary": TRUTH_BOUNDARY,
    }


def compare_decision_items(items: Sequence[Mapping[str, Any]], *, cash_need: str = "HIGH", long_term: str = "HIGH") -> dict[str, Any]:
    cash_need = _upper(cash_need) if _upper(cash_need) in {"HIGH", "MEDIUM", "LOW"} else "HIGH"
    long_term = _upper(long_term) if _upper(long_term) in {"HIGH", "MEDIUM", "LOW"} else "HIGH"
    rows = [dict(x) for x in items]
    for row in rows:
        row["priority_band"] = _priority_band(row, cash_need=cash_need, long_term=long_term)
    rows.sort(key=lambda x: _rank_key(x, cash_need=cash_need, long_term=long_term))
    for idx, row in enumerate(rows, 1):
        row["rank"] = idx
        row["rank_explanation"] = {
            "band": row.get("priority_band"),
            "track": row.get("current_track"),
            "revenue_wedge": row.get("revenue_wedge_decision"),
            "existing_spend": row.get("existing_spend"),
            "founder_fit": (row.get("founder_fit") or {}).get("state") if isinstance(row.get("founder_fit"), Mapping) else "UNKNOWN",
            "paid_dissatisfaction": row.get("paid_dissatisfaction_count"),
            "note": "Lexicographic decision rules, not an opaque weighted confidence score.",
        }
    return {
        "engine_version": ENGINE_VERSION,
        "status": "PASS",
        "settings": {"cash_need": cash_need, "long_term": long_term},
        "count": len(rows),
        "items": rows,
        "top": rows[0] if rows else None,
        "ranking_method": "TRANSPARENT_LEXICOGRAPHIC_RULES_NO_OPAQUE_TOTAL_SCORE",
        "market_truth_writes": 0,
        "truth_boundary": TRUTH_BOUNDARY,
    }


def _round_half(value: float) -> float:
    return round(value * 2.0) / 2.0


def resource_allocation(compare_result: Mapping[str, Any], *, weekly_hours: float = 10.0, cash_need: str = "HIGH", long_term: str = "HIGH") -> dict[str, Any]:
    hours = max(1.0, min(float(weekly_hours or 10.0), 80.0))
    cash_need = _upper(cash_need) if _upper(cash_need) in {"HIGH", "MEDIUM", "LOW"} else "HIGH"
    long_term = _upper(long_term) if _upper(long_term) in {"HIGH", "MEDIUM", "LOW"} else "HIGH"
    rows = list(compare_result.get("items") or [])
    cash_rows = [x for x in rows if x.get("current_track") in {"CASH", "BOTH"} and not x.get("hard_kill")]
    both_rows = [x for x in rows if x.get("current_track") == "BOTH" and not x.get("hard_kill")]
    zip_rows = [x for x in rows if x.get("current_track") == "ZIP2" and not x.get("hard_kill")]

    if cash_need == "HIGH":
        shares = {"CASH_VALIDATION": 0.70, "BOTH_DEEPENING": 0.20, "ZIP2_WATCH": 0.10}
    elif cash_need == "MEDIUM":
        shares = {"CASH_VALIDATION": 0.55, "BOTH_DEEPENING": 0.25, "ZIP2_WATCH": 0.20}
    else:
        shares = {"CASH_VALIDATION": 0.40, "BOTH_DEEPENING": 0.30, "ZIP2_WATCH": 0.30}
    if long_term == "LOW":
        shares["CASH_VALIDATION"] += shares["ZIP2_WATCH"] * 0.7
        shares["BOTH_DEEPENING"] += shares["ZIP2_WATCH"] * 0.3
        shares["ZIP2_WATCH"] = 0.0
    elif long_term == "HIGH" and cash_need != "HIGH":
        shift = min(0.10, shares["CASH_VALIDATION"] - 0.30)
        shares["CASH_VALIDATION"] -= shift
        shares["ZIP2_WATCH"] += shift

    buckets = {
        "CASH_VALIDATION": cash_rows[:2],
        "BOTH_DEEPENING": both_rows[:1],
        "ZIP2_WATCH": zip_rows[:2],
    }
    inactive_share = sum(shares[k] for k, vals in buckets.items() if not vals)
    active = [k for k, vals in buckets.items() if vals]
    if active and inactive_share:
        base = sum(shares[k] for k in active)
        if base > 0:
            for k in active:
                shares[k] += inactive_share * (shares[k] / base)
    for k, vals in buckets.items():
        if not vals:
            shares[k] = 0.0

    allocations: list[dict[str, Any]] = []
    for bucket in ("CASH_VALIDATION", "BOTH_DEEPENING", "ZIP2_WATCH"):
        candidates = buckets[bucket]
        if not candidates:
            continue
        bucket_hours = _round_half(hours * shares[bucket])
        per = _round_half(bucket_hours / len(candidates)) if candidates else 0.0
        remaining = bucket_hours
        for idx, item in enumerate(candidates):
            h = remaining if idx == len(candidates) - 1 else min(per, remaining)
            remaining = max(0.0, remaining - h)
            allocations.append({
                "bucket": bucket,
                "thesis_id": item.get("thesis_id"),
                "title": item.get("title"),
                "hours": h,
                "why": (
                    "Prioritize near-term decision-changing buyer/spend validation." if bucket == "CASH_VALIDATION" else
                    "Preserve a dual-use opportunity that can produce cash learning and structural learning." if bucket == "BOTH_DEEPENING" else
                    "Keep a bounded watch on a structural bet; do not turn it into an open-ended research project."
                ),
                "dependency": (item.get("best_next_action") or {}).get("reason") if isinstance(item.get("best_next_action"), Mapping) else None,
                "expected_learning": item.get("decision_frontier") or ((item.get("wedge_ladder") or {}).get("next_blocker") if isinstance(item.get("wedge_ladder"), Mapping) else None),
                "what_changes_this": list(item.get("what_changes_rank") or [])[:3],
            })
    allocated = sum(float(x.get("hours") or 0) for x in allocations)
    return {
        "weekly_hours": hours,
        "cash_need": cash_need,
        "long_term": long_term,
        "allocations": allocations,
        "allocated_hours": _round_half(allocated),
        "unallocated_hours": _round_half(max(0.0, hours - allocated)),
        "advisory_only": True,
        "authority": "FOUNDER_RESOURCE_DECISION_SUPPORT_ONLY",
        "truth_boundary": "RESOURCE_ALLOCATION_DOES_NOT_AUTOMATICALLY_SCHEDULE_WORK_OR_CHANGE_MARKET_TRUTH",
    }


def _ask_intent(q: str) -> str:
    low = _clean(q).lower()
    if any(x in low for x in ("不要研究", "不用研究", "do not research", "stop researching")):
        return "DO_NOT_RESEARCH"
    if any(x in low for x in ("trigger", "重新看", "什麼時候", "何時")):
        return "WATCH"
    if any(x in low for x in ("zip2", "structural", "長期", "結構")):
        return "ZIP2"
    if "watch" in low:
        return "WATCH"
    if any(x in low for x in ("existing spend", "paid dissatisfaction", "first dollar", "第一筆錢", "現金", "付費", "花錢")):
        return "CASH"
    if any(x in low for x in ("park", "暫停", "先不做", "kill")):
        return "PARK"
    if any(x in low for x in ("compare", "比較", "只能做一個", "哪個", "最好", "best", "top")):
        return "BEST_ONE"
    return "UNKNOWN"


def ask_signalforge(q: str, compare_result: Mapping[str, Any]) -> dict[str, Any]:
    intent = _ask_intent(q)
    rows = list(compare_result.get("items") or [])
    if intent == "CASH":
        matches = [x for x in rows if x.get("current_track") in {"CASH", "BOTH"} and (x.get("existing_spend") in {"STRONG", "PARTIAL"} or int(x.get("paid_dissatisfaction_count") or 0) > 0)]
        answer = "These directions currently combine a cash-capable track with Published spend / paid-dissatisfaction evidence."
    elif intent == "ZIP2":
        matches = [x for x in rows if x.get("current_track") in {"ZIP2", "BOTH"}]
        answer = "These directions currently carry a structural ZIP2/BOTH projection."
    elif intent == "PARK":
        matches = [x for x in rows if x.get("current_track") == "PARK" or x.get("hard_kill")]
        answer = "These directions are currently parked or hard-killed by the decision projection."
    elif intent == "WATCH":
        matches = rows[:8]
        answer = "Trigger Watch shows the specific world-state changes that justify reopening each thesis."
    elif intent == "DO_NOT_RESEARCH":
        matches = rows[:8]
        answer = "These are the current areas SignalForge says should not receive more same-type research unless a new contradiction appears."
    elif intent == "BEST_ONE":
        matches = rows[:5]
        answer = "The first row is the current decision priority under the selected Founder cash/long-term settings; ranking is rule-based and exposes what would change it."
    else:
        matches = []
        answer = "This Part 4 Ask surface is intentionally bounded and deterministic. Ask about: best/compare, first-dollar cash, ZIP2/long-term, PARK, Trigger Watch, or Do Not Research."
    return {
        "engine_version": ENGINE_VERSION,
        "status": "PASS",
        "query": _clean(q),
        "intent": intent,
        "answer": answer,
        "matches": matches,
        "market_truth_writes": 0,
        "truth_boundary": "ASK_SIGNALFORGE_QUERIES_EXISTING_DECISION_PROJECTIONS;_IT_DOES_NOT_USE_FREEFORM_LLM_TEXT_TO_CREATE_MARKET_FACTS",
    }


async def build_opportunity_decision_portfolio(*, limit: int = 30, weekly_hours: float = 10.0, cash_need: str = "HIGH", long_term: str = "HIGH") -> dict[str, Any]:
    from processors.signalforge_brain_v2_engine import get_brain_v2_portfolio
    from processors.signalforge_money_trail import build_money_trail_for_thesis

    portfolio = dict(get_brain_v2_portfolio())
    theses = [dict(x) for x in (portfolio.get("portfolio") or []) if isinstance(x, Mapping)][: max(1, min(int(limit or 30), 100))]
    if not theses:
        compare = compare_decision_items([], cash_need=cash_need, long_term=long_term)
        return {
            **compare,
            "status": portfolio.get("status") or "EMPTY",
            "resource_allocation": resource_allocation(compare, weekly_hours=weekly_hours, cash_need=cash_need, long_term=long_term),
            "track_counts": {k: 0 for k in TRACKS},
            "market_calibration": portfolio.get("market_calibration") or {},
        }

    async def one(thesis: Mapping[str, Any]) -> dict[str, Any]:
        try:
            trail = await build_money_trail_for_thesis(thesis)
        except Exception as exc:
            trail = {
                "thesis_id": thesis.get("thesis_id"),
                "title": thesis.get("representative_title"),
                "revenue_wedge": {"decision": "NOT_NOW", "existing_spend": "UNKNOWN", "buyer_reachability": "UNKNOWN"},
                "paid_dissatisfaction": {"count": 0},
                "published_evidence_count": 0,
                "status": "MONEY_TRAIL_UNAVAILABLE_NON_BLOCKING",
                "error": f"{type(exc).__name__}: {exc}",
            }
        return build_decision_item(thesis, trail)

    items = await asyncio.gather(*(one(x) for x in theses))
    compare = compare_decision_items(items, cash_need=cash_need, long_term=long_term)
    track_counts = Counter(str(x.get("current_track") or "PARK") for x in compare.get("items") or [])
    compare["track_counts"] = {k: int(track_counts.get(k, 0)) for k in TRACKS}
    compare["resource_allocation"] = resource_allocation(compare, weekly_hours=weekly_hours, cash_need=cash_need, long_term=long_term)
    compare["market_calibration"] = portfolio.get("market_calibration") or {}
    compare["authority"] = "FOUNDER_DECISION_SUPPORT_ONLY"
    return compare


async def compare_theses(thesis_ids: Sequence[str], *, weekly_hours: float = 10.0, cash_need: str = "HIGH", long_term: str = "HIGH") -> dict[str, Any]:
    wanted = {_clean(x) for x in thesis_ids if _clean(x)}
    result = await build_opportunity_decision_portfolio(limit=100, weekly_hours=weekly_hours, cash_need=cash_need, long_term=long_term)
    rows = [x for x in result.get("items") or [] if _clean(x.get("thesis_id")) in wanted]
    compare = compare_decision_items(rows, cash_need=cash_need, long_term=long_term)
    compare["resource_allocation"] = resource_allocation(compare, weekly_hours=weekly_hours, cash_need=cash_need, long_term=long_term)
    compare["requested_thesis_ids"] = sorted(wanted)
    compare["missing_thesis_ids"] = sorted(wanted - {_clean(x.get("thesis_id")) for x in rows})
    return compare


async def ask_current_signalforge(q: str, *, weekly_hours: float = 10.0, cash_need: str = "HIGH", long_term: str = "HIGH") -> dict[str, Any]:
    portfolio = await build_opportunity_decision_portfolio(limit=50, weekly_hours=weekly_hours, cash_need=cash_need, long_term=long_term)
    return ask_signalforge(q, portfolio)
