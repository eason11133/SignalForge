"""SignalForge historical replay engine V1.

Purpose:
- freeze evidence availability at an explicit historical cutoff,
- rebuild claim states from only evidence that existed by that cutoff,
- freeze the visible technology regime at the same cutoff,
- expose excluded future evidence and interpretation-time leakage risk,
- reconstruct a conservative evidence stage without pretending to know
  historical attention or future outcomes.

This is replay infrastructure, not proof that SignalForge predicts well.
Predictive credibility stays UNVALIDATED until replay outcomes and live market
ground truth exist.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
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
    _timing_enable,
    _erosion_signal,
    _platform_terms,
    _ev_text,
)

ENGINE_VERSION = "historical-replay-v3-forward-policy-snapshots"
REPORT_DIR = Path(".radar_runtime/replay")
FORWARD_POLICY_DIR = Path(".radar_runtime/policy_snapshots")

GATE_ORDER = [
    ("C03", "PAIN_MATERIALITY"),
    ("C05", "BUYER_REALITY"),
    ("C06", "CURRENT_SOLUTION"),
    ("C07", "UNRESOLVED_GAP"),
    ("C09", "COMPANY_REALITY"),
    ("C08", "DIFFERENTIATION"),
    ("C10", "DISTRIBUTION"),
    ("C11", "ECONOMICS"),
    ("C12", "OPPORTUNITY_WINDOW"),
    ("C13", "COMPETITION"),
    ("C14", "SWITCHING"),
]

VALIDATION_PREREQS = ("C03", "C05", "C06", "C07", "C09")


def _snapshot_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return _naive_utc(parsed)
    except Exception:
        return None


def _forward_snapshot_files() -> list[Path]:
    if not FORWARD_POLICY_DIR.exists():
        return []
    return sorted(FORWARD_POLICY_DIR.glob("policy_*.json"))


def find_forward_policy_snapshot(cutoff: datetime) -> dict[str, Any] | None:
    """Return the latest genuinely recorded policy snapshot at/before cutoff."""
    target = _naive_utc(cutoff) or datetime.utcnow()
    best: tuple[datetime, dict[str, Any], Path] | None = None
    for path in _forward_snapshot_files():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        recorded = _snapshot_timestamp(payload.get("recorded_at"))
        if recorded is None or recorded > target:
            continue
        if best is None or recorded > best[0]:
            best = (recorded, payload, path)
    if best is None:
        return None
    out = dict(best[1])
    out["snapshot_path"] = str(best[2])
    return out


async def capture_forward_policy_snapshot(
    *,
    decision: dict[str, Any] | None = None,
    source: str = "successful_cycle",
) -> dict[str, Any]:
    """Persist what SignalForge actually said now for future honest replay.

    This is forward-only evidence. It does not retroactively make older replay
    cutoffs policy-faithful.
    """
    if decision is None:
        from processors.opportunity_decision import run_opportunity_decision
        decision = await run_opportunity_decision(limit=50)

    now = datetime.utcnow()
    rows = []
    for row in decision.get("rows", []) or []:
        rows.append({
            "case_id": int(row.get("case_id") or 0),
            "candidate_id": row.get("candidate_id"),
            "title": row.get("title"),
            "decision_verdict": row.get("decision_verdict"),
            "current_gate": row.get("current_gate"),
            "attention_score": row.get("attention_score"),
            "market_validation_boundary": row.get("market_validation_boundary"),
            "claims": dict(row.get("claims") or {}),
        })

    payload = {
        "engine_version": ENGINE_VERSION,
        "recorded_at": now.isoformat(),
        "source": source,
        "decision_engine_version": decision.get("engine_version"),
        "build_locked": bool(decision.get("build_locked", True)),
        "verdict_counts": dict(decision.get("verdict_counts") or {}),
        "case_count": len(rows),
        "rows": rows,
        "forward_recorded_policy_truth": True,
        "predictive_accuracy_claimed": False,
    }
    FORWARD_POLICY_DIR.mkdir(parents=True, exist_ok=True)
    stamp = now.strftime("%Y%m%dT%H%M%S_%f")
    path = FORWARD_POLICY_DIR / f"policy_{stamp}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)
    payload["snapshot_path"] = str(path)
    return payload


def forward_policy_snapshot_status() -> dict[str, Any]:
    rows = []
    for path in _forward_snapshot_files():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        recorded = _snapshot_timestamp((payload or {}).get("recorded_at")) if isinstance(payload, dict) else None
        if recorded is not None:
            rows.append((recorded, path, payload))
    rows.sort(key=lambda x: x[0])
    latest = rows[-1] if rows else None
    return {
        "snapshot_count": len(rows),
        "latest_recorded_at": latest[0].isoformat() if latest else None,
        "latest_snapshot_path": str(latest[1]) if latest else None,
        "forward_recording_ready": True,
        "historical_policy_retroactively_fabricated": False,
    }


def _naive_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _evidence_time(ev: RadarEvidence) -> datetime | None:
    for name in ("published_at", "created_at", "collected_at"):
        value = getattr(ev, name, None)
        if isinstance(value, datetime):
            return _naive_utc(value)
    return None


def _link_time(link: RadarClaimEvidence) -> datetime | None:
    for name in ("created_at", "updated_at"):
        value = getattr(link, name, None)
        if isinstance(value, datetime):
            return _naive_utc(value)
    return None


def _state_from_rows(
    claim: RadarClaim,
    rows: list[tuple[RadarClaimEvidence, RadarEvidence]],
    *,
    cutoff: datetime,
) -> dict[str, Any]:
    support = set()
    refute = set()
    direct = set()
    weak = 0
    included = 0
    excluded_future = 0
    unknown_evidence_time = 0
    future_interpretation_excluded = 0
    interpretation_time_unknown = 0

    for link, ev in rows:
        if not bool(getattr(link, "validated", False)):
            continue

        ev_time = _evidence_time(ev)
        if ev_time is None:
            unknown_evidence_time += 1
            # Strict replay does not let undated evidence leak backwards.
            continue
        if ev_time > cutoff:
            excluded_future += 1
            continue

        link_time = _link_time(link)
        if link_time is not None and link_time > cutoff:
            future_interpretation_excluded += 1
            continue
        if link_time is None:
            interpretation_time_unknown += 1

        included += 1
        stance = str(getattr(link, "stance", "") or "").upper()
        family = str(getattr(ev, "source_family_key", "") or "").strip()
        if not family:
            family = f"evidence:{getattr(ev, 'id', 'unknown')}"

        if stance == "SUPPORT":
            support.add(family)
            if str(getattr(ev, "directness", "") or "").upper() == "DIRECT":
                direct.add(family)
        elif stance == "REFUTE":
            refute.add(family)
        elif stance in {"INSUFFICIENT", "RELATED"}:
            weak += 1

    needed = max(1, int(getattr(claim, "required_support_groups", 2) or 2))

    if refute and len(support) >= needed:
        state = "CONFLICTED"
    elif refute and not support:
        state = "REFUTED"
    elif len(support) >= needed:
        state = "SUPPORTED"
    elif included:
        state = "INSUFFICIENT"
    else:
        state = "UNKNOWN"

    return {
        "state": state,
        "required_support_groups": needed,
        "support_groups": len(support),
        "direct_support_groups": len(direct),
        "refute_groups": len(refute),
        "weak_links": weak,
        "included_links": included,
        "excluded_future_evidence": excluded_future,
        "unknown_evidence_time": unknown_evidence_time,
        "future_interpretation_excluded": future_interpretation_excluded,
        "interpretation_time_unknown": interpretation_time_unknown,
    }


def _replay_stage(
    claim_states: dict[str, str],
    blocking_codes: set[str],
) -> tuple[str, str]:
    if claim_states.get("C01") == "REFUTED":
        return "IGNORE", "PROBLEM_REALITY_REFUTED_AS_OF_CUTOFF"

    blockers = sorted(
        code for code in blocking_codes
        if claim_states.get(code) == "REFUTED"
    )
    if blockers:
        return "PARK", "BLOCKING_REFUTE:" + ",".join(blockers)

    if all(
        claim_states.get(code) == "SUPPORTED"
        for code in VALIDATION_PREREQS
    ):
        return (
            "VALIDATION_EVIDENCE_READY",
            "CORE_REALITY_PREREQS_SUPPORTED_AS_OF_CUTOFF",
        )

    for code, gate in GATE_ORDER:
        if claim_states.get(code, "UNKNOWN") not in {"SUPPORTED", "REFUTED"}:
            return "MACHINE_RESEARCH", gate

    return "DECISION_EVIDENCE_READY", "ALL_TRACKED_CLAIMS_RESOLVED"


def _technology_regime(
    evidence: list[RadarEvidence],
    *,
    cutoff: datetime,
) -> dict[str, Any]:
    visible = []
    excluded = 0
    unknown_time = 0

    for ev in evidence:
        ev_time = _evidence_time(ev)
        if ev_time is None:
            unknown_time += 1
            continue
        if ev_time > cutoff:
            excluded += 1
            continue
        visible.append(ev)

    enable_families = {
        str(ev.source_family_key or "")
        for ev in visible
        if _timing_enable(ev) and str(ev.source_family_key or "")
    }
    erosion_families = {
        str(ev.source_family_key or "")
        for ev in visible
        if _erosion_signal(ev) and str(ev.source_family_key or "")
    }
    text = "\n".join(_ev_text(ev) for ev in visible)
    platforms = _platform_terms(text)[:12]

    if len(enable_families) > len(erosion_families):
        balance = "ENABLEMENT_AHEAD"
    elif len(erosion_families) > len(enable_families):
        balance = "EROSION_AHEAD"
    elif enable_families or erosion_families:
        balance = "BALANCED_UNCERTAIN"
    else:
        balance = "THIN_TECH_REGIME_EVIDENCE"

    return {
        "enablement_families": len(enable_families),
        "erosion_families": len(erosion_families),
        "platform_terms": platforms,
        "balance": balance,
        "visible_evidence": len(visible),
        "excluded_future_evidence": excluded,
        "unknown_time_evidence": unknown_time,
        "is_forecast": False,
    }


async def run_historical_replay(
    *,
    cutoff: datetime,
    case_ids: list[int] | None = None,
    save_report: bool = True,
) -> dict[str, Any]:
    cutoff = _naive_utc(cutoff) or datetime.utcnow()

    async with async_session() as session:
        stmt = (
            select(RadarCase, ProblemCandidate)
            .join(
                ProblemCandidate,
                ProblemCandidate.id == RadarCase.candidate_id,
            )
            .order_by(RadarCase.id)
        )
        if case_ids:
            stmt = stmt.where(RadarCase.id.in_(case_ids))

        pairs = list((await session.execute(stmt)).all())
        ids = [case.id for case, _ in pairs]
        if not ids:
            return {
                "engine_version": ENGINE_VERSION,
                "cutoff": cutoff.isoformat(),
                "cases": 0,
                "rows": [],
                "leakage": {},
                "technology_regime": {},
                "predictive_accuracy": "UNVALIDATED",
                "policy_mode": "CURRENT_POLICY_ON_HISTORICAL_EVIDENCE",
                "policy_frozen_to_cutoff": False,
                "forward_policy_snapshot": find_forward_policy_snapshot(cutoff),
                "forward_policy_snapshot_available": find_forward_policy_snapshot(cutoff) is not None,
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
        claim_ids = [claim.id for claim in claims]
        links = []
        if claim_ids:
            links = list(
                (
                    await session.execute(
                        select(RadarClaimEvidence, RadarEvidence)
                        .join(
                            RadarEvidence,
                            RadarEvidence.id == RadarClaimEvidence.evidence_id,
                        )
                        .where(RadarClaimEvidence.claim_id.in_(claim_ids))
                    )
                ).all()
            )

        claims_by_case: dict[int, dict[str, RadarClaim]] = defaultdict(dict)
        links_by_claim: dict[int, list[tuple[RadarClaimEvidence, RadarEvidence]]] = defaultdict(list)
        evidence_by_case: dict[int, list[RadarEvidence]] = defaultdict(list)

        for claim in claims:
            claims_by_case[claim.case_id][claim.claim_code] = claim
        for link, ev in links:
            links_by_claim[link.claim_id].append((link, ev))
        for ev in evidence:
            evidence_by_case[ev.case_id].append(ev)

        rows = []
        leakage_totals = defaultdict(int)
        stage_counts = defaultdict(int)

        for case, candidate in pairs:
            claim_map = claims_by_case.get(case.id, {})
            claim_replay = {}
            blocking = set()

            for code, claim in claim_map.items():
                if bool(getattr(claim, "is_blocking", False)):
                    blocking.add(code)
                detail = _state_from_rows(
                    claim,
                    links_by_claim.get(claim.id, []),
                    cutoff=cutoff,
                )
                claim_replay[code] = detail
                for key in (
                    "excluded_future_evidence",
                    "unknown_evidence_time",
                    "future_interpretation_excluded",
                    "interpretation_time_unknown",
                ):
                    leakage_totals[key] += int(detail.get(key, 0) or 0)

            states = {
                code: detail["state"]
                for code, detail in claim_replay.items()
            }
            stage, reason = _replay_stage(states, blocking)
            stage_counts[stage] += 1

            rows.append({
                "case_id": case.id,
                "title": candidate.title,
                "replay_stage": stage,
                "replay_reason": reason,
                "claims": states,
                "claim_details": claim_replay,
                "technology_regime": _technology_regime(
                    evidence_by_case.get(case.id, []),
                    cutoff=cutoff,
                ),
            })

    report = {
        "engine_version": ENGINE_VERSION,
        "cutoff": cutoff.isoformat(),
        "generated_at": datetime.utcnow().isoformat(),
        "cases": len(rows),
        "stage_counts": dict(stage_counts),
        "rows": rows,
        "leakage": dict(leakage_totals),
        "predictive_accuracy": "UNVALIDATED",
        "policy_mode": "CURRENT_POLICY_ON_HISTORICAL_EVIDENCE",
        "policy_frozen_to_cutoff": False,
        "forward_policy_snapshot": find_forward_policy_snapshot(cutoff),
        "forward_policy_snapshot_available": find_forward_policy_snapshot(cutoff) is not None,
        "forward_policy_recording": forward_policy_snapshot_status(),
        "warning": (
            "Replay freezes evidence/link time where available, but currently "
            "applies today's SignalForge decision policy to historical evidence. "
            "This is a leakage-controlled evidence replay, NOT a claim that the "
            "historical system would have made the same decision at the cutoff. "
            "If historical interpretation timestamps are absent, the report "
            "flags interpretation_time_unknown instead of pretending zero leakage. "
            "M14 records actual policy/decision snapshots going forward; those "
            "snapshots improve future replay fidelity but never fabricate older policy."
        ),
    }

    if save_report:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        stamp = cutoff.strftime("%Y%m%dT%H%M%S")
        path = REPORT_DIR / f"replay_{stamp}.json"
        path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        report["report_path"] = str(path)

    return report


async def run_replay_series(
    *,
    days_back: list[int] | None = None,
) -> dict[str, Any]:
    days = sorted(
        set(int(x) for x in (days_back or [90, 60, 30, 0])),
        reverse=True,
    )
    now = datetime.utcnow()
    reports = []
    for days_ago in days:
        cutoff = now - timedelta(days=max(0, days_ago))
        reports.append(
            await run_historical_replay(
                cutoff=cutoff,
                save_report=True,
            )
        )

    return {
        "engine_version": ENGINE_VERSION,
        "series": [
            {
                "days_back": days_ago,
                "cutoff": report["cutoff"],
                "cases": report["cases"],
                "stage_counts": report["stage_counts"],
                "leakage": report["leakage"],
                "report_path": report.get("report_path"),
            }
            for days_ago, report in zip(days, reports)
        ],
        "predictive_accuracy": "UNVALIDATED",
        "policy_mode": "CURRENT_POLICY_ON_HISTORICAL_EVIDENCE",
        "policy_frozen_to_cutoff": False,
        "forward_policy_recording": forward_policy_snapshot_status(),
    }
