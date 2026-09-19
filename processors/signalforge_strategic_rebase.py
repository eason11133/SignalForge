"""SignalForge Strategic Search & Founder Addressability Rebase.

This module does *not* own market truth. It translates mature opportunity-discovery
constructs into deterministic, evidence-bounded planning metadata on top of Brain v2.

Authority boundaries:
- Radar C01-C14 remain the sole atomic market-truth owner.
- Brain v2 remains the structural synthesis owner.
- This module may classify Founder strategy / next-action routing only.
- Borrowed research frameworks are design priors, never evidence for a live thesis.
- Missing Founder/domain evidence stays UNKNOWN/INSUFFICIENT; AI buildability never
  auto-promotes domain knowledge, buyer access, legitimacy, or right-to-win.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

from processors.signalforge_brain_v2_contracts import clean, dim_state, normalize_state

ENGINE_VERSION = "signalforge-strategic-search-founder-addressability-rebase-r1"
PROFILE_PATH = Path("config/company_capability_profile.json")

STRATEGIC_TRACKS = {"ZIP2_STRUCTURAL", "FAST_VALIDATION", "BOTH", "NEITHER"}
ADDRESSABILITY_STATES = {"SUPPORTED", "PARTIAL", "INSUFFICIENT", "UNKNOWN", "REFUTED"}

# These are research/design priors only. They are not live-market evidence.
BORROWED_FRAMEWORKS = {
    "ENTREPRENEURIAL_ALERTNESS": "Scanning/search -> association/connection -> evaluation/judgment.",
    "WINDOWS_OF_OPPORTUNITY": "Technology, demand, institution/regulation windows can create entrant openings.",
    "LEAD_USER": "Ahead-of-trend users with high benefit expectation and revealed workaround behavior.",
    "THIRD_TO_FIRST_PERSON": "A market opportunity can exist without being addressable by this Founder.",
    "MARKET_CHOICE_SET": "Generate a bounded set of plausible wedges before committing to one market path.",
    "EFFECTUATION": "Use means at hand and affordable-loss logic under high uncertainty.",
    "BRICOLAGE": "Recombine resources already at hand for a low-cost entry path.",
    "LEGITIMACY": "Provider credibility/trust is a distinct entry constraint, not technical buildability.",
    "LEAN_VALIDATION": "Once a thesis is concrete enough, falsification by market action can dominate more desk research.",
}

# Conservative domain families. These are routing heuristics, not assertions that the
# Founder is an expert in the underlying industry.
DOMAIN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("REGULATED_HIGH_TRUST", re.compile(r"\b(healthcare|medical|patient|clinical|diagnos|pharma|bank|banking|financial|insurance|legal|law firm|regulated|compliance|hipaa|pci|critical infrastructure|aviation safety)\w*\b", re.I)),
    ("PHYSICAL_SPECIALIST", re.compile(r"\b(semiconductor|fab|manufactur|factory|industrial|chemical|mechanical|warehouse|construction|hardware install|robotics|aerospace|aircraft)\w*\b", re.I)),
    ("DEVTOOLS_AI", re.compile(r"\b(developer|coding|code review|ide|api|sdk|llm|ai agent|coding agent|claude code|github|software team|engineering team)\w*\b", re.I)),
    ("DATA_EVIDENCE_RESEARCH", re.compile(r"\b(evidence|research workflow|data pipeline|scrap|crawler|provenance|verification|audit trail|intelligence|information retrieval)\w*\b", re.I)),
    ("WEB_PRODUCT", re.compile(r"\b(web app|saas|dashboard|workflow software|automation|online tool|browser|self[- ]serve|productivity software)\w*\b", re.I)),
    ("ENTERPRISE_SOFTWARE", re.compile(r"\b(enterprise|crm|procurement|salesforce|erp|large company|b2b)\w*\b", re.I)),
    ("SMB_DIGITAL_OPS", re.compile(r"\b(small business|smb|local business|agency|freelancer|back office|operations|manual workflow)\w*\b", re.I)),
)

LOW_TRUST_PATTERNS = re.compile(r"\b(self[- ]serve|developer tool|devtool|plugin|extension|utility|workflow tool|small team|creator|freelancer)\w*\b", re.I)
HIGH_TRUST_PATTERNS = re.compile(r"\b(enterprise core|security|production infrastructure|mission critical|procurement|governance|audit|regulated|healthcare|finance|legal)\w*\b", re.I)


def _load_profile(root: Path | None = None) -> dict[str, Any]:
    root = (root or Path.cwd()).resolve()
    path = root / PROFILE_PATH
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _profile_strengths(profile: Mapping[str, Any]) -> set[str]:
    return {
        clean(row.get("capability")).lower()
        for row in (profile.get("strengths") or [])
        if isinstance(row, Mapping) and clean(row.get("level")).lower() == "strong"
    }


def _profile_gap_names(profile: Mapping[str, Any]) -> set[str]:
    return {
        clean(row.get("capability")).lower()
        for row in (profile.get("known_gaps") or [])
        if isinstance(row, Mapping)
    }


def _text_for_thesis(thesis: Mapping[str, Any]) -> str:
    structural = thesis.get("structural_thesis") if isinstance(thesis.get("structural_thesis"), Mapping) else {}
    parts = [
        thesis.get("representative_title"),
        thesis.get("representative_problem"),
        structural.get("problem"),
        structural.get("transition"),
        structural.get("wedge_type"),
        thesis.get("opportunity_class"),
    ]
    return " ".join(clean(x) for x in parts if clean(x))


def classify_domain(text: str) -> list[str]:
    found = [name for name, pat in DOMAIN_PATTERNS if pat.search(text)]
    return found or ["UNKNOWN"]


def _state_row(state: str, *, basis: str, evidence: list[str] | None = None, metrics: Mapping[str, Any] | None = None) -> dict[str, Any]:
    normalized = normalize_state(state)
    if normalized not in ADDRESSABILITY_STATES:
        normalized = "UNKNOWN"
    return {
        "state": normalized,
        "basis": basis,
        "evidence_refs": list(evidence or [])[:24],
        "metrics": dict(metrics or {}),
        "truth_owner": "FOUNDER_COMPANY_TRUTH_DERIVED_NO_MARKET_AUTHORITY",
    }


def _profile_support(profile: Mapping[str, Any]) -> dict[str, bool]:
    strengths = _profile_strengths(profile)
    return {
        "ai": any("ai" in x or "api" in x for x in strengths),
        "backend": any("python backend" in x for x in strengths),
        "web": any("web product" in x for x in strengths),
        "data": any("data scraping" in x or "evidence pipeline" in x for x in strengths),
        "rapid_mvp": any("rapid ai-assisted" in x for x in strengths),
    }


def _trust_burden(domains: list[str], text: str) -> str:
    if "REGULATED_HIGH_TRUST" in domains:
        return "EXTREME"
    if "PHYSICAL_SPECIALIST" in domains:
        return "HIGH"
    if HIGH_TRUST_PATTERNS.search(text):
        return "HIGH"
    if LOW_TRUST_PATTERNS.search(text) or "DEVTOOLS_AI" in domains or "WEB_PRODUCT" in domains:
        return "LOW_TO_MEDIUM"
    if "ENTERPRISE_SOFTWARE" in domains:
        return "HIGH"
    return "UNKNOWN"


def assess_founder_addressability(
    thesis: Mapping[str, Any],
    *,
    company_profile: Mapping[str, Any] | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Translate objective opportunity truth into Founder-specific addressability.

    This function intentionally refuses to infer domain expertise from generic AI/software
    implementation capability. A technical C09 SUPPORTED state can prove task execution,
    but not buyer access, industry judgment, legitimacy, or trust.
    """
    profile = dict(company_profile or _load_profile(root))
    support = _profile_support(profile)
    text = _text_for_thesis(thesis)
    domains = classify_domain(text)
    claims = thesis.get("claim_states") if isinstance(thesis.get("claim_states"), Mapping) else {}
    dims = thesis.get("dimensions") if isinstance(thesis.get("dimensions"), Mapping) else {}
    c09 = normalize_state(claims.get("C09") or dim_state(dims, "captureability"))
    c10 = normalize_state(claims.get("C10") or dim_state(dims, "distribution_leverage"))
    trust = _trust_burden(domains, text)

    software_adjacent = any(x in domains for x in ("DEVTOOLS_AI", "DATA_EVIDENCE_RESEARCH", "WEB_PRODUCT", "SMB_DIGITAL_OPS"))
    specialist = any(x in domains for x in ("REGULATED_HIGH_TRUST", "PHYSICAL_SPECIALIST"))
    enterprise = "ENTERPRISE_SOFTWARE" in domains

    capability_state = "UNKNOWN"
    if c09 == "REFUTED":
        capability_state = "REFUTED"
    elif software_adjacent and all((support["backend"], support["rapid_mvp"])):
        capability_state = "SUPPORTED" if ("DEVTOOLS_AI" in domains and support["ai"]) or ("DATA_EVIDENCE_RESEARCH" in domains and support["data"]) else "PARTIAL"
    elif specialist:
        capability_state = "INSUFFICIENT"
    elif c09 == "SUPPORTED":
        capability_state = "PARTIAL"

    # Domain judgment is deliberately stricter than software capability.
    if "DATA_EVIDENCE_RESEARCH" in domains and support["data"]:
        domain_state = "PARTIAL"
    elif "DEVTOOLS_AI" in domains and support["ai"] and support["backend"]:
        domain_state = "PARTIAL"
    elif "WEB_PRODUCT" in domains and support["web"]:
        domain_state = "PARTIAL"
    elif specialist:
        domain_state = "INSUFFICIENT"
    else:
        domain_state = "UNKNOWN"

    # C10 is distribution feasibility, not proof of an owned relationship. It can only
    # advance buyer access to PARTIAL unless explicit company-access evidence is added later.
    buyer_access_state = "PARTIAL" if c10 == "SUPPORTED" else ("INSUFFICIENT" if c10 == "REFUTED" else "UNKNOWN")

    if trust == "EXTREME" and domain_state not in {"SUPPORTED"}:
        legitimacy_state = "REFUTED"
    elif trust == "HIGH":
        legitimacy_state = "UNKNOWN"
    elif software_adjacent and capability_state in {"SUPPORTED", "PARTIAL"}:
        legitimacy_state = "PARTIAL"
    else:
        legitimacy_state = "UNKNOWN"

    if trust == "EXTREME":
        learning_distance = "PROHIBITIVE_NOW"
    elif specialist:
        learning_distance = "DISTANT"
    elif software_adjacent and capability_state == "SUPPORTED":
        learning_distance = "CORE_OR_ADJACENT"
    elif software_adjacent or enterprise:
        learning_distance = "ADJACENT_OR_BRIDGEABLE"
    else:
        learning_distance = "UNKNOWN"

    if legitimacy_state == "REFUTED":
        bridge_state = "INSUFFICIENT"
    elif domain_state in {"INSUFFICIENT", "UNKNOWN"} or buyer_access_state == "UNKNOWN" or legitimacy_state == "UNKNOWN":
        bridge_state = "PARTIAL" if trust != "EXTREME" else "INSUFFICIENT"
    else:
        bridge_state = "SUPPORTED"

    if capability_state == "REFUTED" or legitimacy_state == "REFUTED" or learning_distance == "PROHIBITIVE_NOW":
        right_to_win = "REFUTED"
    elif capability_state == "SUPPORTED" and domain_state in {"SUPPORTED", "PARTIAL"} and buyer_access_state == "PARTIAL" and legitimacy_state == "PARTIAL":
        right_to_win = "PARTIAL"
    elif capability_state in {"SUPPORTED", "PARTIAL"} and domain_state not in {"REFUTED"}:
        right_to_win = "INSUFFICIENT"
    else:
        right_to_win = "UNKNOWN"

    blockers: list[str] = []
    if capability_state not in {"SUPPORTED", "PARTIAL"}: blockers.append("TASK_CAPABILITY")
    if domain_state not in {"SUPPORTED", "PARTIAL"}: blockers.append("DOMAIN_KNOWLEDGE")
    if buyer_access_state not in {"SUPPORTED", "PARTIAL"}: blockers.append("BUYER_ACCESS")
    if legitimacy_state not in {"SUPPORTED", "PARTIAL"}: blockers.append("LEGITIMACY")
    if learning_distance in {"DISTANT", "PROHIBITIVE_NOW"}: blockers.append("LEARNING_DISTANCE")

    return {
        "engine_version": ENGINE_VERSION,
        "third_person_opportunity_state": clean(thesis.get("classification")) or "UNKNOWN",
        "first_person_addressability_state": right_to_win,
        "domains": domains,
        "trust_burden": trust,
        "learning_distance": learning_distance,
        "dimensions": {
            "task_capability": _state_row(capability_state, basis="C09 plus explicit company capability profile; AI buildability cannot prove domain expertise.", evidence=[str(PROFILE_PATH)] if profile else [], metrics={"C09": c09}),
            "domain_knowledge": _state_row(domain_state, basis="Only adjacency to explicitly evidenced company work may reduce domain distance; generic internet research is not expertise.", evidence=[str(PROFILE_PATH)] if profile else []),
            "buyer_access": _state_row(buyer_access_state, basis="C10 may show a feasible channel but does not prove an owned buyer relationship; no distribution is assumed.", metrics={"C10": c10}),
            "legitimacy": _state_row(legitimacy_state, basis="Provider credibility is separate from implementation skill and becomes a hard blocker in high-trust regulated domains."),
            "bridgeability": _state_row(bridge_state, basis="Unknown gaps may be bridgeable by a partner, customer co-design, or bounded learning path; bridgeability never self-promotes the missing truth."),
            "right_to_win": _state_row(right_to_win, basis="First-person opportunity gate across capability, domain judgment, buyer access, legitimacy, and trust burden."),
        },
        "blocking_unknowns": blockers,
        "hard_blocked": right_to_win == "REFUTED",
        "company_profile_version": profile.get("version") if isinstance(profile, Mapping) else None,
        "truth_boundary": "Founder addressability is company-specific derived truth. It cannot change objective Radar market claims. AI execution capacity never substitutes for domain knowledge, buyer access, legitimacy, or trust.",
    }


