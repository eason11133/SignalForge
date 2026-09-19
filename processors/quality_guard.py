"""SignalForge runtime quality guard V1.

Purpose:
- audit the current Evidence Ledger and Decision output for known false-positive
  paths,
- snapshot mutable claim/link state before research,
- automatically roll back new claim/link mutations if a new critical regression
  appears after a research cycle.

Evidence rows themselves are never deleted. New links created by a failed cycle
are retained for audit but invalidated.
"""

from __future__ import annotations

import copy
import re
from collections import defaultdict
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
from processors.calibration import calibration_report
from processors.validation_registry import validation_registry_report

ENGINE_VERSION = "quality-guard-v2-ledger-repair"

STRICT_LEDGER_CODES = {
    "C03", "C05", "C06", "C07", "C08", "C10", "C11", "C12", "C13", "C14",
}

WEAK_METHOD_PREFIXES = (
    "parallel_reality_context",
    "parallel_reality_context_precise",
)

LOAD_TERMS = re.compile(
    r"\b(?:under load|overload|high load|concurren|traffic|rps|"
    r"queue|capacity|parallel requests|throughput|many requests)\b",
    re.I,
)

LATENCY_NEGATIVE = re.compile(
    r"\b(?:slow|latency|response time|delay|timeout|time[- ]to[- ]first)\b",
    re.I,
)
LATENCY_POSITIVE = re.compile(
    r"\b(?:ultrafast|low latency|faster|speedup|reduced latency|34 ms|"
    r"milliseconds)\b",
    re.I,
)


def _link_payload(link: RadarClaimEvidence) -> dict[str, Any]:
    return {
        "stance": link.stance,
        "validated": bool(link.validated),
        "interpretation_method": link.interpretation_method,
        "method_version": link.method_version,
        "interpretation_confidence": link.interpretation_confidence,
        "rationale": link.rationale,
    }


def _claim_payload(claim: RadarClaim) -> dict[str, Any]:
    return {
        "state": claim.state,
        "support_groups": claim.support_groups,
        "direct_support_groups": claim.direct_support_groups,
        "refute_groups": claim.refute_groups,
        "insufficient_count": claim.insufficient_count,
        "evidence_summary": copy.deepcopy(claim.evidence_summary or {}),
        "last_evaluated_at": claim.last_evaluated_at,
    }


async def capture_quality_snapshot() -> dict[str, Any]:
    async with async_session() as session:
        claims = list(
            (await session.execute(select(RadarClaim))).scalars().all()
        )
        links = list(
            (await session.execute(select(RadarClaimEvidence))).scalars().all()
        )

    return {
        "engine_version": ENGINE_VERSION,
        "claims": {
            int(claim.id): _claim_payload(claim)
            for claim in claims
        },
        "links": {
            int(link.id): _link_payload(link)
            for link in links
        },
    }


async def rollback_quality_snapshot(snapshot: dict[str, Any]) -> dict[str, int]:
    claim_snap = snapshot.get("claims") or {}
    link_snap = snapshot.get("links") or {}

    restored_claims = 0
    reset_new_claims = 0
    restored_links = 0
    invalidated_new_links = 0

    async with async_session() as session:
        claims = list(
            (await session.execute(select(RadarClaim))).scalars().all()
        )
        links = list(
            (await session.execute(select(RadarClaimEvidence))).scalars().all()
        )

        for claim in claims:
            saved = claim_snap.get(int(claim.id))
            if not saved:
                # Claims created after the snapshot (for example by bounded M14
                # discovery) have no previous truth to restore. On a critical
                # regression, keep the case/evidence for auditability but reset
                # the new claim conservatively so invalidated new links cannot
                # leave a synthetic positive state behind.
                claim.state = "UNKNOWN"
                claim.support_groups = 0
                claim.direct_support_groups = 0
                claim.refute_groups = 0
                claim.insufficient_count = 0
                claim.evidence_summary = {
                    "quality_guard_rollback": {
                        "engine_version": ENGINE_VERSION,
                        "reason": "claim_created_after_quality_snapshot",
                    }
                }
                claim.last_evaluated_at = None
                reset_new_claims += 1
                continue
            for field, value in saved.items():
                setattr(claim, field, copy.deepcopy(value))
            restored_claims += 1

        for link in links:
            saved = link_snap.get(int(link.id))
            if saved:
                for field, value in saved.items():
                    setattr(link, field, value)
                restored_links += 1
                continue

            if bool(link.validated):
                link.validated = False
                link.rationale = (
                    "Retained but invalidated by SignalForge Quality Guard "
                    "because the research cycle introduced a critical regression."
                )
                link.method_version = ENGINE_VERSION
                invalidated_new_links += 1

        await session.commit()

    return {
        "restored_claims": restored_claims,
        "reset_new_claims": reset_new_claims,
        "restored_links": restored_links,
        "invalidated_new_links": invalidated_new_links,
    }


