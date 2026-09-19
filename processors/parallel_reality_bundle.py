"""SignalForge Parallel Reality Bundle V2.

One precision-filtered local evidence pass develops C08/C10/C11/C12/C13/C14
together. Weak context remains weak context. Legacy broad bundle links that no
longer pass claim-specific qualification are preserved but invalidated.
"""

from __future__ import annotations

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
from processors.commercial_reality import (
    TARGET_CODES,
    qualify_evidence_for_claim,
    rank_evidence_for_claim,
)
from processors.opportunity_reality import _refresh_claim_state

ENGINE_VERSION = "parallel-reality-bundle-research-v2-precision"

WEAK_STANCE = {
    "C08": "RELATED",
    "C10": "RELATED",
    "C11": "INSUFFICIENT",
    "C12": "RELATED",
    "C13": "RELATED",
    "C14": "INSUFFICIENT",
}


async def _weak_link(
    session,
    claim: RadarClaim,
    ev: RadarEvidence,
    *,
    code: str,
) -> bool:
    existing = (
        await session.execute(
            select(RadarClaimEvidence).where(
                RadarClaimEvidence.claim_id == claim.id,
                RadarClaimEvidence.evidence_id == ev.id,
            )
        )
    ).scalar_one_or_none()

    if existing is not None:
        if str(existing.stance or "").upper() in {"SUPPORT", "REFUTE"}:
            return False
        if "human" in str(existing.interpretation_method or "").lower():
            return False
        if "manual" in str(existing.interpretation_method or "").lower():
            return False

        existing.stance = WEAK_STANCE[code]
        existing.interpretation_method = "parallel_reality_context_precise"
        existing.method_version = ENGINE_VERSION
        existing.interpretation_confidence = 0.64
        existing.rationale = (
            f"Precision-filtered shared evidence is relevant context for {code}; "
            "it is intentionally insufficient for SUPPORT."
        )
        existing.validated = True
        return False

    session.add(
        RadarClaimEvidence(
            claim_id=claim.id,
            evidence_id=ev.id,
            stance=WEAK_STANCE[code],
            interpretation_method="parallel_reality_context_precise",
            method_version=ENGINE_VERSION,
            interpretation_confidence=0.64,
            rationale=(
                f"Precision-filtered shared evidence is relevant context for {code}; "
                "it is intentionally insufficient for SUPPORT."
            ),
            validated=True,
        )
    )
    return True


async def _quarantine_legacy_weak_links(
    session,
    *,
    claims_by_case: dict[int, dict[str, RadarClaim]],
    evidence_by_id: dict[int, RadarEvidence],
) -> int:
    claim_ids = [
        claim.id
        for claims in claims_by_case.values()
        for claim in claims.values()
        if claim.claim_code in TARGET_CODES
    ]
    if not claim_ids:
        return 0

    links = list(
        (
            await session.execute(
                select(RadarClaimEvidence).where(
                    RadarClaimEvidence.claim_id.in_(claim_ids),
                    RadarClaimEvidence.interpretation_method
                    == "parallel_reality_context",
                    RadarClaimEvidence.validated == True,
                )
            )
        ).scalars().all()
    )

    claim_by_id = {
        claim.id: claim
        for claims in claims_by_case.values()
        for claim in claims.values()
    }

    quarantined = 0
    for link in links:
        claim = claim_by_id.get(link.claim_id)
        ev = evidence_by_id.get(link.evidence_id)
        if claim is None or ev is None:
            continue
        if qualify_evidence_for_claim(claim.claim_code, ev):
            continue

        link.validated = False
        link.method_version = ENGINE_VERSION
        link.rationale = (
            "Legacy broad parallel context quarantined by V2 precision "
            "qualification. Evidence retained; no REFUTE inferred."
        )
        quarantined += 1

    return quarantined


