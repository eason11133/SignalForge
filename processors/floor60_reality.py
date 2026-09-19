"""SignalForge Floor-60 Reality Engine V1.

This module raises the low commercial/timing modules from "context exists" to a
usable research/validation packet without manufacturing SUPPORT.

It works on the same Evidence Ledger as the rest of SignalForge and produces:
- C08 differentiation wedge + falsification packet
- C10 acquisition route + qualification packet
- C11 price/WTP evidence classes + price-commitment packet
- C12 technology enablement / erosion / platform absorption scenario
- C13 competitor / survivability packet
- C14 switching-friction / real-behavior packet

All outputs are hypotheses, research instructions, or validation plans unless
the underlying claim is already supported by validated evidence.
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
)
from processors.commercial_reality import (
    TARGET_CODES,
    _state,
    _ev_text,
    _feature_sets,
    _metrics,
    _candidate_wedge,
    _source_label,
    _platform_terms,
    _explicit_money,
    _acquisition_signal,
    _competition_signal,
    _explicit_switch,
    _workaround_signal,
    _timing_enable,
    _erosion_signal,
    _moat_signal,
)

ENGINE_VERSION = "floor60-reality-v1"

MONEY_CAPTURE = re.compile(
    r"(?P<currency>US\$|USD|\$|EUR|€|GBP|£)\s*"
    r"(?P<amount>\d[\d,]*(?:\.\d+)?)",
    re.I,
)

CURRENCY_MAP = {
    "$": "USD",
    "US$": "USD",
    "USD": "USD",
    "€": "EUR",
    "EUR": "EUR",
    "£": "GBP",
    "GBP": "GBP",
}

FRICTION_PATTERNS = {
    "DATA_MIGRATION": (
        r"\bmigrat", r"\bdata export\b", r"\bimport\b",
        r"\bproprietary format\b",
    ),
    "INTEGRATION": (
        r"\bintegration\b", r"\bapi\b", r"\bworkflow\b",
        r"\bplugin\b", r"\bconnector\b",
    ),
    "TRAINING": (
        r"\bretraining\b", r"\blearning curve\b", r"\bonboarding\b",
        r"\btraining\b",
    ),
    "CONTRACT_PROCUREMENT": (
        r"\bcontract\b", r"\bprocurement\b", r"\bapproval\b",
        r"\bbudget cycle\b",
    ),
    "LOCK_IN": (
        r"\block[- ]?in\b", r"\bswitching cost\b",
        r"\bvendor lock\b",
    ),
}

SOURCE_GROUP_FOR_STATUS = {
    "NEEDS_COMPETITIVE_CONTEXT": ("market",),
    "NEEDS_DISTRIBUTION_CONTEXT": ("buyer", "market"),
    "NEEDS_PRICE_WTP_CONTEXT": ("buyer", "market"),
    "NEEDS_TIMING_TECH_CONTEXT": ("timing",),
    "NEEDS_COMPETITION_CONTEXT": ("market",),
    "NEEDS_SWITCHING_BEHAVIOR_CONTEXT": ("buyer", "market"),
}

FALSIFICATION_CHECKS = {
    "C08": [
        "Find a named incumbent or platform that already ships the proposed wedge.",
        "Check whether the wedge is a baseline feature rather than a durable advantage.",
        "Check whether the advantage survives a 6–12 month model capability jump.",
    ],
    "C13": [
        "Identify the strongest incumbent response, not the average competitor.",
        "Check whether a platform can bundle the feature at near-zero marginal price.",
        "Check whether distribution, data, regulation, or workflow integration creates a durable moat.",
    ],
    "C12": [
        "Estimate whether model progress enables the solution faster than it erodes differentiation.",
        "Check likely platform absorption before time-to-customer-satisfaction.",
        "Keep future uncertainty explicit; do not convert scenario evidence into a forecast.",
    ],
}


def _claim_state(claims: dict[str, RadarClaim], code: str) -> str:
    return _state(claims, code)


def _safe(value: Any) -> str:
    return str(value or "").strip()


def _extract_money(rows: list[RadarEvidence]) -> list[dict[str, Any]]:
    out = []
    seen = set()
    for ev in rows:
        if not _explicit_money(ev):
            continue
        text = _ev_text(ev)
        matches = list(MONEY_CAPTURE.finditer(text))
        if not matches:
            # Explicit pricing/WTP language without a parseable numeric amount is
            # still useful context, but is not normalized into a fake number.
            key = (
                str(ev.source_family_key or ""),
                str(ev.source_title or "")[:180],
            )
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "currency": None,
                "amount": None,
                "source_family": str(ev.source_family_key or ""),
                "source_title": str(ev.source_title or "")[:220],
                "directness": str(ev.directness or ""),
                "note": "explicit money/pricing language; numeric amount not parsed",
            })
            continue

        for match in matches[:3]:
            raw_currency = match.group("currency").upper()
            currency = CURRENCY_MAP.get(
                raw_currency,
                CURRENCY_MAP.get(match.group("currency"), raw_currency),
            )
            amount = float(match.group("amount").replace(",", ""))
            key = (
                str(ev.source_family_key or ""),
                currency,
                amount,
            )
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "currency": currency,
                "amount": amount,
                "source_family": str(ev.source_family_key or ""),
                "source_title": str(ev.source_title or "")[:220],
                "directness": str(ev.directness or ""),
                "note": "public price context; not WTP proof",
            })
    return out[:12]


def _named_competitors(rows: list[RadarEvidence]) -> list[str]:
    out = []
    seen = set()

    for ev in rows:
        if not _competition_signal(ev):
            continue

        title = _safe(getattr(ev, "source_title", ""))
        if title and len(title) >= 4:
            label = title[:180]
            key = label.lower()
            if key not in seen:
                seen.add(key)
                out.append(label)

        for term in _platform_terms(_ev_text(ev)):
            label = term
            key = label.lower()
            if key not in seen:
                seen.add(key)
                out.append(label)

        if len(out) >= 8:
            break

    return out[:8]


def _channel_context(rows: list[RadarEvidence]) -> list[dict[str, Any]]:
    grouped: dict[str, set[str]] = defaultdict(set)
    examples: dict[str, str] = {}
    for ev in rows:
        if not _acquisition_signal(ev):
            continue
        label = _source_label(ev.source_type) or str(ev.source_type or "unknown")
        family = str(ev.source_family_key or "").strip()
        if family:
            grouped[label].add(family)
        if label not in examples:
            examples[label] = str(ev.source_title or "")[:180]

    return [
        {
            "channel": label,
            "evidence_families": len(families),
            "example": examples.get(label),
            "proof_level": "CONTEXT_ONLY_UNTIL_QUALIFIED_BUYER_ENGAGES",
        }
        for label, families in sorted(
            grouped.items(),
            key=lambda kv: (-len(kv[1]), kv[0]),
        )
    ]


def _friction_context(rows: list[RadarEvidence]) -> dict[str, int]:
    counts = {key: 0 for key in FRICTION_PATTERNS}
    for ev in rows:
        text = _ev_text(ev)
        for key, patterns in FRICTION_PATTERNS.items():
            if any(re.search(pattern, text, re.I) for pattern in patterns):
                counts[key] += 1
    return counts


def _machine_or_market(code: str, status: str) -> str:
    if status.startswith("BLOCKED_BY_"):
        return "MACHINE_RESEARCH_FIRST"
    if code in {"C10", "C11", "C14"} and status in {
        "MARKET_TEST_READY",
        "PRICE_CONTEXT_READY_NOT_WTP",
        "WORKAROUND_CONTEXT_READY_NOT_SWITCH_INTENT",
    }:
        return "MARKET_VALIDATION_NEXT"
    if code in {"C08", "C13"} and (
        "FALSIFICATION" in status or "SURVIVABILITY" in status
    ):
        return "MACHINE_FALSIFICATION_NEXT"
    if code == "C12" and status == "SCENARIO_READY_NOT_FORECAST":
        return "SCENARIO_MONITORING_NEXT"
    return "MACHINE_RESEARCH_FIRST"


def _packet_for(
    *,
    code: str,
    status: str,
    claims: dict[str, RadarClaim],
    candidate: ProblemCandidate,
    evidence: list[RadarEvidence],
    features: dict[str, list[RadarEvidence]],
    metrics: dict[str, int],
    wedge: str | None,
) -> dict[str, Any]:
    title = _safe(getattr(candidate, "title", ""))
    actor = _safe(getattr(candidate, "actor", "")) or "target user"
    problem = (
        _safe(getattr(candidate, "problem_statement", ""))
        or title
    )
    workaround = _safe(getattr(candidate, "workaround", ""))
    competitors = _named_competitors(features["competition"])
    channels = _channel_context(features["acquisition"])
    prices = _extract_money(features["money"])
    friction = _friction_context(evidence)

    packet: dict[str, Any] = {
        "claim_code": code,
        "status": status,
        "next_boundary": _machine_or_market(code, status),
        "target_actor": actor,
        "problem": problem[:360],
        "source_need": list(SOURCE_GROUP_FOR_STATUS.get(status, ())),
        "evidence_metrics": dict(metrics),
        "generated_at": datetime.utcnow().isoformat(),
        "support_not_inferred": True,
    }

    if code == "C08":
        packet.update({
            "wedge_hypothesis": wedge,
            "named_competitor_context": competitors,
            "falsification_checks": FALSIFICATION_CHECKS["C08"],
            "ready_when": (
                "C06 and C07 are supported, at least two independent competitive "
                "families exist, and the wedge survives direct incumbent comparison."
            ),
        })

    elif code == "C10":
        packet.update({
            "candidate_acquisition_routes": channels,
            "buyer_state": _claim_state(claims, "C05"),
            "experiment": {
                "type": "TARGETED_ACQUISITION_TEST",
                "unit": "qualified target buyer",
                "pass": (
                    "A qualified buyer reached through the chosen route agrees "
                    "to a real interview, demo, or pilot discussion."
                ),
                "fail": (
                    "Repeated targeted attempts create no qualified engagement. "
                    "Clicks/impressions do not count."
                ),
            },
        })

    elif code == "C11":
        packet.update({
            "public_price_context": prices,
            "buyer_state": _claim_state(claims, "C05"),
            "experiment": {
                "type": "PRICE_COMMITMENT_TEST",
                "unit": "qualified buyer with a concrete price",
                "pass": (
                    "A qualified buyer accepts a paid pilot, deposit, purchase "
                    "commitment, or equivalent price-bearing action."
                ),
                "fail": (
                    "Interest without a price-bearing commitment remains "
                    "INSUFFICIENT."
                ),
            },
        })

    elif code == "C12":
        enable = metrics.get("timing_families", 0)
        erosion = metrics.get("erosion_families", 0)
        platform_terms = _platform_terms(
            "\n".join(_ev_text(ev) for ev in evidence)
        )[:8]
        if enable > erosion:
            balance = "ENABLEMENT_AHEAD_OF_EROSION"
        elif erosion > enable:
            balance = "EROSION_AHEAD_OF_ENABLEMENT"
        elif enable or erosion:
            balance = "BALANCED_UNCERTAIN"
        else:
            balance = "EVIDENCE_TOO_THIN"

        packet.update({
            "technology_regime": {
                "enablement_families": enable,
                "erosion_families": erosion,
                "platform_absorption_terms": platform_terms,
                "execution_state": _claim_state(claims, "C09"),
                "balance": balance,
            },
            "scenario_matrix": [
                {
                    "scenario": "ENABLEMENT_WINS",
                    "condition": (
                        "capability/cost improves before incumbents absorb the "
                        "feature and before differentiation erodes"
                    ),
                    "implication": "window may open; still require execution-time evidence",
                },
                {
                    "scenario": "EROSION_WINS",
                    "condition": (
                        "model/platform progress commoditizes the value proposition "
                        "before customer acquisition compounds"
                    ),
                    "implication": "park or redesign moat",
                },
                {
                    "scenario": "PLATFORM_ABSORPTION",
                    "condition": (
                        "a dominant platform bundles the core capability before "
                        "time-to-customer-satisfaction"
                    ),
                    "implication": "need a non-feature moat or distribution wedge",
                },
            ],
            "falsification_checks": FALSIFICATION_CHECKS["C12"],
            "forecast_claimed": False,
        })

    elif code == "C13":
        packet.update({
            "named_competitor_context": competitors,
            "moat_signal_families": metrics.get("moat_families", 0),
            "platform_absorption_terms": _platform_terms(
                "\n".join(_ev_text(ev) for ev in evidence)
            )[:8],
            "falsification_checks": FALSIFICATION_CHECKS["C13"],
            "survivability_question": (
                "What remains defensible after the strongest incumbent response "
                "and one major platform bundling event?"
            ),
        })

    elif code == "C14":
        packet.update({
            "current_workaround": workaround or None,
            "explicit_switch_families": metrics.get("switching_families", 0),
            "workaround_families": metrics.get("workaround_families", 0),
            "friction_signals": friction,
            "experiment": {
                "type": "SWITCH_COMMITMENT_TEST",
                "unit": "real recurring workflow / data / task",
                "pass": (
                    "A target user moves a real recurring workflow, dataset, or "
                    "task to the proposed pilot/alternative."
                ),
                "fail": (
                    "Positive feedback without moving behavior is not switching proof."
                ),
            },
        })

    return packet


async def run_floor60_reality(
    case_ids: list[int] | None = None,
    *,
    limit: int | None = None,
) -> dict[str, Any]:
    async with async_session() as session:
        stmt = (
            select(RadarCase, ProblemCandidate)
            .join(
                ProblemCandidate,
                ProblemCandidate.id == RadarCase.candidate_id,
            )
            .order_by(RadarCase.id)
        )
        if case_ids is not None:
            normalized_case_ids = sorted({int(x) for x in case_ids if int(x) > 0})
            stmt = stmt.where(RadarCase.id.in_(normalized_case_ids))

        pairs = list((await session.execute(stmt)).all())
        if limit is not None:
            pairs = pairs[: max(1, int(limit))]

        ids = [case.id for case, _ in pairs]
        if not ids:
            return {
                "engine_version": ENGINE_VERSION,
                "cases": 0,
                "results": {},
                "status_counts": {},
                "boundary_counts": {},
                "source_need_counts": {},
                "api_calls": 0,
                "llm_calls": 0,
            }

        claims = list(
            (
                await session.execute(
                    select(RadarClaim).where(RadarClaim.case_id.in_(ids))
                )
            ).scalars().all()
        )
        evidence = list(
            (
                await session.execute(
                    select(RadarEvidence).where(RadarEvidence.case_id.in_(ids))
                )
            ).scalars().all()
        )

        claims_by_case: dict[int, dict[str, RadarClaim]] = defaultdict(dict)
        evidence_by_case: dict[int, list[RadarEvidence]] = defaultdict(list)
        for claim in claims:
            claims_by_case[claim.case_id][claim.claim_code] = claim
        for ev in evidence:
            evidence_by_case[ev.case_id].append(ev)

        results: dict[int, dict[str, Any]] = {}
        status_counts: dict[str, int] = defaultdict(int)
        boundary_counts: dict[str, int] = defaultdict(int)
        source_need_counts: dict[str, int] = defaultdict(int)

        for case, candidate in pairs:
            claim_map = claims_by_case.get(case.id, {})
            rows = evidence_by_case.get(case.id, [])
            features = _feature_sets(rows)
            metrics = _metrics(features)
            wedge = _candidate_wedge(
                candidate,
                c06=_claim_state(claim_map, "C06"),
                c07=_claim_state(claim_map, "C07"),
            )

            packets: dict[str, dict[str, Any]] = {}
            for code in TARGET_CODES:
                claim = claim_map.get(code)
                if claim is None:
                    continue

                summary = dict(claim.evidence_summary or {})
                commercial = (
                    summary.get("parallel_reality_v2")
                    or summary.get("parallel_reality_v1")
                    or {}
                )
                status = str(
                    commercial.get("status")
                    or "NO_COMMERCIAL_STATUS"
                ).upper()

                packet = _packet_for(
                    code=code,
                    status=status,
                    claims=claim_map,
                    candidate=candidate,
                    evidence=rows,
                    features=features,
                    metrics=metrics,
                    wedge=wedge,
                )
                packets[code] = packet
                status_counts[f"{code}:{status}"] += 1
                boundary_counts[packet["next_boundary"]] += 1
                for group in packet["source_need"]:
                    source_need_counts[group] += 1

                summary["floor60_v1"] = packet
                claim.evidence_summary = summary
                claim.last_evaluated_at = datetime.utcnow()

            results[case.id] = {
                "case_id": case.id,
                "title": candidate.title,
                "packets": packets,
                "source_needs": sorted({
                    group
                    for packet in packets.values()
                    for group in packet.get("source_need", [])
                }),
                "validation_ready_claims": sorted([
                    code
                    for code, packet in packets.items()
                    if packet.get("next_boundary") == "MARKET_VALIDATION_NEXT"
                ]),
                "machine_falsification_claims": sorted([
                    code
                    for code, packet in packets.items()
                    if packet.get("next_boundary") == "MACHINE_FALSIFICATION_NEXT"
                ]),
            }

        await session.commit()

    return {
        "engine_version": ENGINE_VERSION,
        "cases": len(results),
        "results": results,
        "status_counts": dict(status_counts),
        "boundary_counts": dict(boundary_counts),
        "source_need_counts": dict(source_need_counts),
        "api_calls": 0,
        "llm_calls": 0,
    }
