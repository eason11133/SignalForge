"""Part 4 Founder Acceptance Closure.

This layer closes the gaps found by independent adversarial review without
creating a second Market Truth engine.  Canonical Brain `strategic_track` remains
market/strategy classification authority.  This module adds Founder actionability,
relationship mapping, wedge expansion, synthetic provenance, benchmark batch
handling and compositional querying as read-only/advisory projections.
"""
from __future__ import annotations

import asyncio
import hashlib
import re
from collections import Counter
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping, Sequence

from processors.signalforge_opportunity_decision import (
    TRACKS,
    ask_signalforge as _legacy_ask,
    build_decision_item,
    build_opportunity_decision_portfolio,
    compare_decision_items,
    compare_theses,
)

ENGINE_VERSION = "signalforge-part4-founder-acceptance-closure-v1"
TRUTH_BOUNDARY = (
    "PART4_CLOSURE_ADDS_FOUNDER_ACTIONABILITY,_RELATIONSHIP_MAPPING,_WEDGE_EXPANSION,_SYNTHETIC_PROVENANCE,_"
    "BATCH_BENCHMARKING_AND_COMPOSITIONAL_QUERYING_WITH_ZERO_C01_C14_OR_MARKET_TRUTH_WRITE_AUTHORITY"
)
MARKET_TRUTH_WRITES = 0
PROVENANCE_TYPES = {"FOUNDER_HYPOTHESIS", "MODEL_HYPOTHESIS", "MULTI_MODEL_CONVERGENCE", "SYNTHETIC_HYPOTHESIS"}
FOUNDER_ACTION_ORDER = {
    "ACTION_NOW": 0,
    "VALIDATE_DISTRIBUTION": 1,
    "NARROW_WEDGE": 2,
    "INVESTIGATE": 3,
    "WATCH": 4,
    "PARK_OR_PARTNER": 5,
    "PARK": 6,
}


def _clean(v: Any, limit: int = 5000) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()[:limit]


def _upper(v: Any) -> str:
    return _clean(v, 200).upper()


def _mapping(v: Any) -> Mapping[str, Any]:
    return v if isinstance(v, Mapping) else {}


def _state(v: Any) -> str:
    x = _upper(v)
    return x or "UNKNOWN"


def _fa_dims(thesis: Mapping[str, Any]) -> Mapping[str, Any]:
    fa = _mapping(thesis.get("founder_addressability"))
    return _mapping(fa.get("dimensions"))


def _fa_state(thesis: Mapping[str, Any], name: str) -> str:
    return _state(_mapping(_fa_dims(thesis).get(name)).get("state"))


def _dim_state(thesis: Mapping[str, Any], name: str) -> str:
    return _state(_mapping(_mapping(thesis.get("dimensions")).get(name)).get("state"))


def _explicit_distribution(thesis: Mapping[str, Any]) -> Mapping[str, Any]:
    fa = _mapping(thesis.get("founder_addressability"))
    return _mapping(fa.get("distribution_fit") or thesis.get("distribution_fit"))


def _normalize_gate_value(raw: Any) -> str:
    if isinstance(raw, bool):
        return "YES" if raw else "NO"
    v = _upper(raw)
    return v if v else "UNKNOWN"


