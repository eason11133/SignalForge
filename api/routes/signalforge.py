from __future__ import annotations

import asyncio
import json
import os
import secrets
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException
from sqlalchemy import select

from database.connection import (
    async_session,
    ProblemCandidate,
    CandidateEvidence,
    RadarCase,
    RadarClaim,
    RadarClaimEvidence,
    RadarEvidence,
)

from processors.signalforge_runtime import get_signalforge_runtime_status, launch_signalforge_cycle_nonblocking
from processors.system_wide_audit import run_system_wide_audit
from processors.solo_transition_opportunity import assess_solo_transition
from spending_tracker import get_spending_data

router = APIRouter()
SNAPSHOT = Path('.radar_runtime/founder_daily.json')
_research_more_lock = asyncio.Lock()


def _load_published_daily() -> dict:
    if not SNAPSHOT.exists():
        return {}
    try:
        raw = json.loads(SNAPSHOT.read_text(encoding='utf-8'))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


@router.get('/daily')
async def daily():
    runtime = get_signalforge_runtime_status()
    snapshot = _load_published_daily()
    if not snapshot:
        return {
            'status': 'NO_PUBLISHED_SNAPSHOT',
            'published': False,
            'runtime': runtime,
            'spending': get_spending_data(),
            'cards': [],
        }
    snapshot = dict(snapshot)
    snapshot['published'] = True
    snapshot['runtime'] = runtime
    snapshot['spending'] = get_spending_data()
    return snapshot


@router.get('/status')
async def status():
    return get_signalforge_runtime_status()


@router.get('/live-acceptance')
async def live_acceptance_r9():
    """Compact live-engineering evidence; never a market-accuracy verdict."""
    from processors.signalforge_market_action_registry import build_market_action_queue

    runtime = get_signalforge_runtime_status()
    attempt = runtime.get('last_attempt_cycle') or {}
    brain = attempt.get('brain_refresh') or {}
    routing = attempt.get('post_brain_routing') or {}
    coherence = attempt.get('strategic_routing_coherence') or {}
    warm = attempt.get('warm_cache_readiness') or {}
    published = _load_published_daily()
    actions = build_market_action_queue(limit=100)

    checks = {
        'runtime_pass': str(runtime.get('status') or '').upper() == 'PASS',
        'last_attempt_pass': str(runtime.get('last_attempt_status') or '').upper() == 'PASS',
        'worker_stopped': not bool(runtime.get('running')) and not bool((runtime.get('dispatch') or {}).get('worker_alive')),
        'brain_refresh_pass': str(brain.get('status') or '').upper() in {'PASS', 'PASS_EMPTY'},
        'strategic_routing_coherent': str(coherence.get('status') or '').upper() == 'PASS',
    }
    return {
        'engine_version': 'signalforge-live-acceptance-r9',
        'engineering_live_gate': 'PASS' if all(checks.values()) else 'PENDING_OR_FAIL',
        'checks': checks,
        'runtime_engine': runtime.get('engine_version'),
        'last_attempt_error': runtime.get('last_attempt_error'),
        'phase_seconds': attempt.get('phase_seconds') or {},
        'brain_refresh': {
            'status': brain.get('status'),
            'refreshed_at': brain.get('refreshed_at'),
            'strategic_summary': brain.get('strategic_summary') or {},
        },
        'post_brain_routing': routing,
        'strategic_routing_coherence': coherence,
        'warm_cache_readiness': warm,
        'published_operating_counts': (published.get('operating_queue') or {}).get('counts') or {},
        'founder_action_queue_count': int(actions.get('count', 0) or 0),
        'founder_action_queue': actions.get('items') or [],
        'market_calibration_claimed': False,
        'truth_boundary': 'LIVE_ACCEPTANCE_SUMMARY_IS_ENGINEERING_EXECUTION_EVIDENCE_ONLY_NOT_PRODUCT_SUCCESS_OR_MARKET_ACCURACY',
    }


@router.post('/trigger', status_code=202)
async def trigger():
    # R3: dispatch the heavy cycle into a separate Python process. Returning
    # from this route must never depend on the research cycle yielding back to
    # the FastAPI event loop.
    return launch_signalforge_cycle_nonblocking(force=True, reason='manual_api')


@router.get('/audit')
async def audit():
    return await run_system_wide_audit()


def _evidence_payload(claim: RadarClaim, link: RadarClaimEvidence, ev: RadarEvidence) -> dict:
    return {
        "claim_code": str(claim.claim_code or ""),
        "claim_state": str(claim.state or "UNKNOWN"),
        "stance": str(link.stance or "INSUFFICIENT"),
        "validated": bool(link.validated),
        "interpretation_confidence": link.interpretation_confidence,
        "rationale": str(link.rationale or ""),
        "source_type": str(ev.source_type or ""),
        "source_title": str(ev.source_title or ""),
        "excerpt": str(ev.excerpt or "")[:1400],
        "source_url": ev.source_url,
        "source_family_key": str(ev.source_family_key or ""),
        "directness": str(ev.directness or ""),
        "authority_class": str(ev.authority_class or ""),
        "raw_metadata": {
            key: value for key, value in dict(ev.raw_metadata or {}).items()
            if key in {"solution_identity", "solution", "product", "tool", "competitor", "alternative", "company", "buyer", "status", "source"}
        },
    }