async def run_parallel_reality_bundle(
    target_rows: list[dict[str, Any]],
    *,
    max_cases: int = 12,
    max_families_per_claim: int = 4,
) -> dict[str, Any]:
    case_ids = []
    for row in target_rows:
        cid = int(row.get("case_id") or 0)
        if cid and cid not in case_ids:
            case_ids.append(cid)
        if len(case_ids) >= max_cases:
            break

    if not case_ids:
        return {
            "engine_version": ENGINE_VERSION,
            "cases": 0,
            "links_created": 0,
            "legacy_links_quarantined": 0,
            "claim_contexts": 0,
            "needed_source_groups": [],
            "claim_status_counts": {},
            "validation_ready_counts": {},
            "context_gap_counts": {},
            "details": {},
            "llm_calls": 0,
            "api_calls": 0,
        }

    async with async_session() as session:
        pairs = list(
            (
                await session.execute(
                    select(RadarCase, ProblemCandidate)
                    .join(
                        ProblemCandidate,
                        ProblemCandidate.id == RadarCase.candidate_id,
                    )
                    .where(RadarCase.id.in_(case_ids))
                )
            ).all()
        )
        claims = list(
            (
                await session.execute(
                    select(RadarClaim).where(
                        RadarClaim.case_id.in_(case_ids),
                        RadarClaim.claim_code.in_(TARGET_CODES),
                    )
                )
            ).scalars().all()
        )
        evidence = list(
            (
                await session.execute(
                    select(RadarEvidence).where(
                        RadarEvidence.case_id.in_(case_ids)
                    )
                )
            ).scalars().all()
        )

        claims_by_case: dict[int, dict[str, RadarClaim]] = defaultdict(dict)
        evidence_by_case: dict[int, list[RadarEvidence]] = defaultdict(list)
        evidence_by_id = {ev.id: ev for ev in evidence}

        for claim in claims:
            claims_by_case[claim.case_id][claim.claim_code] = claim
        for ev in evidence:
            evidence_by_case[ev.case_id].append(ev)

        legacy_quarantined = await _quarantine_legacy_weak_links(
            session,
            claims_by_case=claims_by_case,
            evidence_by_id=evidence_by_id,
        )

        links_created = 0
        claim_contexts = 0
        needed_groups: list[str] = []
        status_counts: dict[str, int] = defaultdict(int)
        validation_ready_counts: dict[str, int] = defaultdict(int)
        context_gap_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        details: dict[int, dict[str, Any]] = {}

        for case, candidate in pairs:
            case_detail = {
                "case_id": case.id,
                "title": candidate.title,
                "claims": {},
            }

            for code in TARGET_CODES:
                claim = claims_by_case.get(case.id, {}).get(code)
                if claim is None:
                    continue

                all_case_evidence = evidence_by_case.get(case.id, [])
                candidates = [
                    ev
                    for ev in all_case_evidence
                    if qualify_evidence_for_claim(code, ev)
                ]
                candidates.sort(
                    key=lambda ev: rank_evidence_for_claim(code, ev),
                    reverse=True,
                )

                selected = []
                seen_families = set()
                for ev in candidates:
                    family = str(ev.source_family_key or "").strip()
                    if not family or family in seen_families:
                        continue
                    seen_families.add(family)
                    selected.append(ev)
                    if len(selected) >= max_families_per_claim:
                        break

                for ev in selected:
                    links_created += int(
                        await _weak_link(
                            session,
                            claim,
                            ev,
                            code=code,
                        )
                    )

                await _refresh_claim_state(session, claim)

                summary = dict(claim.evidence_summary or {})
                reality = dict(summary.get("parallel_reality_v2") or {})
                status = str(
                    reality.get("status")
                    or summary.get("parallel_reality_v1", {}).get("status")
                    or "NO_PARALLEL_CONTEXT"
                )
                needs = list(
                    reality.get("needed_source_groups")
                    or summary.get("parallel_reality_v1", {}).get(
                        "needed_source_groups", []
                    )
                    or []
                )
                plan = reality.get("validation_plan")
                if plan:
                    validation_ready_counts[code] += 1

                for group in needs:
                    if group not in needed_groups:
                        needed_groups.append(group)

                if selected:
                    context_gap = "CONTEXT_SELECTED"
                elif not all_case_evidence:
                    context_gap = "NO_RADAR_EVIDENCE"
                elif not candidates:
                    context_gap = "NO_CLAIM_QUALIFIED_EVIDENCE"
                else:
                    context_gap = "NO_INDEPENDENT_FAMILY"
                context_gap_counts[code][context_gap] += 1

                bundle_block = {
                    "engine_version": ENGINE_VERSION,
                    "available_case_evidence": len(all_case_evidence),
                    "qualified_evidence": len(candidates),
                    "context_gap": context_gap,
                    "selected_evidence": len(selected),
                    "selected_families": len(seen_families),
                    "status": status,
                    "needed_source_groups": needs,
                    "precision_filtered": True,
                    "validation_plan_ready": bool(plan),
                    "updated_at": datetime.utcnow().isoformat(),
                    "support_created": False,
                    "warning": (
                        "This shared pass only develops qualified context. "
                        "Market-test-only claims remain unproven until real action."
                    ),
                }
                summary["parallel_bundle_research_v2"] = bundle_block
                claim.evidence_summary = summary
                claim.last_evaluated_at = datetime.utcnow()

                claim_contexts += 1
                status_counts[f"{code}:{status}"] += 1

                case_detail["claims"][code] = {
                    "state": str(claim.state or "UNKNOWN").upper(),
                    "status": status,
                    "selected_families": len(seen_families),
                    "needed_source_groups": needs,
                    "validation_plan_ready": bool(plan),
                }

            details[case.id] = case_detail

        await session.commit()

    return {
        "engine_version": ENGINE_VERSION,
        "cases": len(details),
        "links_created": links_created,
        "legacy_links_quarantined": legacy_quarantined,
        "claim_contexts": claim_contexts,
        "needed_source_groups": needed_groups,
        "claim_status_counts": dict(status_counts),
        "validation_ready_counts": dict(validation_ready_counts),
        "context_gap_counts": {
            code: dict(counts)
            for code, counts in context_gap_counts.items()
        },
        "details": details,
        "llm_calls": 0,
        "api_calls": 0,
    }