def _registered_experiment_ids() -> set[str]:
    report = validation_registry_report()
    return {
        str(row.get("experiment_id"))
        for row in report.get("rows", [])
        if row.get("experiment_id")
    }


async def repair_ledger_state_from_validated_links() -> dict[str, Any]:
    """Deterministically reconcile claim state with the current validated ledger.

    This is a quality repair, not threshold weakening:
    - SUPPORT still requires the claim's configured independent-family threshold.
    - Evidence/link rows are never deleted or relabeled.
    - Claims that were historically marked SUPPORTED below threshold are
      downgraded to the state implied by the current validated links.
    """
    changed: list[dict[str, Any]] = []
    checked = 0

    async with async_session() as session:
        claims = list(
            (
                await session.execute(
                    select(RadarClaim).where(
                        RadarClaim.claim_code.in_(STRICT_LEDGER_CODES)
                    )
                )
            ).scalars().all()
        )

        claim_ids = [int(claim.id) for claim in claims]
        rows = []
        if claim_ids:
            rows = list(
                (
                    await session.execute(
                        select(RadarClaimEvidence, RadarEvidence)
                        .join(
                            RadarEvidence,
                            RadarEvidence.id
                            == RadarClaimEvidence.evidence_id,
                        )
                        .where(
                            RadarClaimEvidence.claim_id.in_(claim_ids)
                        )
                    )
                ).all()
            )

        by_claim: dict[int, list[tuple[Any, Any]]] = defaultdict(list)
        for link, ev in rows:
            by_claim[int(link.claim_id)].append((link, ev))

        for claim in claims:
            checked += 1
            related = by_claim.get(int(claim.id), [])

            support = {
                str(ev.source_family_key or f"evidence:{ev.id}")
                for link, ev in related
                if bool(link.validated)
                and str(link.stance or "").upper() == "SUPPORT"
            }
            refute = {
                str(ev.source_family_key or f"evidence:{ev.id}")
                for link, ev in related
                if bool(link.validated)
                and str(link.stance or "").upper() == "REFUTE"
            }
            direct = {
                str(ev.source_family_key or f"evidence:{ev.id}")
                for link, ev in related
                if bool(link.validated)
                and str(link.stance or "").upper() == "SUPPORT"
                and str(ev.directness or "").upper() == "DIRECT"
            }
            weak_count = sum(
                1
                for link, _ in related
                if bool(link.validated)
                and str(link.stance or "").upper()
                in {"INSUFFICIENT", "RELATED"}
            )

            needed = max(
                1,
                int(getattr(claim, "required_support_groups", 2) or 2),
            )

            if refute and len(support) >= needed:
                derived_state = "CONFLICTED"
            elif refute and not support:
                derived_state = "REFUTED"
            elif len(support) >= needed:
                derived_state = "SUPPORTED"
            elif related:
                derived_state = "INSUFFICIENT"
            else:
                derived_state = "UNKNOWN"

            before = {
                "state": str(claim.state or "UNKNOWN").upper(),
                "support_groups": int(claim.support_groups or 0),
                "direct_support_groups": int(
                    claim.direct_support_groups or 0
                ),
                "refute_groups": int(claim.refute_groups or 0),
                "insufficient_count": int(claim.insufficient_count or 0),
            }
            after = {
                "state": derived_state,
                "support_groups": len(support),
                "direct_support_groups": len(direct),
                "refute_groups": len(refute),
                "insufficient_count": weak_count,
            }

            if before != after:
                claim.state = derived_state
                claim.support_groups = len(support)
                claim.direct_support_groups = len(direct)
                claim.refute_groups = len(refute)
                claim.insufficient_count = weak_count

                summary = dict(claim.evidence_summary or {})
                summary["quality_ledger_repair_v2"] = {
                    "reason": (
                        "Claim state reconciled to current validated "
                        "independent evidence families."
                    ),
                    "previous": before,
                    "derived": after,
                    "required_support_groups": needed,
                    "threshold_weakened": False,
                }
                claim.evidence_summary = summary

                changed.append({
                    "case_id": int(claim.case_id),
                    "claim": str(claim.claim_code),
                    "before": before,
                    "after": after,
                    "required": needed,
                })

        await session.commit()

    counts: dict[str, int] = defaultdict(int)
    for row in changed:
        counts[str(row["claim"])] += 1

    return {
        "engine_version": ENGINE_VERSION,
        "checked_claims": checked,
        "changed_claims": len(changed),
        "changed_by_code": dict(sorted(counts.items())),
        "changes": changed,
        "thresholds_weakened": False,
        "links_deleted": 0,
        "evidence_deleted": 0,
    }