def _metadata_names(rows: list[dict], keys: tuple[str, ...]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if not row.get("validated"):
            continue
        md = row.get("raw_metadata") or {}
        for key in keys:
            value = md.get(key)
            if isinstance(value, str):
                value = value.strip()
                if value and value.lower() not in seen:
                    seen.add(value.lower())
                    out.append(value)
                break
    return out[:20]


def _solution_names(rows: list[dict]) -> list[str]:
    # A competitor name is not automatically a current solution. Keep the
    # classes separate so the Founder UI does not turn market context into truth.
    return _metadata_names(
        rows,
        ("solution_identity", "solution", "product", "tool"),
    )


def _competitive_names(rows: list[dict]) -> list[str]:
    return _metadata_names(rows, ("competitor", "alternative"))


def _failure_reasons(rows: list[dict]) -> list[str]:
    # Only validated C07 SUPPORT may become a stated reason the gap persists.
    # UNKNOWN / INSUFFICIENT stays unknown; the UI must not complete the story.
    out: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if row.get("claim_code") != "C07" or row.get("stance") != "SUPPORT" or not row.get("validated"):
            continue
        text = str(row.get("excerpt") or row.get("rationale") or "").strip()
        if text and text.lower() not in seen:
            seen.add(text.lower())
            out.append(text[:1200])
    return out[:8]


def _compact_candidate_evidence(row: CandidateEvidence) -> dict:
    md = dict(row.evidence_metadata or {})
    return {
        "id": int(row.id),
        "source_type": str(row.source_type or ""),
        "source_table": row.source_table,
        "source_ref": row.source_ref,
        "relation": str(row.relation or ""),
        "title": row.title,
        "excerpt": str(row.excerpt or "")[:1400],
        "url": row.url,
        "retrieval_score": row.retrieval_score,
        "verified": bool(row.verified),
        "verification_confidence": row.verification_confidence,
        "metadata": {
            key: value for key, value in md.items()
            if key in {"solution_identity", "solution", "product", "tool", "competitor", "alternative", "company", "buyer", "status", "source"}
        },
    }


def _candidate_core(row: ProblemCandidate) -> dict:
    return {
        "id": int(row.id),
        "canonical_key": str(row.canonical_key or ""),
        "title": str(row.title or ""),
        "problem_statement": row.problem_statement,
        "actor": row.actor,
        "actor_category": row.actor_category,
        "task": row.task,
        "object": row.object,
        "failure_mode": row.failure_mode,
        "consequence": row.consequence,
        "buyer_context": row.buyer_context,
        "workaround": row.workaround,
        "community_platform": row.community_platform,
        "discussion_key": row.discussion_key,
        "community_evidence_count": int(row.community_evidence_count or 0),
        "community_user_count": int(row.community_user_count or 0),
        "stage": str(row.stage or "candidate"),
        "founder_status": str(row.founder_status or "new"),
        "market_score": float(row.market_score or 0),
        "confidence_score": float(row.confidence_score or 0),
        "community_problem_score": float(row.community_problem_score or 0),
        "corroboration_score": float(row.corroboration_score or 0),
        "buyer_demand_score": float(row.buyer_demand_score or 0),
        "supply_gap_score": float(row.supply_gap_score or 0),
        "cross_source_score": float(row.cross_source_score or 0),
        "source_support": dict(row.source_support or {}),
        "relation_support": dict(row.relation_support or {}),
        "fingerprint": dict(row.fingerprint or {}),
        "first_seen_at": row.first_seen_at,
        "last_seen_at": row.last_seen_at,
        "calculated_at": row.calculated_at,
        "updated_at": row.updated_at,
    }




def _research_card_id(candidate_id: int) -> str:
    return f"candidate:{candidate_id}"


def _research_base_query(candidate: ProblemCandidate) -> str:
    parts = [
        candidate.title,
        candidate.problem_statement,
        candidate.actor,
        candidate.task,
        candidate.failure_mode,
        candidate.consequence,
    ]
    seen: set[str] = set()
    out: list[str] = []
    for value in parts:
        text = str(value or "").strip()
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            out.append(text)
    return " | ".join(out)[:1600] or f"candidate {candidate.id}"


def _u15_recent_requests(card_id: str, limit: int = 8) -> list[dict]:
    state_path = Path('.radar_runtime/founder_directed_research_u15.json')
    if not state_path.exists():
        return []
    try:
        raw = json.loads(state_path.read_text(encoding='utf-8'))
    except Exception:
        return []
    rows = [row for row in (raw.get('requests') or []) if str(row.get('card_id') or '') == card_id]
    return rows[-limit:][::-1]


def _serialize_research_progress(store, card_id: str) -> dict:
    try:
        progress = store.card_progress(card_id, 0.08)
    except Exception as exc:
        return {
            'status': 'RESEARCH_STATE_ERROR',
            'error': f'{type(exc).__name__}: {exc}',
            'best_next_research': None,
            'gap_progress': [],
        }
    return {
        'status': 'OK',
        'thesis_id': progress.get('thesis_id'),
        'best_next_research': progress.get('best_next_research'),
        'gap_progress': progress.get('gap_progress') or [],
    }


def _initial_best_next_research(claim_states: dict[str, str], solo_assessment: dict) -> dict:
    priority = []
    next_gate = str((solo_assessment or {}).get("next_gate") or "").strip()
    if next_gate:
        priority.append({
            "gate": next_gate,
            "why": "Current published assessment identifies this as the next unresolved opportunity gate.",
        })
    for code, label in (
        ("C05", "Find DIRECT thesis-specific buyer / budget evidence"),
        ("C07", "Find evidence the same gap remains unresolved despite existing solutions"),
        ("C11", "Prefer a bounded buyer/price test when WTP is the remaining decision-critical unknown"),
    ):
        state = str((claim_states or {}).get(code) or "UNKNOWN").upper()
        if state in {"INSUFFICIENT", "UNKNOWN"}:
            priority.append({"claim_code": code, "state": state, "action": label})
    if not priority:
        priority.append({"action": "Research the highest-risk UNKNOWN/INSUFFICIENT claim before changing Published truth."})
    return {
        "mode": "FOUNDER_FIRST_USE_DETERMINISTIC",
        "priority": priority[:4],
        "truth_boundary": "Guidance only. It cannot promote a Published claim.",
    }


@router.get('/opportunity/{candidate_id}/research-state')
async def opportunity_research_state(candidate_id: int):
    """Read SHADOW founder-directed research state. Never mutates published claim truth.

    The initial recommendation is derived in this request from current Published truth.
    It does not depend on another endpoint populating an in-process cache.
    """
    async with async_session() as session:
        candidate = (
            await session.execute(
                select(ProblemCandidate).where(ProblemCandidate.id == candidate_id).limit(1)
            )
        ).scalars().first()
        case = (
            await session.execute(
                select(RadarCase)
                .where(RadarCase.candidate_id == candidate_id)
                .order_by(RadarCase.id.desc())
                .limit(1)
            )
        ).scalars().first()
        claims = []
        if case is not None:
            claims = list((await session.execute(
                select(RadarClaim).where(RadarClaim.case_id == case.id)
            )).scalars().all())
    if candidate is None:
        return {'status': 'NOT_FOUND', 'candidate_id': candidate_id}

    claim_states = {str(c.claim_code): str(c.state or "UNKNOWN") for c in claims}
    solo_assessment = assess_solo_transition(
        candidate or {"title": ""},
        claim_states=claim_states,
        company_reality={},
        commercial_reality={},
        attention={},
    ) if case is not None else {}

    try:
        from processors.founder_thesis_research_control_u14 import Store
    except Exception as exc:
        return {
            'status': 'SHADOW_RESEARCH_UNAVAILABLE',
            'candidate_id': candidate_id,
            'reason': f'U14 unavailable: {type(exc).__name__}: {exc}',
            'published_truth_changed': False,
        }

    store = Store()
    card_id = _research_card_id(candidate_id)
    if card_id not in store.card_map:
        best_next = _initial_best_next_research(claim_states, solo_assessment)
        return {
            'status': 'NOT_REGISTERED',
            'candidate_id': candidate_id,
            'card_id': card_id,
            'claim_states': claim_states,
            'solo_assessment': solo_assessment,
            'best_next_research': best_next,
            'gap_progress': [
                {
                    'claim_code': row.get('claim_code'),
                    'state': row.get('state'),
                    'action': row.get('action'),
                }
                for row in best_next.get('priority', [])
                if row.get('claim_code')
            ],
            'recent_requests': [],
            'published_truth_changed': False,
            'truth_boundary': 'SHADOW_RESEARCH_DOES_NOT_CHANGE_PUBLISHED_CLAIMS',
        }

    payload = _serialize_research_progress(store, card_id)
    payload.update({
        'candidate_id': candidate_id,
        'card_id': card_id,
        'claim_states': claim_states,
        'solo_assessment': solo_assessment,
        'recent_requests': _u15_recent_requests(card_id),
        'published_truth_changed': False,
        'truth_boundary': 'SHADOW_RESEARCH_DOES_NOT_CHANGE_PUBLISHED_CLAIMS',
    })
    return payload


@router.post('/opportunity/{candidate_id}/research-more')
async def opportunity_research_more(candidate_id: int):
    """Run one bounded U15 request for the highest-marginal-value open gap.

    Results remain SHADOW. They are visible to the Founder but do not update RadarClaim
    state, Opportunity verdict, WTP, or build recommendation. Published truth changes
    only through the normal SignalForge adjudication/publish pipeline.
    """
    async with async_session() as session:
        candidate = (
            await session.execute(
                select(ProblemCandidate).where(ProblemCandidate.id == candidate_id).limit(1)
            )
        ).scalars().first()
    if candidate is None:
        return {'status': 'NOT_FOUND', 'candidate_id': candidate_id}

    try:
        from processors.founder_thesis_research_control_u14 import Store, GapType
        from processors.founder_directed_research_u15 import FounderDirectedExecutor
    except Exception as exc:
        return {
            'status': 'SHADOW_RESEARCH_UNAVAILABLE',
            'candidate_id': candidate_id,
            'reason': f'U14/U15 unavailable: {type(exc).__name__}: {exc}',
            'published_truth_changed': False,
        }

    async with _research_more_lock:
        store = Store()
        card_id = _research_card_id(candidate_id)
        thesis = store.register_card({'id': card_id, 'type': 'FOUNDER_OPPORTUNITY'})
        base_query = _research_base_query(candidate)
        thesis.title = str(candidate.title or candidate.problem_statement or card_id)[:600]
        thesis.aliases = [x for x in [str(candidate.canonical_key or ''), str(candidate.title or ''), str(candidate.problem_statement or '')] if x][:8]
        for gap_type in GapType:
            gap = store.gap(thesis.thesis_id, gap_type.value)
            if not gap.last_query:
                gap.last_query = base_query
        store._persist()

        executor = FounderDirectedExecutor()
        result = await asyncio.to_thread(executor.execute, store, founder_requests=1)
        progress = _serialize_research_progress(store, card_id)
    return {
        'status': result.get('status', 'UNKNOWN'),
        'candidate_id': candidate_id,
        'card_id': card_id,
        'request_result': result,
        'best_next_research': progress.get('best_next_research'),
        'gap_progress': progress.get('gap_progress') or [],
        'recent_requests': _u15_recent_requests(card_id),
        'published_truth_changed': False,
        'truth_boundary': 'SHADOW_RESEARCH_DOES_NOT_CHANGE_PUBLISHED_CLAIMS',
    }


@router.get('/opportunity/{candidate_id}/candidate')
async def opportunity_candidate_compact(candidate_id: int):
    """Compact Candidate read path for Founder Detail. No crawler/LLM; bounded evidence."""
    async with async_session() as session:
        candidate = (
            await session.execute(
                select(ProblemCandidate).where(ProblemCandidate.id == candidate_id).limit(1)
            )
        ).scalars().first()
        if candidate is None:
            return {"status": "NOT_FOUND", "id": candidate_id, "evidence": []}
        evidence = list((
            await session.execute(
                select(CandidateEvidence)
                .where(CandidateEvidence.candidate_id == candidate_id)
                .order_by(CandidateEvidence.verified.desc(), CandidateEvidence.verification_confidence.desc(), CandidateEvidence.id.desc())
                .limit(24)
            )
        ).scalars().all())
        return {**_candidate_core(candidate), "evidence": [_compact_candidate_evidence(row) for row in evidence]}


@router.get('/opportunity/{candidate_id}')
async def opportunity_detail(candidate_id: int):
    """Read-only Founder detail from the Evidence Ledger. No crawler or LLM."""
    async with async_session() as session:
        case = (
            await session.execute(
                select(RadarCase)
                .where(RadarCase.candidate_id == candidate_id)
                .order_by(RadarCase.id.desc())
                .limit(1)
            )
        ).scalars().first()
        if case is None:
            return {
                "status": "NO_RADAR_CASE",
                "candidate_id": candidate_id,
                "case_id": None,
                "claim_states": {},
                "current_solutions": [],
                "competitive_context": [],
                "solution_evidence": [],
                "gap_evidence": [],
                "failure_reasons": [],
            }

        candidate = (
            await session.execute(
                select(ProblemCandidate).where(ProblemCandidate.id == case.candidate_id).limit(1)
            )
        ).scalars().first()
        claims = list((await session.execute(
            select(RadarClaim).where(RadarClaim.case_id == case.id)
        )).scalars().all())
        claim_states = {str(c.claim_code): str(c.state or "UNKNOWN") for c in claims}
        all_by_id = {int(c.id): c for c in claims}
        target_claims = [c for c in claims if str(c.claim_code) in {"C06", "C07"}]
        by_id = {int(c.id): c for c in target_claims}
        rows: list[dict] = []
        published_evidence: list[dict] = []

        # Targeted C06/C07 rows may include unvalidated candidates so the UI can
        # explicitly say evidence is still pending. They must never be promoted
        # into Founder handoff / published-evidence surfaces without validation.
        if by_id:
            joined = list((await session.execute(
                select(RadarClaimEvidence, RadarEvidence)
                .join(RadarEvidence, RadarEvidence.id == RadarClaimEvidence.evidence_id)
                .where(RadarClaimEvidence.claim_id.in_(list(by_id)))
                .order_by(RadarClaimEvidence.id.desc())
                .limit(48)
            )).all())
            for link, ev in joined:
                claim = by_id.get(int(link.claim_id))
                if claim is not None:
                    rows.append(_evidence_payload(claim, link, ev))

        # Founder handoff gets only validated ledger evidence from the current
        # RadarCase. Retrieved/unvalidated CandidateEvidence remains context, not
        # published truth. This preserves retrieved candidate != confirmed evidence.
        if all_by_id:
            joined_all = list((await session.execute(
                select(RadarClaimEvidence, RadarEvidence)
                .join(RadarEvidence, RadarEvidence.id == RadarClaimEvidence.evidence_id)
                .where(RadarClaimEvidence.claim_id.in_(list(all_by_id)))
                .order_by(RadarClaimEvidence.id.desc())
                .limit(96)
            )).all())
            for link, ev in joined_all:
                if not bool(link.validated):
                    continue
                claim = all_by_id.get(int(link.claim_id))
                if claim is None:
                    continue
                published_evidence.append(_evidence_payload(claim, link, ev))
                if len(published_evidence) >= 24:
                    break

    solution_rows = [row for row in rows if row["claim_code"] == "C06"]
    gap_rows = [row for row in rows if row["claim_code"] == "C07"]
    solo_assessment = assess_solo_transition(
        candidate or {"title": ""},
        claim_states=claim_states,
        company_reality={},
        commercial_reality={},
        attention={},
    )
    return {
        "status": "OK",
        "candidate_id": candidate_id,
        "case_id": int(case.id),
        "claim_states": claim_states,
        "solo_assessment": solo_assessment,
        "current_solutions": _solution_names(solution_rows),
        "competitive_context": _competitive_names(rows),
        "solution_evidence": solution_rows[:12],
        "gap_evidence": gap_rows[:12],
        "published_evidence": published_evidence,
        "failure_reasons": _failure_reasons(gap_rows),
        "truth_boundary": "FOUNDER_HANDOFF_USES_VALIDATED_LEDGER_EVIDENCE_ONLY",
    }

# -------------------------------------------------------------------------------------------------
# R5 Founder operating loop: thesis-level work routing and pre-registered market actions.
# These endpoints never write RadarClaim truth directly.
# -------------------------------------------------------------------------------------------------

@router.get('/operating-queue')
async def operating_queue_r5():
    from processors.signalforge_market_action_registry import (
        build_market_action_queue,
        market_action_registry_report,
    )
    snapshot = _load_published_daily()
    return {
        'engine_version': 'signalforge-founder-operating-loop-r5',
        'published_founder_generated_at': snapshot.get('generated_at'),
        'founder_strategy': snapshot.get('founder_strategy') or {},
        'execution_governor': snapshot.get('execution_governor') or {},
        'strategic_routing_coherence': snapshot.get('strategic_routing_coherence') or {},
        'operating_queue': snapshot.get('operating_queue') or {},
        'market_action_queue': build_market_action_queue(limit=100),
        'market_action_registry': market_action_registry_report(),
        'truth_boundary': 'OPERATING_QUEUE_AND_ACTION_REGISTRY_HAVE_ZERO_DIRECT_C01_C14_WRITE_AUTHORITY',
    }


@router.get('/money-trails')
async def money_trails_founder_product(limit: int = 20):
    """Founder-facing money trail + revenue wedge projection.

    Derived from existing published/validated evidence only. This route never
    writes Radar claims, market truth, or calibration.
    """
    from processors.signalforge_money_trail import build_money_trail_portfolio
    return await build_money_trail_portfolio(limit=max(1, min(int(limit or 20), 50)))


@router.get('/money-trails/{thesis_id}')
async def money_trail_founder_product(thesis_id: str):
    from processors.signalforge_brain_v2_engine import get_brain_v2_portfolio
    from processors.signalforge_money_trail import build_money_trail_for_thesis

    portfolio = dict(get_brain_v2_portfolio())
    thesis = next((x for x in (portfolio.get('portfolio') or []) if str(x.get('thesis_id') or '') == str(thesis_id)), None)
    if thesis is None:
        raise HTTPException(status_code=404, detail=f'thesis {thesis_id!r} not found')
    return await build_money_trail_for_thesis(thesis)


@router.post('/money-trails/probe')
async def money_trail_direction_probe(payload: dict):
    """Read-only Founder probe over the current published SignalForge corpus."""
    from processors.signalforge_money_trail import probe_money_trail_direction

    title = str(payload.get('title') or '').strip()
    description = str(payload.get('description') or '').strip()
    if len(title) < 2:
        raise HTTPException(status_code=422, detail='title must contain at least 2 characters')
    return await probe_money_trail_direction(title=title, description=description)


@router.post('/founder-idea/probe')
async def founder_idea_loop_probe(payload: dict):
    """Part 1 Founder Idea Loop: fresh 0-AI fast probe + Published Money Trail + one Decision Frontier.

    Fresh public-search results are read-only UNVALIDATED_SEARCH_TRACE records.
    They have zero authority to mutate C01-C14, Radar claims, Published evidence,
    market calibration, or any other Market Truth surface.
    """
    from processors.signalforge_founder_idea_loop import probe_founder_idea

    title = str(payload.get('title') or '').strip()
    description = str(payload.get('description') or '').strip()
    if len(title) < 2:
        raise HTTPException(status_code=422, detail='title must contain at least 2 characters')
    return await probe_founder_idea(title=title, description=description)



# -------------------------------------------------------------------------------------------------
# Part 4 Opportunity Decision System: compare / portfolio / trigger watch / Founder resource allocation.
# Read-only projection over Published Brain + Money Trail + Founder addressability + Part 3 disposition.
# -------------------------------------------------------------------------------------------------

@router.get('/decision/portfolio')
async def signalforge_decision_portfolio_part4(
    limit: int = 30,
    weekly_hours: float = 10.0,
    cash_need: str = 'HIGH',
    long_term: str = 'HIGH',
):
    from processors.signalforge_opportunity_decision_closure import build_opportunity_decision_portfolio_closure
    return await build_opportunity_decision_portfolio_closure(
        limit=max(1, min(int(limit or 30), 100)),
        weekly_hours=max(1.0, min(float(weekly_hours or 10.0), 80.0)),
        cash_need=cash_need,
        long_term=long_term,
    )


@router.post('/decision/compare')
async def signalforge_decision_compare_part4(payload: dict):
    from processors.signalforge_opportunity_decision_closure import compare_theses_closure
    thesis_ids = payload.get('thesis_ids') if isinstance(payload.get('thesis_ids'), list) else []
    if not thesis_ids:
        raise HTTPException(status_code=422, detail='thesis_ids must contain at least one thesis')
    return await compare_theses_closure(
        [str(x) for x in thesis_ids],
        weekly_hours=float(payload.get('weekly_hours') or 10.0),
        cash_need=str(payload.get('cash_need') or 'HIGH'),
        long_term=str(payload.get('long_term') or 'HIGH'),
    )


@router.post('/decision/ask')
async def signalforge_decision_ask_part4(payload: dict):
    from processors.signalforge_opportunity_decision_closure import ask_current_signalforge_closure
    q = str(payload.get('q') or '').strip()
    if len(q) < 2:
        raise HTTPException(status_code=422, detail='q must contain at least 2 characters')
    return await ask_current_signalforge_closure(
        q,
        weekly_hours=float(payload.get('weekly_hours') or 10.0),
        cash_need=str(payload.get('cash_need') or 'HIGH'),
        long_term=str(payload.get('long_term') or 'HIGH'),
    )


@router.get('/decision/watch')
async def signalforge_decision_watch_part4(limit: int = 50):
    from processors.signalforge_opportunity_decision_closure import build_opportunity_decision_portfolio_closure
    result = await build_opportunity_decision_portfolio_closure(limit=max(1, min(int(limit or 50), 100)))
    return {
        'engine_version': result.get('engine_version'),
        'status': result.get('status'),
        'count': len(result.get('items') or []),
        'items': [
            {
                'thesis_id': row.get('thesis_id'),
                'title': row.get('title'),
                'current_track': row.get('current_track'),
                'promotion_demotion_watch': row.get('promotion_demotion_watch'),
            }
            for row in (result.get('items') or [])
        ],
        'market_truth_writes': 0,
        'truth_boundary': 'TRIGGER_WATCH_IS_A_READ_ONLY_REVIEW_CONDITION_PROJECTION_NOT_AUTOMATIC_MONITORING_OR_TRUTH_MUTATION',
    }


@router.post('/decision/benchmark-batch')
async def signalforge_decision_benchmark_batch_closure(payload: dict):
    from processors.signalforge_opportunity_decision_closure import benchmark_batch_ingest
    hypotheses = payload.get('hypotheses') if isinstance(payload.get('hypotheses'), list) else []
    if not hypotheses:
        raise HTTPException(status_code=422, detail='hypotheses must contain at least one raw hypothesis')
    if len(hypotheses) > 60:
        raise HTTPException(status_code=422, detail='benchmark batch is bounded to 60 hypotheses')
    return await benchmark_batch_ingest(hypotheses, run_probe=bool(payload.get('run_probe', True)))


# -------------------------------------------------------------------------------------------------
# Part 3 Trust / Falsification: counterevidence search + Published evidence replay + disposition.
# Fresh counterevidence candidates are read-only and never mutate Published Market Truth.
# -------------------------------------------------------------------------------------------------

@router.post('/trust/falsify')
async def signalforge_falsify_part3(payload: dict):
    from processors.signalforge_trust_falsification import falsify_direction

    title = str(payload.get('title') or '').strip()
    description = str(payload.get('description') or '').strip()
    thesis_id = str(payload.get('thesis_id') or '').strip() or None
    if len(title) < 2:
        raise HTTPException(status_code=422, detail='title must contain at least 2 characters')
    return await falsify_direction(title=title, description=description, thesis_id=thesis_id)


@router.get('/trust/evidence-replay/{thesis_id}')
async def signalforge_evidence_replay_part3(thesis_id: str):
    from processors.signalforge_trust_falsification import evidence_replay

    result = await evidence_replay(thesis_id)
    if result.get('status') == 'THESIS_NOT_FOUND':
        raise HTTPException(status_code=404, detail=f'thesis {thesis_id!r} not found')
    return result


# -------------------------------------------------------------------------------------------------
# Part 2 Founder Memory: append-only Founder reasoning, Discussion Brief and Discussion Delta.
# Founder Memory is a separate authority domain and can never write C01-C14 / Published Market Truth.
# -------------------------------------------------------------------------------------------------

@router.get('/founder-memory/status')
async def founder_memory_status_part2():
    from processors.signalforge_founder_memory import founder_memory_status
    return founder_memory_status()


@router.get('/founder-memory/subjects')
async def founder_memory_subjects_part2():
    from processors.signalforge_founder_memory import list_founder_memory_subjects
    return list_founder_memory_subjects()


@router.get('/founder-memory')
async def founder_memory_ledger_part2(subject_key: str | None = None, thesis_id: str | None = None, limit: int = 200):
    from processors.signalforge_founder_memory import list_founder_reasoning
    try:
        return list_founder_reasoning(subject_key=subject_key, thesis_id=thesis_id, limit=max(1, min(int(limit or 200), 1000)))
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post('/founder-memory/entries')
async def founder_memory_record_part2(payload: dict):
    from processors.signalforge_founder_memory import record_founder_reasoning
    tags = payload.get('tags') if isinstance(payload.get('tags'), list) else []
    try:
        return record_founder_reasoning(
            subject_key=str(payload.get('subject_key') or payload.get('subject_label') or payload.get('thesis_id') or ''),
            subject_label=payload.get('subject_label'),
            thesis_id=payload.get('thesis_id'),
            entry_type=str(payload.get('entry_type') or ''),
            statement=str(payload.get('statement') or ''),
            reason=payload.get('reason'),
            source_ref=payload.get('source_ref'),
            tags=[str(x) for x in tags],
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get('/founder-memory/brief')
async def founder_memory_brief_part2(subject_key: str, thesis_id: str | None = None):
    from processors.signalforge_founder_memory import build_discussion_brief
    try:
        return build_discussion_brief(subject_key=subject_key, thesis_id=thesis_id)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get('/founder-memory/delta')
async def founder_memory_delta_part2(subject_key: str, thesis_id: str | None = None):
    from processors.signalforge_founder_memory import build_discussion_delta
    try:
        return build_discussion_delta(subject_key=subject_key, thesis_id=thesis_id)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post('/founder-memory/checkpoints')
async def founder_memory_checkpoint_part2(payload: dict):
    from processors.signalforge_founder_memory import create_discussion_checkpoint
    try:
        return create_discussion_checkpoint(
            subject_key=str(payload.get('subject_key') or payload.get('subject_label') or payload.get('thesis_id') or ''),
            thesis_id=payload.get('thesis_id'),
            note=payload.get('note'),
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get('/market-actions')
async def market_actions_r5():
    from processors.signalforge_market_action_registry import (
        build_market_action_queue,
        market_action_registry_report,
    )
    return {
        'suggested': build_market_action_queue(limit=100),
        'registry': market_action_registry_report(),
    }


@router.post('/market-actions/register')
async def register_market_action_r5(payload: dict):
    from processors.signalforge_market_action_registry import register_market_action
    try:
        return register_market_action(
            thesis_id=str(payload.get('thesis_id') or ''),
            action_type=payload.get('action_type'),
            sample_target=payload.get('sample_target'),
            success_criteria=payload.get('success_criteria'),
            failure_criteria=payload.get('failure_criteria'),
            note=payload.get('note'),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post('/market-actions/{action_id}/complete')
async def complete_market_action_r5(action_id: str, payload: dict):
    from processors.signalforge_market_action_registry import complete_market_action
    try:
        return complete_market_action(
            action_id=action_id,
            result=str(payload.get('result') or ''),
            observations=payload.get('observations') if isinstance(payload.get('observations'), dict) else {},
            note=payload.get('note'),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


# Claim-specific real-market validation. Unlike thesis-level market actions,
# these endpoints use the existing validation_registry + market_ground_truth
# path and therefore may update C10/C11/C14 only after preregistration and the
# established human-market quality checks.
@router.get('/validation-experiments')
async def validation_experiments_r5():
    from processors.signalforge_validation_workflow import claim_validation_report
    return claim_validation_report()


@router.post('/validation-experiments/register')
async def register_validation_experiment_r5(payload: dict):
    from processors.signalforge_validation_workflow import register_claim_validation
    try:
        return await register_claim_validation(
            case_id=int(payload.get('case_id') or 0),
            claim_code=str(payload.get('claim_code') or ''),
            note=payload.get('note'),
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post('/validation-experiments/{experiment_id}/record-result')
async def record_validation_experiment_result_r5(experiment_id: str, payload: dict):
    from processors.signalforge_validation_workflow import record_claim_validation_outcome
    try:
        amount = payload.get('amount')
        return await record_claim_validation_outcome(
            experiment_id=experiment_id,
            result=str(payload.get('result') or ''),
            note=str(payload.get('note') or ''),
            event=payload.get('event'),
            actor_label=payload.get('actor_label'),
            amount=(float(amount) if amount not in (None, '') else None),
            currency=payload.get('currency'),
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

# -------------------------------------------------------------------------------------------------
# Part 6 Market Execution & Learning.
# Test design / preregistration / outcome capture are Founder execution records.  Atomic C10/C11/C14
# writes remain exclusively behind the existing claim-validation + market_ground_truth authority.
# -------------------------------------------------------------------------------------------------

@router.get('/market-execution')
async def signalforge_market_execution_part6(limit: int = 30):
    from processors.signalforge_market_execution_learning import market_execution_dashboard
    return await market_execution_dashboard(limit=limit)


@router.post('/market-execution/design')
async def signalforge_design_market_test_part6(payload: dict):
    from processors.signalforge_market_execution_learning import design_market_test
    try:
        cost = payload.get('max_cost')
        return await design_market_test(
            thesis_id=str(payload.get('thesis_id') or ''),
            max_sample=(int(payload.get('max_sample')) if payload.get('max_sample') not in (None, '') else None),
            max_cost=(float(cost) if cost not in (None, '') else None),
            cost_currency=payload.get('cost_currency'),
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post('/market-execution/preregister')
async def signalforge_preregister_market_test_part6(payload: dict):
    from processors.signalforge_market_execution_learning import preregister_market_test
    try:
        cost = payload.get('max_cost')
        return await preregister_market_test(
            thesis_id=str(payload.get('thesis_id') or ''),
            max_sample=(int(payload.get('max_sample')) if payload.get('max_sample') not in (None, '') else None),
            max_cost=(float(cost) if cost not in (None, '') else None),
            cost_currency=payload.get('cost_currency'),
            decision_rule_override=(payload.get('decision_rule') if isinstance(payload.get('decision_rule'), dict) else None),
            note=payload.get('note'),
        )
    except (TypeError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get('/market-execution/actions/{action_id}/claim-preregistration-options')
async def signalforge_claim_prereg_options_part6(action_id: str):
    from processors.signalforge_market_execution_learning import claim_preregistration_options
    try:
        return await claim_preregistration_options(action_id)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post('/market-execution/actions/{action_id}/claim-preregister')
async def signalforge_claim_preregister_part6(action_id: str, payload: dict):
    from processors.signalforge_market_execution_learning import preregister_claim_for_action
    try:
        return await preregister_claim_for_action(
            action_id=action_id,
            case_id=int(payload.get('case_id') or 0),
            claim_code=str(payload.get('claim_code') or ''),
            note=payload.get('note'),
        )
    except (TypeError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post('/market-execution/actions/{action_id}/capture')
async def signalforge_capture_market_outcome_part6(action_id: str, payload: dict):
    from processors.signalforge_market_execution_learning import capture_market_outcome
    try:
        amount = payload.get('amount')
        return capture_market_outcome(
            action_id=action_id,
            outcome_counts=(payload.get('outcome_counts') if isinstance(payload.get('outcome_counts'), dict) else {}),
            actor_labels=(payload.get('actor_labels') if isinstance(payload.get('actor_labels'), list) else []),
            evidence_refs=(payload.get('evidence_refs') if isinstance(payload.get('evidence_refs'), list) else []),
            observation_records=(payload.get('observation_records') if isinstance(payload.get('observation_records'), list) else []),
            observed_behavior=payload.get('observed_behavior'),
            decision_relevant_findings=payload.get('decision_relevant_findings'),
            reason_counts=(payload.get('reason_counts') if isinstance(payload.get('reason_counts'), dict) else {}),
            amount=(float(amount) if amount not in (None, '') else None),
            currency=payload.get('currency'),
            actual_cost=(float(payload.get('actual_cost')) if payload.get('actual_cost') not in (None, '') else None),
            actual_cost_currency=payload.get('actual_cost_currency'),
            note=payload.get('note'),
        )
    except (TypeError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get('/market-execution/actions/{action_id}/promotion-options')
async def signalforge_promotion_options_part6(action_id: str):
    from processors.signalforge_market_execution_learning import promotion_options
    try:
        return promotion_options(action_id)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post('/market-execution/actions/{action_id}/promote')
async def signalforge_promote_market_outcome_part6(action_id: str, payload: dict):
    from processors.signalforge_market_execution_learning import promote_market_outcome
    try:
        return await promote_market_outcome(
            action_id=action_id,
            experiment_id=str(payload.get('experiment_id') or ''),
            note=payload.get('note'),
        )
    except (TypeError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get('/market-execution/calibration')
async def signalforge_market_learning_calibration_part6():
    from processors.signalforge_market_learning_calibration import market_learning_calibration_report
    from processors.signalforge_calibration_domains import calibration_domains_report
    return {
        'part6_signal_calibration': market_learning_calibration_report(),
        'existing_domain_calibration': calibration_domains_report(),
        'general_predictive_accuracy': 'UNVALIDATED',
        'truth_boundary': 'REAL_OUTCOME_CALIBRATION_ONLY;_ENGINEERING_PASS_NEVER_BECOMES_MARKET_ACCURACY',
    }


# -------------------------------------------------------------------------------------------------
# Part 5 ChatGPT Integration: read/search/probe/falsify/compare + pending Decision Artifact workflow.
# ChatGPT can prepare artifacts, but only explicit Founder confirmation in SignalForge may append to
# Founder Memory. This surface has zero Market Truth write authority.
# -------------------------------------------------------------------------------------------------

@router.get('/chatgpt/status')
async def signalforge_chatgpt_status_part5():
    from processors.signalforge_chatgpt_integration import integration_status
    return integration_status()


@router.get('/chatgpt/discussion-packet/{thesis_id}')
async def signalforge_chatgpt_discussion_packet_part5(thesis_id: str):
    from processors.signalforge_chatgpt_integration import build_discussion_packet
    result = await build_discussion_packet(thesis_id)
    if result.get('status') == 'THESIS_NOT_FOUND':
        raise HTTPException(status_code=404, detail=f'thesis {thesis_id!r} not found')
    return result


@router.post('/chatgpt/decision-artifacts')
async def signalforge_chatgpt_prepare_artifact_part5(payload: dict):
    from processors.signalforge_chatgpt_integration import prepare_decision_artifact
    entries = payload.get('entries') if isinstance(payload.get('entries'), list) else []
    try:
        return prepare_decision_artifact(
            subject_key=str(payload.get('subject_key') or payload.get('subject_label') or payload.get('thesis_id') or ''),
            subject_label=payload.get('subject_label'),
            thesis_id=payload.get('thesis_id'),
            discussion_summary=payload.get('discussion_summary'),
            entries=entries,
            source=str(payload.get('source') or 'SIGNALFORGE_UI'),
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get('/chatgpt/decision-artifacts')
async def signalforge_chatgpt_list_artifacts_part5(status: str | None = None, limit: int = 100):
    from processors.signalforge_chatgpt_integration import list_decision_artifacts
    try:
        return list_decision_artifacts(status=status, limit=max(1, min(int(limit or 100), 500)))
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post('/chatgpt/decision-artifacts/{artifact_id}/confirm')
async def signalforge_chatgpt_confirm_artifact_part5(artifact_id: str, payload: dict):
    from processors.signalforge_chatgpt_integration import confirm_decision_artifact
    if payload.get('founder_confirmed') is not True:
        raise HTTPException(status_code=422, detail='founder_confirmed=true is required')
    try:
        return confirm_decision_artifact(artifact_id=artifact_id, founder_confirmed=True)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post('/chatgpt/decision-artifacts/{artifact_id}/reject')
async def signalforge_chatgpt_reject_artifact_part5(artifact_id: str, payload: dict):
    from processors.signalforge_chatgpt_integration import reject_decision_artifact
    try:
        return reject_decision_artifact(artifact_id=artifact_id, reason=payload.get('reason'))
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


# -------------------------------------------------------------------------------------------------
# Founder UX Architecture v1 — Phase 1 canonical Founder View Models.
# Backend-only product projection. React must render these semantics, not reconstruct them.
# -------------------------------------------------------------------------------------------------

@router.get('/founder-ux/status')
async def signalforge_founder_ux_phase1_status():
    from processors.signalforge_founder_view_models import architecture_status
    return architecture_status()


@router.get('/founder-ux/today')
async def signalforge_founder_ux_today_phase1(limit: int = 50):
    from processors.signalforge_founder_view_models import current_today_view
    return await current_today_view(limit=max(1, min(int(limit or 50), 100)))


@router.get('/founder-ux/opportunities')
async def signalforge_founder_ux_opportunities_phase1(limit: int = 50):
    from processors.signalforge_founder_view_models import current_opportunity_list_view
    return await current_opportunity_list_view(limit=max(1, min(int(limit or 50), 100)))


@router.get('/founder-ux/opportunities/{opportunity_id}')
async def signalforge_founder_ux_opportunity_phase1(opportunity_id: str):
    from processors.signalforge_founder_view_models import current_opportunity_view
    result = await current_opportunity_view(opportunity_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f'opportunity {opportunity_id!r} not found')
    return result

# ---------------------------------------------------------------------------
# Source Expansion Wave 1 — registry / bounded observation probes
# ---------------------------------------------------------------------------

@router.get('/sources/registry')
async def signalforge_source_registry_wave1():
    from processors.signalforge_source_registry import registry_snapshot
    return registry_snapshot()


@router.post('/sources/probe')
async def signalforge_source_expansion_probe_wave1(
    payload: dict,
    x_signalforge_source_token: str | None = Header(default=None, alias='X-SignalForge-Source-Token'),
):
    # This diagnostic endpoint can spend paid API quota. Keep it fail-closed unless an
    # explicit server-side token is configured; never expose the upstream API keys.
    expected_token = str(os.getenv('SIGNALFORGE_SOURCE_PROBE_TOKEN') or '')
    if not expected_token:
        raise HTTPException(status_code=503, detail='Source probe API is disabled until SIGNALFORGE_SOURCE_PROBE_TOKEN is configured')
    if not x_signalforge_source_token or not secrets.compare_digest(x_signalforge_source_token, expected_token):
        raise HTTPException(status_code=401, detail='Invalid source probe token')
    from processors.signalforge_source_expansion import run_source_expansion
    title = str(payload.get('title') or '').strip()
    description = str(payload.get('description') or '').strip()
    if len(title) < 2:
        raise HTTPException(status_code=422, detail='title must contain at least 2 characters')
    hypothesis = f"{title} {description}".strip()
    query = str(payload.get('query') or hypothesis).strip()
    source_ids = payload.get('source_ids')
    if source_ids is not None and not isinstance(source_ids, list):
        raise HTTPException(status_code=422, detail='source_ids must be a list when provided')
    return await asyncio.to_thread(
        run_source_expansion,
        hypothesis,
        query,
        explicit_source_ids=[str(x) for x in source_ids] if isinstance(source_ids, list) else None,
    )

# R8_RESEARCH_BACKLOG_V1_HOTFIX3_ROUTER_INCLUDE
from api.routes.signalforge_research_backlog import router as _r8_research_backlog_router
router.include_router(_r8_research_backlog_router)
# /R8_RESEARCH_BACKLOG_V1_HOTFIX3_ROUTER_INCLUDE