def assess_fast_validation(thesis: Mapping[str, Any], addressability: Mapping[str, Any]) -> dict[str, Any]:
    dims = thesis.get("dimensions") if isinstance(thesis.get("dimensions"), Mapping) else {}
    p = dim_state(dims, "problem_persistence")
    e = dim_state(dims, "economic_materiality")
    b = dim_state(dims, "buyer_formation")
    g = dim_state(dims, "gap_durability")
    w = dim_state(dims, "workaround_intensity")
    d = dim_state(dims, "distribution_leverage")
    c = dim_state(dims, "captureability")
    right = normalize_state(((addressability.get("dimensions") or {}).get("right_to_win") or {}).get("state"))

    if any(x == "REFUTED" for x in (p, e, b, g, c, right)):
        state = "BLOCKED"
    elif all(x == "SUPPORTED" for x in (p, e, b, g)) and right in {"SUPPORTED", "PARTIAL"} and d in {"SUPPORTED", "PARTIAL"}:
        state = "READY"
    elif p in {"SUPPORTED", "PARTIAL"} and e in {"SUPPORTED", "PARTIAL"} and b in {"SUPPORTED", "PARTIAL"} and g != "REFUTED" and right != "REFUTED":
        state = "RESEARCH_READY"
    else:
        state = "NOT_READY"

    revealed_behavior = "HIGH" if w == "SUPPORTED" else ("MEDIUM" if w in {"PARTIAL", "INSUFFICIENT"} else "UNKNOWN")
    market_action_candidate = bool(state in {"READY", "RESEARCH_READY"} and p == "SUPPORTED" and b == "SUPPORTED" and g == "SUPPORTED" and right in {"SUPPORTED", "PARTIAL"})
    return {
        "state": state,
        "revealed_behavior": revealed_behavior,
        "market_action_candidate": market_action_candidate,
        "falsification_cost_class": "LOW_OR_BOUNDED" if market_action_candidate else "UNKNOWN",
        "truth_boundary": "Fast-validation readiness is a routing decision, not proof of demand or willingness-to-pay.",
    }