def distribution_fit_gate(thesis: Mapping[str, Any], trail: Mapping[str, Any], *, market_track: str | None = None, hard_kill: bool = False) -> dict[str, Any]:
    """Founder Distribution Fit gate.

    Market track is not reclassified here.  This answers a different question:
    even if the market thesis is CASH/BOTH/ZIP2, should this Founder act now?
    """
    fa = _mapping(thesis.get("founder_addressability"))
    explicit = _explicit_distribution(thesis)
    track = _upper(market_track or thesis.get("strategic_track")) or "PARK"
    wedge = _mapping(trail.get("revenue_wedge"))
    matrix = {
        "buyer_access": _fa_state(thesis, "buyer_access"),
        "legitimacy": _fa_state(thesis, "legitimacy"),
        "right_to_win": _fa_state(thesis, "right_to_win"),
        "distribution_leverage": _dim_state(thesis, "distribution_leverage"),
        "trust_burden": _normalize_gate_value(fa.get("trust_burden")),
        "learning_distance": _normalize_gate_value(fa.get("learning_distance")),
        "self_serve": _normalize_gate_value(explicit.get("self_serve")),
        "enterprise_procurement": _normalize_gate_value(explicit.get("enterprise_procurement")),
        "deep_integrations": _normalize_gate_value(explicit.get("deep_integrations")),
        "sensitive_data": _normalize_gate_value(explicit.get("sensitive_data")),
        "hardware": _normalize_gate_value(explicit.get("hardware")),
        "time_to_first_value": _normalize_gate_value(explicit.get("time_to_first_value")),
        "online_buyer": _normalize_gate_value(explicit.get("online_buyer")),
        "natural_distribution_channel": _normalize_gate_value(explicit.get("natural_distribution_channel")),
    }
    blockers: list[str] = []
    unknowns: list[str] = []
    for k in ("buyer_access", "legitimacy", "right_to_win"):
        if matrix[k] in {"REFUTED", "CONTRADICTED", "BLOCKED"}:
            blockers.append(f"{k}={matrix[k]}")
        elif matrix[k] in {"UNKNOWN", "INSUFFICIENT", "UNASSESSED", ""}:
            unknowns.append(k)
    if matrix["distribution_leverage"] in {"REFUTED", "CONTRADICTED", "BLOCKED"}:
        blockers.append(f"distribution_leverage={matrix['distribution_leverage']}")
    elif matrix["distribution_leverage"] in {"UNKNOWN", "INSUFFICIENT", "UNASSESSED"}:
        unknowns.append("distribution_leverage")
    if matrix["trust_burden"] in {"HIGH", "VERY_HIGH", "EXTREME"}:
        blockers.append(f"trust_burden={matrix['trust_burden']}")
    for k in ("enterprise_procurement", "deep_integrations", "sensitive_data", "hardware"):
        if matrix[k] in {"YES", "REQUIRED", "HIGH"}:
            blockers.append(f"{k}={matrix[k]}")
        elif matrix[k] == "UNKNOWN":
            unknowns.append(k)
    if matrix["time_to_first_value"] in {"LONG", "SLOW", "HIGH"}:
        blockers.append(f"time_to_first_value={matrix['time_to_first_value']}")
    elif matrix["time_to_first_value"] == "UNKNOWN":
        unknowns.append("time_to_first_value")
    for k in ("self_serve", "online_buyer", "natural_distribution_channel"):
        if matrix[k] == "NO":
            blockers.append(f"{k}=NO")
        elif matrix[k] == "UNKNOWN":
            unknowns.append(k)

    wedge_decision = _upper(wedge.get("decision")) or "NOT_NOW"
    spend = _upper(wedge.get("existing_spend")) or "UNKNOWN"
    reach = _upper(wedge.get("buyer_reachability")) or "UNKNOWN"
    hard_identity_block = any(x.startswith(("right_to_win=", "legitimacy=", "buyer_access=")) for x in blockers)
    high_friction = any(x.startswith(("trust_burden=", "enterprise_procurement=", "deep_integrations=", "sensitive_data=", "hardware=", "time_to_first_value=", "self_serve=", "online_buyer=", "natural_distribution_channel=", "distribution_leverage=")) for x in blockers)

    if hard_kill or track == "PARK":
        action = "PARK"
    elif hard_identity_block:
        action = "PARK_OR_PARTNER"
    elif high_friction:
        action = "VALIDATE_DISTRIBUTION"
    elif wedge_decision == "TRY_NOW" and spend in {"STRONG", "PARTIAL"} and reach in {"STRONG", "SUPPORTED", "PARTIAL", "MEDIUM"} and matrix["right_to_win"] in {"SUPPORTED", "KNOWN"}:
        action = "ACTION_NOW"
    elif wedge_decision == "KILL":
        action = "PARK"
    elif track == "ZIP2":
        action = "WATCH" if wedge_decision in {"NOT_NOW", "INVESTIGATE"} else "INVESTIGATE"
    elif unknowns:
        action = "INVESTIGATE"
    else:
        action = "NARROW_WEDGE"

    return {
        "market_track": market_track,
        "founder_action": action,
        "gate_pass": action == "ACTION_NOW",
        "blockers": blockers,
        "unknowns": sorted(set(unknowns)),
        "matrix": matrix,
        "reason": (
            "Market track and Founder actionability are separate. High trust/distribution friction can block ACTION_NOW without rewriting the market track."
        ),
        "market_truth_writes": 0,
        "truth_boundary": "FOUNDER_DISTRIBUTION_FIT_IS_AN_ACTIONABILITY_GATE_NOT_A_MARKET_TRACK_OR_C01_C14_WRITER",
    }


