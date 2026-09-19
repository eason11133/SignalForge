"""SignalForge real market ground truth V3 — quality locked.

Only a pre-registered, pending experiment may create real market evidence.
PASS requires an identified real actor. PRICE / PAID_PILOT PASS additionally
requires a positive amount and currency.

One negative experiment remains INSUFFICIENT. Evidence is never silently
converted into REFUTE.
"""

from __future__ import annotations

from datetime import datetime
import re
from typing import Any

from sqlalchemy import select

from database.connection import (
    async_session,
    ProblemCandidate,
    RadarCase,
    RadarClaim,
    RadarClaimEvidence,
)
from processors.opportunity_reality import (
    _ensure_evidence,
    _refresh_claim_state,
)
from processors.validation_registry import get_validation_experiment

ENGINE_VERSION = "market-ground-truth-v3-preregistered-quality-lock"

EVENT_TO_CLAIMS = {
    "ACQUISITION": ("C10",),
    "PRICE": ("C11",),
    "SWITCH": ("C14",),
    "PAID_PILOT": ("C10", "C11", "C14"),
}

EVENT_LABEL = {
    "ACQUISITION": "Target buyer acquisition experiment",
    "PRICE": "Price / willingness-to-pay experiment",
    "SWITCH": "Real workflow switching experiment",
    "PAID_PILOT": "Paid pilot with real workflow commitment",
}


def _actor_family(actor_label: str | None) -> str:
    raw = str(actor_label or "").strip().lower()
    if not raw:
        return "unidentified_actor"
    slug = re.sub(r"[^a-z0-9]+", "-", raw).strip("-")
    return slug[:80] or "unidentified_actor"


def validate_market_result_request(
    *,
    case_id: int,
    event: str,
    result: str,
    experiment_id: str,
    actor_label: str | None,
    amount: float | None,
    currency: str | None,
) -> dict[str, Any]:
    event = str(event or "").strip().upper().replace("-", "_")
    result = str(result or "").strip().upper()
    experiment_id = str(experiment_id or "").strip()

    if event not in EVENT_TO_CLAIMS:
        raise ValueError(
            "event must be one of: "
            + ", ".join(sorted(EVENT_TO_CLAIMS))
        )
    if result not in {"PASS", "FAIL"}:
        raise ValueError("result must be PASS or FAIL")
    if not experiment_id:
        raise ValueError(
            "experiment_id is required; unregistered market results "
            "cannot create SignalForge claim evidence"
        )

    registered = get_validation_experiment(experiment_id)
    if registered is None:
        raise ValueError(
            f"experiment {experiment_id} is not pre-registered"
        )
    if str(registered.get("status") or "").upper() != "PENDING":
        raise ValueError(
            f"experiment {experiment_id} is not pending"
        )
    if int(registered.get("case_id") or 0) != int(case_id):
        raise ValueError(
            "experiment case does not match --case"
        )

    registered_event = str(registered.get("event") or "").upper()
    registered_claim = str(registered.get("claim_code") or "").upper()

    allowed_event = registered_event
    # PAID_PILOT may satisfy acquisition/price semantics, but it is not
    # automatically a switching observation. C14 requires an explicit SWITCH
    # event and Part 6 verifies observed switch behavior before promotion.
    if event != allowed_event:
        if not (
            event == "PAID_PILOT"
            and registered_claim in {"C10", "C11"}
        ):
            raise ValueError(
                f"experiment event mismatch: registered={allowed_event}, "
                f"recorded={event}"
            )

    if result == "PASS":
        if not str(actor_label or "").strip():
            raise ValueError(
                "PASS requires --actor so independent buyer evidence "
                "cannot be fabricated from anonymous tests"
            )
        if event in {"PRICE", "PAID_PILOT"}:
            if amount is None or float(amount) <= 0:
                raise ValueError(
                    f"{event} PASS requires a positive --amount"
                )
            if not str(currency or "").strip():
                raise ValueError(
                    f"{event} PASS requires --currency"
                )

    return registered


async def _upsert_human_link(
    session,
    *,
    claim: RadarClaim,
    evidence,
    stance: str,
    rationale: str,
) -> None:
    link = (
        await session.execute(
            select(RadarClaimEvidence).where(
                RadarClaimEvidence.claim_id == claim.id,
                RadarClaimEvidence.evidence_id == evidence.id,
            )
        )
    ).scalar_one_or_none()

    if link is None:
        link = RadarClaimEvidence(
            claim_id=claim.id,
            evidence_id=evidence.id,
            stance=stance,
            interpretation_method="human_market_test",
            method_version=ENGINE_VERSION,
            interpretation_confidence=1.0,
            rationale=rationale,
            validated=True,
        )
        session.add(link)
    else:
        link.stance = stance
        link.interpretation_method = "human_market_test"
        link.method_version = ENGINE_VERSION
        link.interpretation_confidence = 1.0
        link.rationale = rationale
        link.validated = True