def strategic_track(thesis: Mapping[str, Any], fast: Mapping[str, Any]) -> str:
    zip2 = clean(thesis.get("zip2_readiness")).upper()
    zip2_active = zip2 in {"ZIP2_HIGH_CONVICTION", "ZIP2_CANDIDATE"}
    fast_active = clean(fast.get("state")).upper() in {"READY", "RESEARCH_READY"}
    if zip2_active and fast_active:
        return "BOTH"
    if zip2_active:
        return "ZIP2_STRUCTURAL"
    if fast_active:
        return "FAST_VALIDATION"
    return "NEITHER"


def choose_best_next_action(thesis: Mapping[str, Any], addressability: Mapping[str, Any], fast: Mapping[str, Any]) -> dict[str, Any]:
    dims = thesis.get("dimensions") if isinstance(thesis.get("dimensions"), Mapping) else {}
    addr_dims = addressability.get("dimensions") if isinstance(addressability.get("dimensions"), Mapping) else {}
    right = normalize_state((addr_dims.get("right_to_win") or {}).get("state"))
    domain = normalize_state((addr_dims.get("domain_knowledge") or {}).get("state"))
    access = normalize_state((addr_dims.get("buyer_access") or {}).get("state"))
    legitimacy = normalize_state((addr_dims.get("legitimacy") or {}).get("state"))

    if right == "REFUTED":
        return {"mode": "STOP_OR_PARTNER", "action": "DO_NOT_BUILD", "reason": "FIRST_PERSON_RIGHT_TO_WIN_REFUTED", "authority": "FOUNDER_DECISION_SUPPORT_ONLY"}
    if domain not in {"SUPPORTED", "PARTIAL"}:
        return {"mode": "FOUNDER_DISCOVERY", "action": "DOMAIN_EXPERT_OR_PRACTITIONER_INTERVIEW", "reason": "DOMAIN_JUDGMENT_NOT_ESTABLISHED", "authority": "PLANNING_ONLY"}
    if legitimacy not in {"SUPPORTED", "PARTIAL"}:
        return {"mode": "FOUNDER_DISCOVERY", "action": "BUILD_OR_BORROW_LEGITIMACY", "reason": "PROVIDER_CREDIBILITY_NOT_ESTABLISHED", "authority": "PLANNING_ONLY"}
    if access not in {"SUPPORTED", "PARTIAL"}:
        return {"mode": "FOUNDER_DISCOVERY", "action": "IDENTIFY_REACHABLE_BUYER_CHANNEL", "reason": "BUYER_ACCESS_NOT_ESTABLISHED", "authority": "PLANNING_ONLY"}

    # Once core buyer/problem/gap truth is strong, desk research should not monopolize VOI.
    p, b, g, e = (dim_state(dims, k) for k in ("problem_persistence", "buyer_formation", "gap_durability", "economic_materiality"))
    econ = normalize_state((thesis.get("claim_states") or {}).get("C11"))
    if fast.get("market_action_candidate") and all(x == "SUPPORTED" for x in (p, b, g)) and econ not in {"SUPPORTED", "REFUTED"}:
        return {"mode": "MARKET_ACTION", "action": "PAID_PILOT_OR_PREORDER_TEST", "reason": "WTP_UNCERTAINTY_BETTER_REDUCED_BY_MARKET_ACTION", "authority": "FOUNDER_EXECUTION_REQUIRED"}
    if fast.get("state") == "READY":
        return {"mode": "MARKET_ACTION", "action": "BOUNDED_CUSTOMER_TEST", "reason": "FAST_VALIDATION_GATE_READY", "authority": "FOUNDER_EXECUTION_REQUIRED"}

    # Preserve Brain's highest-VOI evidence question when market action is premature.
    plan = thesis.get("research_plan") if isinstance(thesis.get("research_plan"), list) else []
    if plan:
        first = dict(plan[0])
        return {"mode": "RESEARCH", "action": first.get("action"), "dimension": first.get("dimension"), "voi": first.get("voi"), "reason": "HIGHEST_BRAIN_VOI_OPEN_DIMENSION", "authority": "PLANNING_ONLY"}
    if e not in {"SUPPORTED", "REFUTED"}:
        return {"mode": "RESEARCH", "action": "FIND_DIRECT_ECONOMIC_CONSEQUENCE_EVIDENCE", "reason": "ECONOMIC_MATERIALITY_OPEN", "authority": "PLANNING_ONLY"}
    return {"mode": "HOLD", "action": "NO_HIGH_VALUE_NEXT_ACTION", "reason": "NO_DECISION_CRITICAL_OPEN_ACTION", "authority": "PLANNING_ONLY"}