def structural_relationship_mapper(thesis: Mapping[str, Any], trail: Mapping[str, Any], *, root: Path | None = None) -> dict[str, Any]:
    """Map Problem ↔ Problem Lineage ↔ Sellable Wedge ↔ Structural Thesis ↔ Transition."""
    pl = _mapping(thesis.get("problem_lineage_snapshot"))
    tl = _mapping(thesis.get("transition_lineage_snapshot"))
    try:
        from processors.signalforge_brain_v2_engine import get_problem_lineage, get_transition_lineage
        if not pl and thesis.get("problem_lineage_id"):
            pl = _mapping(get_problem_lineage(str(thesis.get("problem_lineage_id")), root=root))
        if not tl and thesis.get("transition_lineage_id"):
            tl = _mapping(get_transition_lineage(str(thesis.get("transition_lineage_id")), root=root))
    except Exception:
        pass
    structural = _mapping(thesis.get("structural_thesis"))
    possible_wedge = _mapping(trail.get("possible_revenue_wedge"))
    wedge = _mapping(trail.get("revenue_wedge"))
    nodes = [
        {"type": "PROBLEM", "text": thesis.get("representative_problem") or trail.get("problem"), "authority": "PUBLISHED_THESIS_PROJECTION"},
        {"type": "PROBLEM_LINEAGE", "id": thesis.get("problem_lineage_id"), "text": pl.get("representative_problem") or pl.get("representative_title"), "state": pl.get("persistence_state"), "trajectory": pl.get("trajectory"), "authority": "BRAIN_DERIVED_LINEAGE" if pl else "UNKNOWN"},
        {"type": "SELLABLE_WEDGE", "text": possible_wedge.get("statement"), "state": possible_wedge.get("status"), "revenue_decision": wedge.get("decision"), "authority": "HYPOTHESIS" if possible_wedge else "UNKNOWN"},
        {"type": "STRUCTURAL_THESIS", "text": structural.get("transition") or structural.get("system_mismatch"), "payload": dict(structural), "authority": "BRAIN_STRUCTURAL_SYNTHESIS" if structural else "UNKNOWN"},
        {"type": "UNDERLYING_TRANSITION", "id": thesis.get("transition_lineage_id"), "text": tl.get("representative_text") or structural.get("transition"), "driver": tl.get("driver") or structural.get("transition_driver"), "state": tl.get("state"), "authority": "BRAIN_DERIVED_TRANSITION_LINEAGE" if tl else ("BRAIN_STRUCTURAL_SYNTHESIS" if structural.get("transition") else "UNKNOWN")},
    ]
    edges = [
        {"from": "PROBLEM", "to": "PROBLEM_LINEAGE", "relation": "MEMBER_OF_OR_REPRESENTED_BY"},
        {"from": "PROBLEM_LINEAGE", "to": "SELLABLE_WEDGE", "relation": "CURRENT_CAPTURE_HYPOTHESIS"},
        {"from": "SELLABLE_WEDGE", "to": "STRUCTURAL_THESIS", "relation": "MAY_VALIDATE_OR_UNLOCK"},
        {"from": "STRUCTURAL_THESIS", "to": "UNDERLYING_TRANSITION", "relation": "EXPLAINS_OR_DEPENDS_ON"},
    ]
    return {"nodes": nodes, "edges": edges, "market_truth_writes": 0, "truth_boundary": "RELATIONSHIP_MAPPER_ONLY_LINKS_EXISTING_BRAIN_AND_MONEY_TRAIL_OBJECTS;_MISSING_LINKS_REMAIN_UNKNOWN"}


def wedge_expansion_ladder(thesis: Mapping[str, Any], trail: Mapping[str, Any]) -> dict[str, Any]:
    possible = _mapping(trail.get("possible_revenue_wedge"))
    cheapest = _mapping(trail.get("cheapest_test"))
    exp = _mapping(_mapping(thesis.get("dimensions")).get("expansion_surface"))
    metrics = _mapping(exp.get("metrics"))
    candidates = metrics.get("candidate_wedges") or metrics.get("adjacent_workflows") or thesis.get("wedge_expansion_candidates") or []
    if not isinstance(candidates, list):
        candidates = []
    current = {
        "status": possible.get("status") or "UNKNOWN",
        "statement": possible.get("statement") or "No evidence-backed current wedge.",
        "authority": "MONEY_TRAIL_HYPOTHESIS_ONLY" if possible else "UNKNOWN",
    }
    evidence_to_collect = []
    if cheapest:
        evidence_to_collect.append({"type": "MARKET_TEST", "instruction": cheapest.get("instruction"), "sample": cheapest.get("sample"), "success": cheapest.get("success"), "failure": cheapest.get("failure")})
    if thesis.get("best_next_evidence"):
        evidence_to_collect.append({"type": "BRAIN_NEXT_EVIDENCE", "value": thesis.get("best_next_evidence")})
    next_rows = [{"wedge": _clean(x, 500), "authority": "EXPLICIT_EXPANSION_CANDIDATE", "state": _state(exp.get("state"))} for x in candidates if _clean(x, 500)][:8]
    return {
        "current_wedge": current,
        "evidence_to_collect": evidence_to_collect,
        "unlock_condition": (
            "Do not expand until the current wedge produces preregistered real buyer behavior and expansion_surface has evidence-backed adjacent workflow/value-pool support."
        ),
        "possible_next_wedges": next_rows,
        "next_wedge_status": "AVAILABLE" if next_rows else "UNKNOWN",
        "truth_boundary": "WEDGE_EXPANSION_NEVER_INVENTS_A_NEXT_WEDGE_WHEN_EXPANSION_EVIDENCE_OR_EXPLICIT_CANDIDATES_ARE_ABSENT",
        "market_truth_writes": 0,
    }


