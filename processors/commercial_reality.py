"""SignalForge commercial / timing reality V4.

Develops the weak commercial/timing claims in parallel while preserving the
boundary between desk research and real market validation.

Claims:
- C08 differentiation_possible
- C10 distribution_feasible
- C11 economics_plausible
- C12 window_outlasts_execution
- C13 competition_survivable
- C14 customer_switch_plausible

Core rule:
Context can prepare a claim, but public evidence cannot pretend to be a real
acquisition, WTP, or switching experiment.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime
from typing import Any

from sqlalchemy import select

from database.connection import (
    async_session,
    ProblemCandidate,
    RadarCase,
    RadarClaim,
    RadarEvidence,
    RadarClaimEvidence,
)
from processors.opportunity_reality import (
    _prime_reality_session_caches,
    _refresh_claim_state as _refresh_claim_state_cached,
)

ENGINE_VERSION = "commercial-reality-r5-scoped-batched-ledger"

TARGET_CODES = ("C08", "C10", "C11", "C12", "C13", "C14")

RESOLUTION_MODE = {
    "C08": "MACHINE_RESEARCH_THEN_FALSIFY",
    "C10": "MARKET_TEST_REQUIRED",
    "C11": "MARKET_TEST_REQUIRED",
    "C12": "MACHINE_SCENARIO_THEN_MARKET_UPDATE",
    "C13": "MACHINE_RESEARCH_THEN_FALSIFY",
    "C14": "MARKET_TEST_REQUIRED",
}

KNOWN_PLATFORM_TERMS = (
    "openai", "chatgpt", "anthropic", "claude", "google", "gemini",
    "microsoft", "copilot", "salesforce", "hubspot", "shopify", "wix",
    "framer", "aws", "azure", "cursor", "perplexity", "deepseek",
    "qwen", "ollama", "vllm", "langchain", "langgraph",
)

PUBLIC_CHANNELS = {
    "reddit": "Reddit",
    "hackernews": "Hacker News",
    "stackoverflow": "Stack Overflow",
    "stackexchange": "Stack Exchange",
    "github_issue": "GitHub Issues",
    "github": "GitHub",
    "discourse_feed": "Discourse",
    "discourse": "Discourse",
    "gitlab_issue": "GitLab",
    "gitlab": "GitLab",
    "yc": "YC",
    "package": "Package ecosystem",
}

EXPLICIT_MONEY_PATTERNS = (
    r"(?:US\$|USD|\$)\s?\d[\d,]*(?:\.\d+)?",
    r"(?:€|EUR)\s?\d[\d,]*(?:\.\d+)?",
    r"(?:£|GBP)\s?\d[\d,]*(?:\.\d+)?",
    r"\bwilling(?:ness)? to pay\b",
    r"\bpaid (?:for|pilot|plan|subscription|contract)\b",
    r"\bpay(?:ing)? (?:for|customer|client)\b",
    r"\bpricing\b",
    r"\bprice(?:d| point)?\b",
    r"\bsubscription\b",
    r"\bcontract value\b",
    r"\bannual contract\b",
    r"\bmonthly fee\b",
    r"\bpilot fee\b",
)

JOB_COMPENSATION_PATTERNS = (
    r"\bsalary\b",
    r"\bcompensation\b",
    r"\bper year\b",
    r"\bper annum\b",
    r"\bhourly\b",
    r"\bbase pay\b",
    r"\bequity\b",
)

ACQUISITION_PATTERNS = (
    r"\b(?:acquir|find|reach|win|convert)(?:ed|ing)? customers?\b",
    r"\bqualified leads?\b",
    r"\blead generation\b",
    r"\boutbound\b",
    r"\bcold email\b",
    r"\bcold outreach\b",
    r"\bsales channel\b",
    r"\bpartner channel\b",
    r"\breferral(?:s)?\b",
    r"\bmarketplace\b",
    r"\bSEO\b",
    r"\bpaid ads?\b",
)

COMPETITION_PATTERNS = (
    r"\bcompetitor",
    r"\balternative(?:s)?\b",
    r"\bversus\b",
    r"\bvs\.?\b",
    r"\bcompared? (?:with|to)\b",
    r"\breplac(?:e|ed|ing) .+ with\b",
    r"\bmigrat(?:e|ed|ing) from\b",
)

EXPLICIT_SWITCH_PATTERNS = (
    r"\bswitch(?:ed|ing)? from\b",
    r"\bmigrat(?:e|ed|ing|ion) from\b",
    r"\breplac(?:e|ed|ing) .+ with\b",
    r"\bmoved? from .+ to\b",
    r"\bleft .+ for\b",
)

WORKAROUND_PATTERNS = (
    r"\bworkaround\b",
    r"\bmanual workaround\b",
    r"\bmanually\b",
)

LOCKIN_PATTERNS = (
    r"\block[- ]?in\b",
    r"\bmigration cost\b",
    r"\bswitching cost\b",
    r"\bproprietary format\b",
    r"\bdata export\b",
    r"\bintegration cost\b",
    r"\bretraining\b",
)

TIMING_ENABLE_PATTERNS = (
    r"\bnew (?:model|api|capability|release)\b",
    r"\blaunch(?:ed|ing)?\b",
    r"\brelease(?:d)?\b",
    r"\bopen[- ]source\b",
    r"\bcheaper\b",
    r"\bcost (?:fell|dropped|reduced)\b",
    r"\bfaster\b",
    r"\bperformance improvement\b",
    r"\bavailable via api\b",
)

EROSION_PATTERNS = (
    r"\bbuilt[- ]?in\b",
    r"\bnative\b",
    r"\bincluded\b",
    r"\bintegrat(?:ed|ion)\b",
    r"\bfree tier\b",
    r"\bprice cut\b",
    r"\bcommoditi[sz]",
    r"\bplatform feature\b",
)

MOAT_PATTERNS = (
    r"\bproprietary data\b",
    r"\bworkflow\b",
    r"\bnetwork effect\b",
    r"\bcustomer relationship\b",
    r"\bdistribution\b",
    r"\bcompliance\b",
    r"\bregulat",
    r"\bphysical\b",
    r"\bintegration\b",
    r"\bhistorical data\b",
)

DIRECTNESS_STRONG = {"DIRECT", "PRIMARY"}


def _state(claims: dict[str, RadarClaim], code: str) -> str:
    claim = claims.get(code)
    return str(claim.state if claim else "UNKNOWN").upper()


def _useful(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return text not in {
        "", "unknown", "none", "unclear", "n/a", "none mentioned",
        "not specified", "no workaround", "no workaround mentioned",
        "not mentioned", "nothing mentioned",
    }


def _ev_text(ev: RadarEvidence) -> str:
    return " ".join(
        str(x or "")
        for x in (
            getattr(ev, "source_title", ""),
            getattr(ev, "excerpt", ""),
        )
    )


def _source_type(ev: RadarEvidence) -> str:
    return str(getattr(ev, "source_type", "") or "").lower()


def _is_job(ev: RadarEvidence) -> bool:
    st = _source_type(ev)
    return st.startswith("job") or "job_" in st or "hiring" in st


def _match_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text or "", re.I) for pattern in patterns)


def _family_set(items: list[RadarEvidence]) -> set[str]:
    return {
        str(ev.source_family_key or "")
        for ev in items
        if str(ev.source_family_key or "").strip()
    }


def _direct_family_set(items: list[RadarEvidence]) -> set[str]:
    return {
        str(ev.source_family_key or "")
        for ev in items
        if (
            str(ev.source_family_key or "").strip()
            and str(ev.directness or "").upper() in DIRECTNESS_STRONG
        )
    }


def _source_label(source_type: Any) -> str | None:
    st = str(source_type or "").lower()
    for prefix, label in PUBLIC_CHANNELS.items():
        if st == prefix or st.startswith(prefix + ":") or st.startswith(prefix + "_"):
            return label
    return None


def _platform_terms(text: str) -> list[str]:
    low = str(text or "").lower()
    return sorted({term for term in KNOWN_PLATFORM_TERMS if term in low})


def _candidate_wedge(
    candidate: ProblemCandidate,
    *,
    c06: str,
    c07: str,
) -> str | None:
    if c06 != "SUPPORTED" or c07 != "SUPPORTED":
        return None

    failure = str(getattr(candidate, "failure_mode", "") or "").strip()
    workaround = str(getattr(candidate, "workaround", "") or "").strip()

    if _useful(failure) and _useful(workaround):
        return (
            f"Reduce '{failure[:180]}' without forcing users to rely on "
            f"'{workaround[:180]}'."
        )
    if _useful(failure):
        return "Target the verified unresolved failure mode: " + failure[:260]
    return None


def _explicit_money(ev: RadarEvidence) -> bool:
    if _is_job(ev):
        return False
    text = _ev_text(ev)
    if _match_any(text, JOB_COMPENSATION_PATTERNS):
        if not re.search(
            r"\b(?:customer|client|subscription|contract|pilot|pricing|price)\b",
            text,
            re.I,
        ):
            return False
    return _match_any(text, EXPLICIT_MONEY_PATTERNS)


def _acquisition_signal(ev: RadarEvidence) -> bool:
    if _is_job(ev):
        return False
    return _match_any(_ev_text(ev), ACQUISITION_PATTERNS)


def _competition_signal(ev: RadarEvidence) -> bool:
    text = _ev_text(ev)
    if _match_any(text, COMPETITION_PATTERNS):
        return True
    st = _source_type(ev)
    named = bool(_platform_terms(text))
    ecosystem = st.startswith(("package", "yc", "github_repo", "github:repo"))
    return bool(named and ecosystem)


def _explicit_switch(ev: RadarEvidence) -> bool:
    return _match_any(_ev_text(ev), EXPLICIT_SWITCH_PATTERNS)


def _workaround_signal(ev: RadarEvidence) -> bool:
    return _match_any(_ev_text(ev), WORKAROUND_PATTERNS)


def _timing_enable(ev: RadarEvidence) -> bool:
    return _match_any(_ev_text(ev), TIMING_ENABLE_PATTERNS)


def _erosion_signal(ev: RadarEvidence) -> bool:
    text = _ev_text(ev)
    if _match_any(text, EROSION_PATTERNS):
        return True
    return bool(_platform_terms(text) and _match_any(text, TIMING_ENABLE_PATTERNS))


def _moat_signal(ev: RadarEvidence) -> bool:
    return _match_any(_ev_text(ev), MOAT_PATTERNS)


def qualify_evidence_for_claim(code: str, ev: RadarEvidence) -> bool:
    if code == "C08":
        return _competition_signal(ev) or _moat_signal(ev)
    if code == "C10":
        return _acquisition_signal(ev)
    if code == "C11":
        return _explicit_money(ev)
    if code == "C12":
        return _timing_enable(ev) or _erosion_signal(ev)
    if code == "C13":
        return _competition_signal(ev)
    if code == "C14":
        return _explicit_switch(ev) or _workaround_signal(ev)
    return False


def rank_evidence_for_claim(code: str, ev: RadarEvidence) -> tuple[int, int, int]:
    strong = 0
    if code == "C08":
        strong = int(_competition_signal(ev)) + int(_moat_signal(ev))
    elif code == "C10":
        strong = int(_acquisition_signal(ev))
    elif code == "C11":
        strong = int(_explicit_money(ev))
    elif code == "C12":
        strong = int(_timing_enable(ev)) + int(_erosion_signal(ev))
    elif code == "C13":
        strong = int(_competition_signal(ev))
    elif code == "C14":
        strong = 2 * int(_explicit_switch(ev)) + int(_workaround_signal(ev))

    direct = int(str(ev.directness or "").upper() in DIRECTNESS_STRONG)
    authority = int(
        str(ev.authority_class or "").upper()
        not in {"", "UNKNOWN", "COMMUNITY_SIGNAL"}
    )
    return (strong, direct, authority)


def _feature_sets(evidence: list[RadarEvidence]) -> dict[str, list[RadarEvidence]]:
    return {
        "money": [ev for ev in evidence if _explicit_money(ev)],
        "acquisition": [ev for ev in evidence if _acquisition_signal(ev)],
        "competition": [ev for ev in evidence if _competition_signal(ev)],
        "switching": [ev for ev in evidence if _explicit_switch(ev)],
        "workaround": [ev for ev in evidence if _workaround_signal(ev)],
        "lockin": [
            ev for ev in evidence
            if _match_any(_ev_text(ev), LOCKIN_PATTERNS)
        ],
        "timing": [ev for ev in evidence if _timing_enable(ev)],
        "erosion": [ev for ev in evidence if _erosion_signal(ev)],
        "moat": [ev for ev in evidence if _moat_signal(ev)],
    }


def _metrics(features: dict[str, list[RadarEvidence]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for name, rows in features.items():
        out[f"{name}_families"] = len(_family_set(rows))
        out[f"{name}_direct_families"] = len(_direct_family_set(rows))
    return out


def _status_for(
    code: str,
    *,
    claims: dict[str, RadarClaim],
    metrics: dict[str, int],
    wedge: str | None,
) -> tuple[str, list[str]]:
    if code == "C08":
        if _state(claims, "C06") != "SUPPORTED" or _state(claims, "C07") != "SUPPORTED":
            return "BLOCKED_BY_PROBLEM_REALITY", []
        if wedge and metrics["competition_families"] >= 2:
            return "WEDGE_HYPOTHESIS_READY_REQUIRES_FALSIFICATION", []
        return "NEEDS_COMPETITIVE_CONTEXT", ["market"]

    if code == "C10":
        if _state(claims, "C05") != "SUPPORTED":
            return "BLOCKED_BY_BUYER_REALITY", []
        if metrics["acquisition_families"] >= 1:
            return "MARKET_TEST_READY", []
        return "NEEDS_DISTRIBUTION_CONTEXT", ["buyer", "market"]

    if code == "C11":
        if _state(claims, "C05") != "SUPPORTED":
            return "BLOCKED_BY_BUYER_REALITY", []
        if metrics["money_direct_families"] >= 1:
            return "MARKET_TEST_READY", []
        if metrics["money_families"] >= 1:
            return "PRICE_CONTEXT_READY_NOT_WTP", ["buyer"]
        return "NEEDS_PRICE_WTP_CONTEXT", ["buyer", "market"]

    if code == "C12":
        if metrics["timing_families"] + metrics["erosion_families"] >= 2:
            return "SCENARIO_READY_NOT_FORECAST", []
        return "NEEDS_TIMING_TECH_CONTEXT", ["timing"]

    if code == "C13":
        if metrics["competition_families"] >= 2:
            return "COMPETITION_MAP_READY_REQUIRES_SURVIVABILITY_TEST", []
        return "NEEDS_COMPETITION_CONTEXT", ["market"]

    if code == "C14":
        if _state(claims, "C05") != "SUPPORTED":
            return "BLOCKED_BY_BUYER_REALITY", []
        if metrics["switching_families"] >= 1:
            return "MARKET_TEST_READY", []
        if metrics["workaround_families"] >= 1:
            return "WORKAROUND_CONTEXT_READY_NOT_SWITCH_INTENT", ["buyer"]
        return "NEEDS_SWITCHING_BEHAVIOR_CONTEXT", ["buyer", "market"]

    return "UNKNOWN", []


def _validation_plan(
    code: str,
    *,
    status: str,
    candidate: ProblemCandidate,
    channels: list[str],
    wedge: str | None,
) -> dict[str, Any] | None:
    actor = str(getattr(candidate, "actor", "") or "").strip() or "target user"
    problem = (
        str(getattr(candidate, "problem_statement", "") or "").strip()
        or str(getattr(candidate, "title", "") or "").strip()
    )
    current_solution = str(
        getattr(candidate, "workaround", "") or ""
    ).strip() or None

    if code == "C10" and status == "MARKET_TEST_READY":
        return {
            "experiment": "TARGETED_ACQUISITION_TEST",
            "target": actor,
            "problem": problem[:320],
            "candidate_channels": channels[:4],
            "pass_signal": (
                "A qualified target buyer reached through a chosen channel "
                "agrees to a real problem interview, demo, or pilot discussion."
            ),
            "fail_signal": (
                "Repeated targeted attempts produce no qualified engagement; "
                "do not reinterpret impressions/clicks as acquisition proof."
            ),
            "founder_required_now": False,
        }

    if code == "C11" and status == "MARKET_TEST_READY":
        return {
            "experiment": "PRICE_COMMITMENT_TEST",
            "target": actor,
            "problem": problem[:320],
            "pass_signal": (
                "A qualified buyer accepts a concrete paid pilot, deposit, "
                "purchase commitment, or equivalent price-bearing action."
            ),
            "fail_signal": (
                "Interest without a price-bearing commitment remains "
                "INSUFFICIENT for WTP."
            ),
            "founder_required_now": False,
        }

    if code == "C14" and status == "MARKET_TEST_READY":
        return {
            "experiment": "SWITCH_COMMITMENT_TEST",
            "target": actor,
            "problem": problem[:320],
            "current_solution_or_workaround": current_solution,
            "pass_signal": (
                "A target user moves a real workflow, dataset, or recurring "
                "task to the proposed alternative/pilot."
            ),
            "fail_signal": (
                "Positive feedback without moving real behavior is not "
                "switching proof."
            ),
            "founder_required_now": False,
        }

    if code == "C08" and status == "WEDGE_HYPOTHESIS_READY_REQUIRES_FALSIFICATION":
        return {
            "experiment": "WEDGE_FALSIFICATION",
            "hypothesis": wedge,
            "pass_signal": (
                "The wedge survives direct comparison against named current "
                "solutions and is not already a baseline/platform feature."
            ),
            "fail_signal": (
                "A credible incumbent/platform already provides the same "
                "advantage with comparable adoption friction."
            ),
            "founder_required_now": False,
        }

    if code == "C13" and status == "COMPETITION_MAP_READY_REQUIRES_SURVIVABILITY_TEST":
        return {
            "experiment": "COMPETITIVE_RESPONSE_FALSIFICATION",
            "pass_signal": (
                "At least one durable advantage remains after considering "
                "incumbent replication and platform absorption."
            ),
            "fail_signal": (
                "The opportunity depends mainly on a capability incumbents "
                "can copy or bundle before customer acquisition compounds."
            ),
            "founder_required_now": False,
        }

    return None


async def _refresh_from_links(session, claim: RadarClaim) -> None:
    rows = list(
        (
            await session.execute(
                select(RadarClaimEvidence, RadarEvidence)
                .join(
                    RadarEvidence,
                    RadarEvidence.id == RadarClaimEvidence.evidence_id,
                )
                .where(RadarClaimEvidence.claim_id == claim.id)
            )
        ).all()
    )

    support = {
        ev.source_family_key
        for link, ev in rows
        if link.validated and link.stance == "SUPPORT"
    }
    refute = {
        ev.source_family_key
        for link, ev in rows
        if link.validated and link.stance == "REFUTE"
    }
    direct = {
        ev.source_family_key
        for link, ev in rows
        if (
            link.validated
            and link.stance == "SUPPORT"
            and ev.directness == "DIRECT"
        )
    }
    weak = sum(
        1
        for link, _ in rows
        if link.validated and link.stance in {"INSUFFICIENT", "RELATED"}
    )

    needed = max(1, int(claim.required_support_groups or 2))
    claim.support_groups = len(support)
    claim.direct_support_groups = len(direct)
    claim.refute_groups = len(refute)
    claim.insufficient_count = weak

    if refute and len(support) >= needed:
        claim.state = "CONFLICTED"
    elif refute and not support:
        claim.state = "REFUTED"
    elif len(support) >= needed:
        claim.state = "SUPPORTED"
    elif rows:
        claim.state = "INSUFFICIENT"
    else:
        claim.state = "UNKNOWN"

    claim.last_evaluated_at = datetime.utcnow()


async def run_commercial_reality(case_ids: list[int] | None = None) -> dict[str, Any]:
    async with async_session() as session:
        stmt = (
            select(RadarCase, ProblemCandidate)
            .join(ProblemCandidate, ProblemCandidate.id == RadarCase.candidate_id)
            .order_by(RadarCase.id)
        )
        if case_ids is not None:
            normalized_case_ids = sorted({int(x) for x in case_ids if int(x) > 0})
            stmt = stmt.where(RadarCase.id.in_(normalized_case_ids))
        pairs = list((await session.execute(stmt)).all())
        selected_case_ids = [case.id for case, _ in pairs]

        claim_rows = list(
            (
                await session.execute(
                    select(RadarClaim).where(RadarClaim.case_id.in_(selected_case_ids))
                )
            ).scalars().all()
        )
        # M18: commercial context refresh used to issue one claim/link SELECT
        # for every C08/C10-C14 claim (~6 x cases). Reuse the exact shared
        # ledger cache and the same state reducer; epistemic thresholds do not
        # change.
        target_claim_ids = [
            int(c.id) for c in claim_rows if str(c.claim_code) in TARGET_CODES
        ]
        await _prime_reality_session_caches(
            session, claim_ids=target_claim_ids
        )
        evidence_rows = list(
            (
                await session.execute(
                    select(RadarEvidence).where(
                        RadarEvidence.case_id.in_(selected_case_ids)
                    )
                )
            ).scalars().all()
        )

        claims_by_case: dict[int, dict[str, RadarClaim]] = defaultdict(dict)
        evidence_by_case: dict[int, list[RadarEvidence]] = defaultdict(list)

        for claim in claim_rows:
            claims_by_case[claim.case_id][claim.claim_code] = claim
        for ev in evidence_rows:
            evidence_by_case[ev.case_id].append(ev)

        results: dict[int, dict[str, Any]] = {}
        status_counts: dict[str, int] = defaultdict(int)
        validation_ready_counts: dict[str, int] = defaultdict(int)

        for case, candidate in pairs:
            claims = claims_by_case.get(case.id, {})
            evidence = evidence_by_case.get(case.id, [])
            features = _feature_sets(evidence)
            metrics = _metrics(features)

            c06 = _state(claims, "C06")
            c07 = _state(claims, "C07")
            wedge = _candidate_wedge(candidate, c06=c06, c07=c07)

            channels = sorted({
                label
                for ev in evidence
                for label in [_source_label(ev.source_type)]
                if label and _acquisition_signal(ev)
            })

            all_text = "\n".join(_ev_text(ev) for ev in evidence)
            platform_terms = _platform_terms(all_text)

            per_claim: dict[str, dict[str, Any]] = {}
            validation_plans: dict[str, dict[str, Any]] = {}
            needed_groups: list[str] = []

            for code in TARGET_CODES:
                claim = claims.get(code)
                if claim is None:
                    continue

                status, needs = _status_for(
                    code,
                    claims=claims,
                    metrics=metrics,
                    wedge=wedge,
                )
                status_counts[f"{code}:{status}"] += 1

                for group in needs:
                    if group not in needed_groups:
                        needed_groups.append(group)

                plan = _validation_plan(
                    code,
                    status=status,
                    candidate=candidate,
                    channels=channels,
                    wedge=wedge,
                )
                if plan is not None:
                    validation_plans[code] = plan
                    validation_ready_counts[code] += 1

                summary = dict(claim.evidence_summary or {})
                block = {
                    "status": status,
                    "engine_version": ENGINE_VERSION,
                    "resolution_mode": RESOLUTION_MODE[code],
                    "context_only": True,
                    "needed_source_groups": needs,
                    "metrics": metrics,
                    "validation_plan": plan,
                    "updated_at": datetime.utcnow().isoformat(),
                    "warning": (
                        "Desk research prepares this claim but does not "
                        "manufacture market truth."
                    ),
                }

                if code == "C08":
                    block.update({
                        "wedge_hypothesis": wedge,
                        "platform_absorption_terms": platform_terms[:8],
                    })
                elif code == "C10":
                    block.update({
                        "candidate_acquisition_channels": channels,
                        "buyer_state": _state(claims, "C05"),
                    })
                elif code == "C11":
                    block.update({
                        "buyer_state": _state(claims, "C05"),
                        "jobs_are_not_wtp": True,
                    })
                elif code == "C12":
                    erosion = metrics["erosion_families"]
                    enable = metrics["timing_families"]
                    block.update({
                        "technology_enablement_families": enable,
                        "model_erosion_families": erosion,
                        "platform_absorption_terms": platform_terms[:8],
                        "execution_state": _state(claims, "C09"),
                        "window_risk_hypothesis": (
                            "EROSION_PRESSURE_HIGH"
                            if erosion > enable and platform_terms
                            else "OPEN_BUT_UNCALIBRATED"
                        ),
                        "is_forecast": False,
                    })
                elif code == "C13":
                    block.update({
                        "platform_terms": platform_terms[:8],
                        "differentiation_state": _state(claims, "C08"),
                        "competition_families": metrics[
                            "competition_families"
                        ],
                    })
                elif code == "C14":
                    block.update({
                        "explicit_switch_families": metrics[
                            "switching_families"
                        ],
                        "workaround_families": metrics[
                            "workaround_families"
                        ],
                        "workaround_is_not_switch_proof": True,
                    })

                summary["parallel_reality_v2"] = block
                claim.evidence_summary = summary

                # Context planning must not manufacture epistemic state.
                # With zero validated claim/evidence links the correct state is
                # UNKNOWN, not INSUFFICIENT. This prevents the recurring
                # UNKNOWN -> INSUFFICIENT -> Quality-Guard repair oscillation.
                await _refresh_claim_state_cached(session, claim)

                per_claim[code] = {
                    "state": str(claim.state or "UNKNOWN").upper(),
                    "status": status,
                    "resolution_mode": RESOLUTION_MODE[code],
                    "needed_source_groups": needs,
                    "validation_plan_ready": plan is not None,
                    **metrics,
                }

            results[case.id] = {
                "case_id": case.id,
                "candidate_id": candidate.id,
                "title": candidate.title,
                "wedge_hypothesis": wedge,
                "candidate_acquisition_channels": channels,
                "needed_source_groups": needed_groups,
                "claim_matrix": per_claim,
                "validation_plans": validation_plans,
                "validation_ready_claims": sorted(validation_plans),
                "platform_terms": platform_terms[:8],
                "metrics": metrics,
            }

        await session.commit()

    return {
        "engine_version": ENGINE_VERSION,
        "cases": len(results),
        "results": results,
        "status_counts": dict(status_counts),
        "validation_ready_counts": dict(validation_ready_counts),
        "llm_calls": 0,
        "api_calls": 0,
    }