def design_priors_for(thesis: Mapping[str, Any]) -> list[str]:
    priors = ["ENTREPRENEURIAL_ALERTNESS", "THIRD_TO_FIRST_PERSON", "MARKET_CHOICE_SET"]
    if clean(thesis.get("transition_lineage_id")):
        priors.append("WINDOWS_OF_OPPORTUNITY")
    if int(thesis.get("workaround_level", 0) or 0) >= 5:
        priors.append("LEAD_USER")
    priors.extend(["EFFECTUATION", "BRICOLAGE", "LEGITIMACY", "LEAN_VALIDATION"])
    return list(dict.fromkeys(priors))


def decorate_thesis_with_strategy(
    thesis: Mapping[str, Any],
    *,
    company_profile: Mapping[str, Any] | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    out = dict(thesis)
    addressability = assess_founder_addressability(out, company_profile=company_profile, root=root)
    fast = assess_fast_validation(out, addressability)
    track = strategic_track(out, fast)
    next_action = choose_best_next_action(out, addressability, fast)
    out["founder_addressability"] = addressability
    out["fast_validation"] = fast
    out["strategic_track"] = track
    out["best_next_action"] = next_action
    out["borrowed_frameworks"] = {
        "design_priors": design_priors_for(out),
        "authority": "DESIGN_PRIORS_ONLY_NOT_LIVE_MARKET_EVIDENCE",
    }
    out["strategic_truth_boundary"] = (
        "Discovery frameworks guide search; Radar evidence owns market truth; Brain owns structural synthesis; "
        "Founder addressability owns first-person fit; market actions/outcomes alone may calibrate predictive value."
    )
    return out


def strategic_sort_key(thesis: Mapping[str, Any]) -> tuple[Any, ...]:
    track_priority = {"BOTH": 0, "ZIP2_STRUCTURAL": 1, "FAST_VALIDATION": 2, "NEITHER": 3}
    zip2_priority = {"ZIP2_HIGH_CONVICTION": 0, "ZIP2_CANDIDATE": 1, "NOT_ZIP2_CLASS": 2}
    fast_priority = {"READY": 0, "RESEARCH_READY": 1, "NOT_READY": 2, "BLOCKED": 3}
    addr = thesis.get("founder_addressability") if isinstance(thesis.get("founder_addressability"), Mapping) else {}
    right = normalize_state((((addr.get("dimensions") or {}).get("right_to_win") or {}).get("state")))
    right_priority = {"SUPPORTED": 0, "PARTIAL": 1, "INSUFFICIENT": 2, "UNKNOWN": 3, "REFUTED": 4}.get(right, 5)
    return (
        track_priority.get(clean(thesis.get("strategic_track")).upper(), 4),
        zip2_priority.get(clean(thesis.get("zip2_readiness")).upper(), 3),
        fast_priority.get(clean((thesis.get("fast_validation") or {}).get("state")).upper(), 4),
        right_priority,
        clean(thesis.get("thesis_id")),
    )


def strategic_summary(theses: list[Mapping[str, Any]]) -> dict[str, Any]:
    counts = {k: 0 for k in ("BOTH", "ZIP2_STRUCTURAL", "FAST_VALIDATION", "NEITHER")}
    fast_counts: dict[str, int] = {}
    addressability_counts: dict[str, int] = {}
    for row in theses:
        track = clean(row.get("strategic_track")).upper() or "NEITHER"
        counts[track] = counts.get(track, 0) + 1
        fs = clean((row.get("fast_validation") or {}).get("state")).upper() or "UNKNOWN"
        fast_counts[fs] = fast_counts.get(fs, 0) + 1
        addr = row.get("founder_addressability") or {}
        rs = clean((((addr.get("dimensions") or {}).get("right_to_win") or {}).get("state"))).upper() or "UNKNOWN"
        addressability_counts[rs] = addressability_counts.get(rs, 0) + 1
    return {
        "strategic_track_counts": counts,
        "fast_validation_counts": fast_counts,
        "founder_addressability_counts": addressability_counts,
        "golden_overlap_count": counts.get("BOTH", 0),
        "empty_is_valid": True,
        "authority": "DERIVED_FOUNDER_STRATEGY_NO_ATOMIC_MARKET_TRUTH_WRITE",
    }


def static_acceptance() -> dict[str, bool]:
    base = {
        "classification": "FOUNDER_TEST_READY",
        "zip2_readiness": "ZIP2_CANDIDATE",
        "representative_title": "Developer tool for AI coding-agent verification",
        "representative_problem": "Software teams manually verify coding-agent changes",
        "claim_states": {"C09": "SUPPORTED", "C10": "SUPPORTED", "C11": "UNKNOWN"},
        "dimensions": {
            "problem_persistence": {"state": "SUPPORTED"},
            "economic_materiality": {"state": "SUPPORTED"},
            "buyer_formation": {"state": "SUPPORTED"},
            "gap_durability": {"state": "SUPPORTED"},
            "workaround_intensity": {"state": "SUPPORTED"},
            "distribution_leverage": {"state": "SUPPORTED"},
            "captureability": {"state": "SUPPORTED"},
        },
        "workaround_level": 5,
    }
    profile = {
        "version": "fixture",
        "strengths": [
            {"capability": "AI/API integration", "level": "strong"},
            {"capability": "Python backend development", "level": "strong"},
            {"capability": "Web product prototyping", "level": "strong"},
            {"capability": "Data scraping and evidence pipelines", "level": "strong"},
            {"capability": "Rapid AI-assisted MVP implementation", "level": "strong"},
        ],
        "known_gaps": [{"capability": "Deep specialist domain expertise", "level": "unknown_or_low_by_default"}],
    }
    good = decorate_thesis_with_strategy(base, company_profile=profile)
    regulated = decorate_thesis_with_strategy({**base, "representative_title": "Clinical diagnosis AI for hospitals"}, company_profile=profile)
    generic_ai = assess_founder_addressability({**base, "representative_title": "AI can build nuclear plant compliance software"}, company_profile=profile)
    return {
        "strategic_track_enum_bounded": good.get("strategic_track") in STRATEGIC_TRACKS,
        "zip2_and_fast_can_overlap": good.get("strategic_track") == "BOTH",
        "ai_does_not_override_regulated_legitimacy": (((regulated.get("founder_addressability") or {}).get("dimensions") or {}).get("right_to_win") or {}).get("state") == "REFUTED",
        "unknown_domain_not_auto_supported": (((generic_ai.get("dimensions") or {}).get("domain_knowledge") or {}).get("state") != "SUPPORTED"),
        "market_action_can_replace_more_web_research_for_wtp": (good.get("best_next_action") or {}).get("mode") == "MARKET_ACTION",
        "borrowed_frameworks_have_zero_live_truth_authority": (good.get("borrowed_frameworks") or {}).get("authority") == "DESIGN_PRIORS_ONLY_NOT_LIVE_MARKET_EVIDENCE",
    }


def founder_action_queue(theses: list[Mapping[str, Any]], *, limit: int = 100) -> list[dict[str, Any]]:
    """Create a bounded Founder action/research queue from strategic theses.

    This is intentionally derived at read/projection time rather than persisted as market
    truth. A MARKET_ACTION row is permission to test, never evidence that the test worked.
    """
    mode_priority = {"MARKET_ACTION": 0, "FOUNDER_DISCOVERY": 1, "RESEARCH": 2, "STOP_OR_PARTNER": 3, "HOLD": 4}
    rows: list[dict[str, Any]] = []
    for thesis in theses:
        action = thesis.get("best_next_action") if isinstance(thesis.get("best_next_action"), Mapping) else {}
        mode = clean(action.get("mode")).upper() or "HOLD"
        rows.append({
            "thesis_id": thesis.get("thesis_id"),
            "problem_lineage_id": thesis.get("problem_lineage_id"),
            "representative_title": thesis.get("representative_title"),
            "representative_problem": thesis.get("representative_problem"),
            "strategic_track": thesis.get("strategic_track"),
            "zip2_readiness": thesis.get("zip2_readiness"),
            "fast_validation_state": (thesis.get("fast_validation") or {}).get("state"),
            "first_person_addressability_state": (thesis.get("founder_addressability") or {}).get("first_person_addressability_state"),
            "mode": mode,
            "action": action.get("action"),
            "reason": action.get("reason"),
            "authority": action.get("authority"),
            "member_candidate_ids": thesis.get("member_candidate_ids") or [],
        })
    rows.sort(key=lambda r: (mode_priority.get(clean(r.get("mode")).upper(), 9), strategic_sort_key(next((t for t in theses if t.get("thesis_id") == r.get("thesis_id")), {}))))
    return rows[: max(0, int(limit))]