def decorate_item(thesis: Mapping[str, Any], trail: Mapping[str, Any], base_item: Mapping[str, Any], *, root: Path | None = None) -> dict[str, Any]:
    out = dict(base_item)
    market_track = str(out.get("current_track") or "PARK")
    gate = distribution_fit_gate(thesis, trail, market_track=market_track, hard_kill=bool(out.get("hard_kill")))
    out["market_track"] = market_track
    out["founder_actionability"] = gate
    out["founder_action"] = gate["founder_action"]
    out["validation_ladder"] = out.get("wedge_ladder")
    out["structural_relationship_mapper"] = structural_relationship_mapper(thesis, trail, root=root)
    out["wedge_expansion_ladder"] = wedge_expansion_ladder(thesis, trail)
    try:
        from processors.signalforge_market_learning_calibration import (
            calibration_adjustment_for_features,
            learning_features_from_projection,
        )
        learning_features = learning_features_from_projection(thesis, trail, out)
        out["market_learning_features"] = learning_features
        out["market_learning_calibration"] = calibration_adjustment_for_features(learning_features)
    except Exception as exc:
        out["market_learning_calibration"] = {
            "adjustment": "UNVALIDATED",
            "applied_to_ranking": False,
            "error": f"{type(exc).__name__}: {exc}",
            "market_truth_writes": 0,
        }
    extra_changes = [f"Distribution gate: {x}" for x in gate.get("blockers") or []]
    out["what_changes_rank"] = list(dict.fromkeys(list(out.get("what_changes_rank") or []) + extra_changes))
    out["market_truth_writes"] = 0
    out["closure_truth_boundary"] = TRUTH_BOUNDARY
    return out


def _action_rank(item: Mapping[str, Any]) -> tuple[Any, ...]:
    action = str(item.get("founder_action") or "PARK")
    calibration = _mapping(item.get("market_learning_calibration"))
    adjustment = str(calibration.get("adjustment") or "UNVALIDATED").upper()
    calibration_order = {"UPWEIGHT": 0, "UNVALIDATED": 1, "NEUTRAL": 1, "MIXED": 1, "DOWNWEIGHT": 2}
    return (FOUNDER_ACTION_ORDER.get(action, 99), calibration_order.get(adjustment, 1), int(item.get("rank") or 9999), str(item.get("title") or ""))


def rerank_closure(items: Sequence[Mapping[str, Any]], *, cash_need: str = "HIGH", long_term: str = "HIGH") -> dict[str, Any]:
    # Keep Part 4's transparent lexicographic market ranking as an input, then put
    # the explicit Founder actionability gate in front of it.
    base = compare_decision_items(items, cash_need=cash_need, long_term=long_term)
    rows = [dict(x) for x in base.get("items") or []]
    rows.sort(key=_action_rank)
    for i, row in enumerate(rows, 1):
        row["founder_rank"] = i
        row["rank_explanation_closure"] = {
            "founder_action": row.get("founder_action"),
            "market_learning_adjustment": _mapping(row.get("market_learning_calibration")).get("adjustment") or "UNVALIDATED",
            "market_rank_before_actionability_gate": row.get("rank"),
            "note": "Founder actionability gate first; sufficiently powered prospective Part 6 calibration is only a transparent tie-breaker; then the existing market/strategy ranking. No opaque score.",
        }
    return {
        **base,
        "engine_version": ENGINE_VERSION,
        "items": rows,
        "top": rows[0] if rows else None,
        "ranking_method": "FOUNDER_ACTIONABILITY_GATE_THEN_VALIDATED_MARKET_LEARNING_TIEBREAKER_THEN_PART4_TRANSPARENT_LEXICOGRAPHIC_RULES",
        "market_truth_writes": 0,
        "truth_boundary": TRUTH_BOUNDARY,
    }