async def record_market_result(
    *,
    case_id: int,
    event: str,
    result: str,
    note: str,
    experiment_id: str,
    actor_label: str | None = None,
    amount: float | None = None,
    currency: str | None = None,
) -> dict[str, Any]:
    if not str(note or "").strip():
        raise ValueError("note is required")

    registered = validate_market_result_request(
        case_id=case_id,
        event=event,
        result=result,
        experiment_id=experiment_id,
        actor_label=actor_label,
        amount=amount,
        currency=currency,
    )

    event = str(event or "").strip().upper().replace("-", "_")
    result = str(result or "").strip().upper()
    # Claim experiments are claim-specific. Even a paid pilot may only update
    # the claim that was explicitly pre-registered. A separate C14 SWITCH
    # experiment is required for switching evidence.
    registered_claim = str(registered.get("claim_code") or "").upper()
    claim_codes = (registered_claim,)

    async with async_session() as session:
        pair = (
            await session.execute(
                select(RadarCase, ProblemCandidate)
                .join(
                    ProblemCandidate,
                    ProblemCandidate.id == RadarCase.candidate_id,
                )
                .where(RadarCase.id == int(case_id))
            )
        ).one_or_none()

        if pair is None:
            raise ValueError(f"case {case_id} not found")

        case, candidate = pair

        claims = list(
            (
                await session.execute(
                    select(RadarClaim).where(
                        RadarClaim.case_id == case.id,
                        RadarClaim.claim_code.in_(claim_codes),
                    )
                )
            ).scalars().all()
        )
        claim_map = {claim.claim_code: claim for claim in claims}

        missing = [code for code in claim_codes if code not in claim_map]
        if missing:
            raise ValueError(
                "missing claim(s): " + ", ".join(missing)
            )

        amount_text = ""
        if amount is not None:
            amount_text = (
                f" Amount={amount}"
                + (f" {currency}" if currency else "")
                + "."
            )

        source_ref = f"{event}:{experiment_id}:{result}"
        excerpt = (
            f"Pre-registered real market experiment. "
            f"Event={event}. Result={result}. "
            f"Actor={actor_label or 'not recorded'}. "
            f"Note={str(note).strip()}.{amount_text}"
        )

        evidence = await _ensure_evidence(
            session,
            case.id,
            source_type="human_market_test",
            source_table="validation_experiments",
            source_ref=source_ref,
            source_title=f"{EVENT_LABEL[event]} — {result}",
            excerpt=excerpt,
            source_url=None,
            source_family_key=(
                f"human_market_test:{case.id}:{_actor_family(actor_label)}"
            ),
            authority_class="PRIMARY",
            directness="DIRECT",
            published_at=datetime.utcnow(),
            metadata={
                "event": event,
                "result": result,
                "experiment_id": experiment_id,
                "registered_claim": registered_claim,
                "actor_label": actor_label,
                "amount": amount,
                "currency": currency,
                "human_recorded": True,
                "pre_registered": True,
                "pretest_snapshot": registered.get("pretest_snapshot"),
            },
        )

        stance = "SUPPORT" if result == "PASS" else "INSUFFICIENT"

        updated = []
        for code in claim_codes:
            claim = claim_map[code]
            rationale = (
                f"Pre-registered Founder market experiment "
                f"{experiment_id}: {event}={result}. "
                "PASS is PRIMARY/DIRECT evidence from an identified actor. "
                "FAIL remains INSUFFICIENT because one negative experiment "
                "cannot establish market impossibility."
            )

            await _upsert_human_link(
                session,
                claim=claim,
                evidence=evidence,
                stance=stance,
                rationale=rationale,
            )
            await _refresh_claim_state(session, claim)

            summary = dict(claim.evidence_summary or {})
            history = list(summary.get("market_ground_truth_v2") or [])
            history = [
                row for row in history
                if row.get("experiment_id") != experiment_id
            ]
            history.append({
                "experiment_id": experiment_id,
                "event": event,
                "result": result,
                "stance": stance,
                "recorded_at": datetime.utcnow().isoformat(),
                "actor_label": actor_label,
                "amount": amount,
                "currency": currency,
                "pre_registered": True,
            })
            summary["market_ground_truth_v2"] = history[-30:]
            claim.evidence_summary = summary

            updated.append({
                "claim_code": code,
                "state": str(claim.state or "UNKNOWN").upper(),
                "support_groups": int(claim.support_groups or 0),
                "refute_groups": int(claim.refute_groups or 0),
            })

        await session.commit()

    return {
        "engine_version": ENGINE_VERSION,
        "case_id": int(case_id),
        "title": candidate.title,
        "event": event,
        "result": result,
        "experiment_id": experiment_id,
        "stance": stance,
        "updated_claims": updated,
        "warning": (
            "Only pre-registered experiments can create market evidence. "
            "Repeated tests from one actor remain one source family. "
            "Normal independent support-group requirements still apply."
        ),
    }
