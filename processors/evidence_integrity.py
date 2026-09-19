"""Radar Evidence Integrity Gate V1.

Purpose:
Prevent earlier broad deterministic retrieval from remaining as production
SUPPORT after stricter focused adjudicators exist.

C05/C06/C07 SUPPORT is trusted only when:
- narrow AI explicitly adjudicated supplied evidence; or
- interpretation is explicitly human/manual.

All other legacy deterministic SUPPORT is downgraded to INSUFFICIENT.
This is not evidence deletion and not REFUTE.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from sqlalchemy import select

from database.connection import (
    async_session,
    RadarClaim,
    RadarClaimEvidence,
    RadarEvidence,
)
from processors.opportunity_reality import _refresh_claim_state

ENGINE_VERSION = "evidence-integrity-gate-v3-direction-mechanism"
TARGET_CODES = {"C05", "C06", "C07"}


def _trusted(
    claim: RadarClaim,
    link: RadarClaimEvidence,
) -> bool:
    rationale = str(link.rationale or "").lower()
    method = str(link.interpretation_method or "").lower()
    version = str(link.method_version or "").lower()

    if "human" in method or "manual" in method:
        return True
    if "human" in rationale and "validated" in rationale:
        return True

    # Focused buyer adjudication remains valid for C05.
    if claim.claim_code == "C05":
        return "narrow ai" in rationale

    # C06/C07 are stricter: broad solution similarity is insufficient.
    # Production SUPPORT must explicitly pass the same-underlying-problem gate.
    if claim.claim_code in {"C06", "C07"}:
        return (
            "same-problem verified" in rationale
            or "same_problem_verified" in method
            or "same-problem" in version
        )

    return False


async def run_evidence_integrity_reconcile() -> dict:
    async with async_session() as session:
        rows = list((await session.execute(
            select(RadarClaim, RadarClaimEvidence, RadarEvidence)
            .join(
                RadarClaimEvidence,
                RadarClaimEvidence.claim_id == RadarClaim.id,
            )
            .join(
                RadarEvidence,
                RadarEvidence.id == RadarClaimEvidence.evidence_id,
            )
            .where(
                RadarClaim.claim_code.in_(TARGET_CODES),
                RadarClaimEvidence.validated == True,  # noqa: E712
                RadarClaimEvidence.stance == "SUPPORT",
            )
        )).all())

        quarantined = defaultdict(int)
        preserved = defaultdict(int)
        affected_claim_ids = set()

        for claim, link, evidence in rows:
            if _trusted(claim, link):
                preserved[claim.claim_code] += 1
                continue

            old_rationale = str(link.rationale or "").strip()
            link.stance = "INSUFFICIENT"
            link.interpretation_method = "integrity_reconcile"
            link.method_version = ENGINE_VERSION
            link.interpretation_confidence = min(
                float(link.interpretation_confidence or 0.45),
                0.45,
            )
            link.rationale = (
                "Quarantined legacy deterministic SUPPORT. Production "
                "C05 requires focused buyer adjudication; C06/C07 require ""same-underlying-problem verification or "
                "explicit human validation. Original interpretation: "
                + old_rationale[:1200]
            )
            link.validated = True

            quarantined[claim.claim_code] += 1
            affected_claim_ids.add(claim.id)

        affected_claims = []
        if affected_claim_ids:
            affected_claims = list((await session.execute(
                select(RadarClaim).where(
                    RadarClaim.id.in_(affected_claim_ids)
                )
            )).scalars().all())

        for claim in affected_claims:
            await _refresh_claim_state(session, claim)

            summary = dict(claim.evidence_summary or {})
            status_key = {
                "C05": "buyer_research_status_v1",
                "C06": "solution_research_status_v1",
                "C07": "gap_research_status_v1",
            }.get(claim.claim_code)

            if status_key:
                block = summary.get(status_key)
                if (
                    isinstance(block, dict)
                    and str(block.get("status") or "").upper()
                    == "SUPPORTED"
                    and str(claim.state or "").upper() != "SUPPORTED"
                ):
                    block = dict(block)
                    block["status"] = "REQUIRES_REVALIDATION"
                    block["integrity_reconciled_at"] = (
                        datetime.utcnow().isoformat()
                    )
                    block["reason"] = (
                        "Legacy deterministic SUPPORT was quarantined."
                    )
                    summary[status_key] = block
                    claim.evidence_summary = summary

        await session.commit()

    return {
        "engine_version": ENGINE_VERSION,
        "support_rows_seen": len(rows),
        "quarantined": dict(quarantined),
        "preserved": dict(preserved),
        "affected_claims": len(affected_claim_ids),
    }