def resource_allocation_closure(compare_result: Mapping[str, Any], *, weekly_hours: float = 10.0) -> dict[str, Any]:
    hours = max(1.0, min(float(weekly_hours or 10.0), 80.0))
    rows = list(compare_result.get("items") or [])
    eligible = [x for x in rows if x.get("founder_action") in {"ACTION_NOW", "VALIDATE_DISTRIBUTION", "NARROW_WEDGE", "WATCH"} and not x.get("hard_kill")][:5]
    weights = {"ACTION_NOW": 4.0, "VALIDATE_DISTRIBUTION": 2.5, "NARROW_WEDGE": 2.0, "WATCH": 0.5}
    total = sum(weights.get(str(x.get("founder_action")), 1.0) for x in eligible) or 1.0
    allocations = []
    used = 0.0
    for idx, x in enumerate(eligible):
        if idx == len(eligible) - 1:
            h = max(0.0, round((hours - used) * 2) / 2)
        else:
            h = round((hours * weights.get(str(x.get("founder_action")), 1.0) / total) * 2) / 2
            used += h
        allocations.append({
            "thesis_id": x.get("thesis_id"), "title": x.get("title"), "hours": h,
            "bucket": x.get("founder_action"),
            "why": "Allocate by Founder actionability, not market track alone.",
            "what_changes_this": list(x.get("what_changes_rank") or [])[:3],
        })
    return {"weekly_hours": hours, "allocations": allocations, "allocated_hours": sum(float(x["hours"]) for x in allocations), "advisory_only": True, "market_truth_writes": 0, "truth_boundary": "RESOURCE_ALLOCATION_USES_FOUNDER_ACTIONABILITY_AND_NEVER_AUTO_EXECUTES"}


def _predicate_specs(q: str) -> list[tuple[str, Callable[[Mapping[str, Any]], bool]]]:
    low = _clean(q).lower()
    preds: list[tuple[str, Callable[[Mapping[str, Any]], bool]]] = []
    if "existing spend" in low or "既存支出" in low or "有 spend" in low:
        preds.append(("EXISTING_SPEND", lambda x: str(x.get("existing_spend") or "").upper() in {"STRONG", "PARTIAL"}))
    if "paid dissatisfaction" in low or "付錢" in low and ("不滿" in low or "還是" in low):
        preds.append(("PAID_DISSATISFACTION", lambda x: int(x.get("paid_dissatisfaction_count") or 0) > 0))
    if "reachable buyer" in low or "buyer reachable" in low or "碰得到" in low or "可觸及" in low:
        preds.append(("REACHABLE_BUYER", lambda x: str(_mapping(_mapping(x.get("founder_fit")).get("dimensions")).get("buyer_access", {}).get("state") or "").upper() in {"SUPPORTED", "KNOWN"}))
    if "action now" in low or "現在做" in low:
        preds.append(("FOUNDER_ACTION_NOW", lambda x: x.get("founder_action") == "ACTION_NOW"))
    for track in TRACKS:
        if track.lower() in low:
            preds.append((f"TRACK_{track}", lambda x, t=track: (x.get("market_track") or x.get("current_track")) == t))
    if "right-to-win" in low or "right to win" in low:
        preds.append(("RIGHT_TO_WIN", lambda x: str(_mapping(x.get("founder_fit")).get("state") or "").upper() in {"SUPPORTED", "KNOWN"}))
    return preds


def ask_signalforge_composite(q: str, compare_result: Mapping[str, Any]) -> dict[str, Any]:
    rows = list(compare_result.get("items") or [])
    preds = _predicate_specs(q)
    if not preds:
        legacy = _legacy_ask(q, compare_result)
        return {**legacy, "engine_version": ENGINE_VERSION, "composite": False, "market_truth_writes": 0, "truth_boundary": TRUTH_BOUNDARY}
    matches = [x for x in rows if all(fn(x) for _, fn in preds)]
    return {
        "engine_version": ENGINE_VERSION, "status": "PASS", "query": _clean(q), "intent": "COMPOSITE_FILTER",
        "predicates": [name for name, _ in preds], "composite": True,
        "answer": f"Matched {len(matches)} direction(s) satisfying ALL requested predicates: {', '.join(name for name,_ in preds)}.",
        "matches": matches, "market_truth_writes": 0,
        "truth_boundary": "ASK_COMPOSITE_FILTERS_EXISTING_PROJECTIONS_WITH_LOGICAL_AND;_IT_DOES_NOT_CREATE_FACTS",
    }


def _tokens(text: str) -> set[str]:
    return {x for x in re.findall(r"[a-z0-9\u4e00-\u9fff]+", text.lower()) if len(x) >= 2}