async def audit_quality(
    *,
    decision: dict[str, Any] | None = None,
) -> dict[str, Any]:
    critical: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    async with async_session() as session:
        claims = list(
            (await session.execute(select(RadarClaim))).scalars().all()
        )
        rows = list(
            (
                await session.execute(
                    select(
                        RadarClaimEvidence,
                        RadarEvidence,
                        RadarClaim,
                        RadarCase,
                        ProblemCandidate,
                    )
                    .join(
                        RadarEvidence,
                        RadarEvidence.id == RadarClaimEvidence.evidence_id,
                    )
                    .join(
                        RadarClaim,
                        RadarClaim.id == RadarClaimEvidence.claim_id,
                    )
                    .join(
                        RadarCase,
                        RadarCase.id == RadarClaim.case_id,
                    )
                    .join(
                        ProblemCandidate,
                        ProblemCandidate.id == RadarCase.candidate_id,
                    )
                )
            ).all()
        )

    links_by_claim: dict[int, list[tuple[Any, ...]]] = defaultdict(list)
    for row in rows:
        link, ev, claim, case, candidate = row
        links_by_claim[int(claim.id)].append(row)

    registered_ids = _registered_experiment_ids()

    for claim in claims:
        related = links_by_claim.get(int(claim.id), [])
        support_families = {
            str(ev.source_family_key or f"evidence:{ev.id}")
            for link, ev, *_ in related
            if bool(link.validated)
            and str(link.stance or "").upper() == "SUPPORT"
        }
        refute_families = {
            str(ev.source_family_key or f"evidence:{ev.id}")
            for link, ev, *_ in related
            if bool(link.validated)
            and str(link.stance or "").upper() == "REFUTE"
        }
        needed = max(
            1,
            int(getattr(claim, "required_support_groups", 2) or 2),
        )
        state = str(claim.state or "UNKNOWN").upper()

        if (
            state == "SUPPORTED"
            and str(claim.claim_code or "").upper() in STRICT_LEDGER_CODES
            and len(support_families) < needed
        ):
            critical.append({
                "type": "SUPPORTED_BELOW_THRESHOLD",
                "case_id": claim.case_id,
                "claim": claim.claim_code,
                "support_families": len(support_families),
                "required": needed,
            })
        if state == "REFUTED" and not refute_families:
            warnings.append({
                "type": "REFUTED_WITHOUT_CURRENT_REFUTE_LINK",
                "case_id": claim.case_id,
                "claim": claim.claim_code,
            })

        for link, ev, _, case, candidate in related:
            if not bool(link.validated):
                continue
            stance = str(link.stance or "").upper()
            if stance != "SUPPORT":
                continue

            method = str(link.interpretation_method or "").lower()
            stype = str(ev.source_type or "").lower()
            text = " ".join([
                str(ev.source_title or ""),
                str(ev.excerpt or ""),
            ])

            if any(method.startswith(prefix) for prefix in WEAK_METHOD_PREFIXES):
                critical.append({
                    "type": "WEAK_CONTEXT_BECAME_SUPPORT",
                    "case_id": case.id,
                    "claim": claim.claim_code,
                    "evidence_id": ev.id,
                    "method": method,
                })

            if claim.claim_code == "C11" and (
                stype.startswith("job") or "hiring" in stype
            ):
                critical.append({
                    "type": "JOB_COMPENSATION_AS_WTP",
                    "case_id": case.id,
                    "evidence_id": ev.id,
                })

            if stype == "human_market_test":
                metadata_raw = (
                    getattr(ev, "metadata", None)
                    or getattr(ev, "raw_metadata", None)
                    or getattr(ev, "metadata_json", None)
                    or {}
                )
                metadata = (
                    dict(metadata_raw)
                    if isinstance(metadata_raw, dict)
                    else {}
                )
                experiment_id = str(
                    metadata.get("experiment_id") or ""
                ).strip()
                actor = str(
                    metadata.get("actor_label") or ""
                ).strip()
                if not experiment_id or experiment_id not in registered_ids:
                    critical.append({
                        "type": "UNREGISTERED_MARKET_SUPPORT",
                        "case_id": case.id,
                        "claim": claim.claim_code,
                        "evidence_id": ev.id,
                    })
                if not actor:
                    critical.append({
                        "type": "ANONYMOUS_ACTOR_MARKET_SUPPORT",
                        "case_id": case.id,
                        "claim": claim.claim_code,
                        "evidence_id": ev.id,
                    })

            title = str(candidate.title or "").lower()
            if (
                claim.claim_code == "C06"
                and "slow response" in title
                and LATENCY_POSITIVE.search(text)
                and not LATENCY_NEGATIVE.search(text)
            ):
                critical.append({
                    "type": "LATENCY_DIRECTION_REGRESSION",
                    "case_id": case.id,
                    "evidence_id": ev.id,
                })

            if (
                claim.claim_code == "C06"
                and "under load" in title
                and not LOAD_TERMS.search(text)
            ):
                critical.append({
                    "type": "LOAD_MECHANISM_REGRESSION",
                    "case_id": case.id,
                    "evidence_id": ev.id,
                })

    if decision is not None:
        if decision.get("build_locked") is not True:
            critical.append({
                "type": "BUILD_LOCK_REGRESSION",
            })

        for row in decision.get("rows", []) or []:
            if str(row.get("decision_verdict") or "").upper() != "VALIDATE":
                continue
            claims_state = row.get("claims") or {}
            missing = [
                code
                for code in ("C03", "C05", "C06", "C07", "C09")
                if str(claims_state.get(code, "UNKNOWN")).upper()
                != "SUPPORTED"
            ]
            if missing:
                critical.append({
                    "type": "VALIDATE_WITH_MISSING_PREREQUISITES",
                    "case_id": row.get("case_id"),
                    "missing": missing,
                })

    calibration = calibration_report()
    completed = int(calibration.get("completed_experiments", 0) or 0)
    credibility = calibration.get("credibility") or {}
    if completed < 10 and credibility.get("status") != "UNVALIDATED":
        critical.append({
            "type": "CALIBRATION_OVERCLAIM",
            "completed": completed,
            "status": credibility.get("status"),
        })

    return {
        "engine_version": ENGINE_VERSION,
        "status": "PASS" if not critical else "FAIL",
        "critical_count": len(critical),
        "warning_count": len(warnings),
        "critical": critical,
        "warnings": warnings,
    }