def _fingerprint(title: str, description: str) -> str:
    toks = sorted(_tokens(f"{title} {description}"))
    return hashlib.sha256(" ".join(toks).encode("utf-8")).hexdigest()[:20]


def normalize_synthetic_batch(hypotheses: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for idx, raw in enumerate(list(hypotheses)[:60]):
        title = _clean(raw.get("title"), 400)
        description = _clean(raw.get("description"), 2000)
        if len(title) < 2:
            continue
        ptype = _upper(raw.get("provenance_type") or "SYNTHETIC_HYPOTHESIS")
        if ptype not in PROVENANCE_TYPES:
            ptype = "SYNTHETIC_HYPOTHESIS"
        fp = _fingerprint(title, description)
        row = groups.setdefault(fp, {
            "hypothesis_id": f"bh_{fp}", "title": title, "description": description,
            "contributors": [], "synthetic_contributor_count": 0, "independent_market_recurrence_count": 0,
            "market_authority": "NONE", "truth_status": "SYNTHETIC_UNVALIDATED", "market_truth_writes": 0,
        })
        contributor = {
            "provenance_type": ptype, "source_model": _clean(raw.get("source_model"), 120) or None,
            "source_ref": _clean(raw.get("source_ref"), 500) or f"batch:{idx}",
        }
        if contributor not in row["contributors"]:
            row["contributors"].append(contributor)
        row["synthetic_contributor_count"] = len(row["contributors"])
        if len({(x.get("source_model"), x.get("source_ref")) for x in row["contributors"]}) > 1:
            row["provenance_summary"] = "MULTI_MODEL_OR_MULTI_SOURCE_SYNTHETIC_CONVERGENCE"
        else:
            row["provenance_summary"] = ptype
    return list(groups.values())


def _lineage_candidate(h: Mapping[str, Any], portfolio_items: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    ht = _tokens(f"{h.get('title','')} {h.get('description','')}")
    best = None
    for row in portfolio_items:
        rt = _tokens(f"{row.get('representative_title','')} {row.get('representative_problem','')} {row.get('title','')} {row.get('problem','')}")
        if not ht or not rt:
            continue
        score = len(ht & rt) / max(1, len(ht | rt))
        if best is None or score > best[0]:
            best = (score, row)
    if best and best[0] >= 0.18:
        return {"thesis_id": best[1].get("thesis_id"), "title": best[1].get("representative_title") or best[1].get("title"), "lexical_similarity": round(best[0], 4), "authority": "SYNTHETIC_LINEAGE_CANDIDATE_ONLY"}
    return None


async def benchmark_batch_ingest(
    hypotheses: Sequence[Mapping[str, Any]], *, run_probe: bool = True,
    probe_runner: Callable[..., Awaitable[Mapping[str, Any]]] | None = None,
    portfolio_items: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    rows = normalize_synthetic_batch(hypotheses)
    if portfolio_items is None:
        try:
            from processors.signalforge_brain_v2_engine import get_brain_v2_portfolio
            portfolio_items = list(dict(get_brain_v2_portfolio()).get("portfolio") or [])
        except Exception:
            portfolio_items = []
    if probe_runner is None:
        from processors.signalforge_founder_idea_loop import probe_founder_idea
        probe_runner = probe_founder_idea
    sem = asyncio.Semaphore(4)

    async def one(row: dict[str, Any]) -> dict[str, Any]:
        lineage = _lineage_candidate(row, portfolio_items or [])
        probe = None
        if run_probe:
            async with sem:
                try:
                    probe = dict(await probe_runner(title=row["title"], description=row.get("description") or ""))
                except Exception as exc:
                    probe = {"status": "PROBE_FAILED_VISIBLE", "error": f"{type(exc).__name__}: {exc}", "market_truth_writes": 0}
        route = "EXISTING_THESIS_REVIEW" if lineage else ("PROBE_REVIEW" if run_probe else "PROBE_REQUIRED")
        return {**row, "probe": probe, "possible_lineage_match": lineage, "route": route, "independent_market_recurrence_count": 0, "market_authority": "NONE", "market_truth_writes": 0}

    out = await asyncio.gather(*(one(dict(x)) for x in rows))
    return {
        "engine_version": ENGINE_VERSION, "status": "PASS", "input_count": min(len(hypotheses), 60), "deduped_count": len(out),
        "items": out, "synthetic_convergence_counts_as_market_recurrence": False,
        "market_truth_writes": 0,
        "truth_boundary": "RAW_BENCHMARK_HYPOTHESES_RETAIN_PROVENANCE;_SYNTHETIC_CONVERGENCE_NEVER_COUNTS_AS_INDEPENDENT_MARKET_RECURRENCE",
    }


def founder_hypothesis_decision_projection(row: Mapping[str, Any]) -> dict[str, Any]:
    """Project a durable Founder hypothesis into Part 4 without market promotion.

    This is deliberately not a Brain thesis and is excluded from market-track
    ranking.  It exists so Part 1 does not drop the Founder idea at the Part 4
    boundary.
    """
    probe = _mapping(row.get("last_probe"))
    fast = _mapping(probe.get("fast_probe"))
    published = _mapping(probe.get("published_money_trail"))
    binding = _mapping(published.get("published_thesis_match"))
    frontier = _mapping(probe.get("decision_frontier"))
    mode = _upper(frontier.get("next_mode"))
    if _upper(binding.get("status")) == "MATCHED":
        route = "EXISTING_THESIS_REVIEW"
        action = "INVESTIGATE"
    elif mode == "PARK_FOUNDER_HYPOTHESIS":
        route = "PARK"
        action = "PARK"
    elif mode == "TARGETED_DOMAIN_RESEARCH":
        route = "RESEARCH"
        action = "INVESTIGATE"
    elif int(fast.get("problem_discussions") or 0) > 0 or int(fast.get("firsthand_pain") or 0) > 0:
        route = "PROBE_REVIEW"
        action = "INVESTIGATE"
    else:
        route = "RESEARCH"
        action = "INVESTIGATE"

    spend = _mapping(published.get("current_spend"))
    pd = _mapping(published.get("paid_dissatisfaction"))
    hid = str(row.get("hypothesis_id") or "")
    return {
        "thesis_id": hid,
        "hypothesis_id": hid,
        "title": row.get("title"),
        "problem": row.get("description") or row.get("title"),
        "source_kind": "FOUNDER_HYPOTHESIS",
        "provenance_type": "FOUNDER_HYPOTHESIS",
        "market_authority": "NONE",
        "independent_market_recurrence_count": 0,
        "rankable_market_thesis": False,
        "market_track": "UNVALIDATED",
        "current_track": "UNVALIDATED",
        "decision_route": route,
        "founder_action": action,
        "founder_rank": None,
        "rank": None,
        "revenue_wedge_decision": "NOT_NOW",
        "existing_spend": str(spend.get("status") or "UNKNOWN").upper() if _upper(binding.get("status")) == "MATCHED" else "UNKNOWN",
        "paid_dissatisfaction_count": int(pd.get("count") or 0) if _upper(binding.get("status")) == "MATCHED" else 0,
        "paid_dissatisfaction_status": pd.get("status") if _upper(binding.get("status")) == "MATCHED" else "UNKNOWN",
        "founder_fit": {"state": "UNASSESSED", "dimensions": {}},
        "founder_actionability": {"founder_action": action, "blockers": [], "unknowns": ["published_market_evidence"], "gate_pass": False},
        "zip2_readiness": "UNASSESSED",
        "rank_explanation": {"band": "UNVALIDATED_FOUNDER_HYPOTHESIS", "track": "NO_MARKET_TRACK", "revenue_wedge": "NOT_NOW", "existing_spend": "UNKNOWN", "founder_fit": "UNASSESSED"},
        "what_changes_rank": [frontier.get("advance_if")] if frontier.get("advance_if") else [],
        "do_not_research": [{"topic": x, "reason": "Founder Decision Frontier"} for x in (frontier.get("do_not_research") or [])],
        "validation_ladder": {"stages": []},
        "wedge_ladder": {"stages": []},
        "structural_mapper": {"dimensions": []},
        "structural_relationship_mapper": {"nodes": [{"type": "FOUNDER_HYPOTHESIS", "text": row.get("title"), "authority": "FOUNDER_REASONING_ONLY"}]},
        "wedge_expansion_ladder": {"current_wedge": {"status": "UNKNOWN", "statement": "No validated wedge yet."}, "possible_next_wedges": [], "unlock_condition": "Validate the hypothesis before expansion."},
        "published_thesis_match": dict(binding),
        "fast_probe": dict(fast),
        "decision_frontier": dict(frontier),
        "market_truth_writes": 0,
        "truth_boundary": "FOUNDER_HYPOTHESIS_IS_VISIBLE_IN_PART4_WITH_ZERO_MARKET_AUTHORITY_AND_ZERO_MARKET_RECURRENCE",
    }


async def build_opportunity_decision_portfolio_closure(*, limit: int = 30, weekly_hours: float = 10.0, cash_need: str = "HIGH", long_term: str = "HIGH", root: Path | None = None) -> dict[str, Any]:
    from processors.signalforge_brain_v2_engine import get_brain_v2_portfolio
    from processors.signalforge_money_trail import build_money_trail_for_thesis
    from processors.signalforge_founder_hypothesis_registry import list_founder_hypotheses
    portfolio = dict(get_brain_v2_portfolio(root=root)) if root is not None else dict(get_brain_v2_portfolio())
    theses = [dict(x) for x in (portfolio.get("portfolio") or []) if isinstance(x, Mapping)][:max(1, min(int(limit or 30), 100))]
    decorated = []
    for thesis in theses:
        try:
            trail = await build_money_trail_for_thesis(thesis)
        except Exception as exc:
            trail = {"thesis_id": thesis.get("thesis_id"), "revenue_wedge": {"decision": "NOT_NOW", "existing_spend": "UNKNOWN", "buyer_reachability": "UNKNOWN"}, "paid_dissatisfaction": {"count": 0}, "status": "MONEY_TRAIL_UNAVAILABLE_NON_BLOCKING", "error": f"{type(exc).__name__}: {exc}"}
        decorated.append(decorate_item(thesis, trail, build_decision_item(thesis, trail), root=root))
    result = rerank_closure(decorated, cash_need=cash_need, long_term=long_term)
    market_items = list(result.get("items") or [])
    try:
        founder_rows = list_founder_hypotheses(limit=max(10, min(int(limit or 30), 100)), root=root)
        founder_items = [founder_hypothesis_decision_projection(x) for x in founder_rows]
    except Exception as exc:
        founder_items = []
        result["founder_hypothesis_handoff_error"] = f"{type(exc).__name__}: {exc}"
    result["items"] = market_items + founder_items
    result["founder_hypotheses"] = founder_items
    result["founder_hypothesis_count"] = len(founder_items)
    result["track_counts"] = {k: int(Counter(str(x.get("market_track") or "PARK") for x in market_items).get(k, 0)) for k in TRACKS}
    result["founder_action_counts"] = dict(Counter(str(x.get("founder_action") or "UNKNOWN") for x in result["items"]))
    result["resource_allocation"] = resource_allocation_closure({**result, "items": market_items}, weekly_hours=weekly_hours)
    result["market_calibration"] = portfolio.get("market_calibration") or {}
    result["founder_hypothesis_handoff_truth_boundary"] = "FOUNDER_HYPOTHESES_ARE_VISIBLE_BUT_EXCLUDED_FROM_MARKET_TRACK_COUNTS_AND_MARKET_RANKING"
    return result


async def compare_theses_closure(thesis_ids: Sequence[str], *, weekly_hours: float = 10.0, cash_need: str = "HIGH", long_term: str = "HIGH") -> dict[str, Any]:
    wanted = {_clean(x, 240) for x in thesis_ids if _clean(x, 240)}
    full = await build_opportunity_decision_portfolio_closure(limit=100, weekly_hours=weekly_hours, cash_need=cash_need, long_term=long_term)
    rows = [x for x in full.get("items") or [] if _clean(x.get("thesis_id"), 240) in wanted]
    market_rows = [x for x in rows if x.get("source_kind") != "FOUNDER_HYPOTHESIS"]
    founder_rows = [x for x in rows if x.get("source_kind") == "FOUNDER_HYPOTHESIS"]
    result = rerank_closure(market_rows, cash_need=cash_need, long_term=long_term) if market_rows else {"engine_version": ENGINE_VERSION, "status": "PASS", "items": [], "top": None, "market_truth_writes": 0}
    result["items"] = list(result.get("items") or []) + founder_rows
    result["founder_hypotheses"] = founder_rows
    result["resource_allocation"] = resource_allocation_closure({**result, "items": list(result.get("items") or [])[:len(market_rows)]}, weekly_hours=weekly_hours) if market_rows else {"weekly_hours": weekly_hours, "allocations": [], "allocated_hours": 0, "advisory_only": True, "market_truth_writes": 0}
    result["requested_thesis_ids"] = sorted(wanted)
    result["missing_thesis_ids"] = sorted(wanted - {_clean(x.get("thesis_id"), 240) for x in rows})
    return result


async def ask_current_signalforge_closure(q: str, *, weekly_hours: float = 10.0, cash_need: str = "HIGH", long_term: str = "HIGH") -> dict[str, Any]:
    portfolio = await build_opportunity_decision_portfolio_closure(limit=50, weekly_hours=weekly_hours, cash_need=cash_need, long_term=long_term)
    return ask_signalforge_composite(q, portfolio)
