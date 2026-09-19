"""Bounded, stale-aware ProblemCandidate discovery for SignalForge M14.

Discovery is deliberately separated from the legacy all-processor pipeline.  It
refreshes only when the underlying corpus changed or the discovery snapshot is
old, runs under the caller's explicit LLM-call allowance, and then migrates any
new ProblemCandidate/CandidateEvidence rows into the Radar ledger.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

from database.connection import async_session, Post, ProblemCandidate, RadarCase
from processors.problem_candidate_engine import run_problem_candidates
from processors.radar_ledger import run_radar_ledger
from processors.signalforge_brain_v2_integration import safe_brain_research_advisory
from processors.transition_gap_discovery import run_transition_gap_discovery

ENGINE_VERSION = "problem-discovery-refresh-r5-opportunity-bearing-portfolio"
STATE_PATH = Path(".radar_runtime/problem_discovery.json")
DEFAULT_STALE_HOURS = 24.0
MAX_DISCOVERY_AI_CALLS = 6


def _utcnow() -> datetime:
    return datetime.utcnow()


def _read_state() -> dict[str, Any]:
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_state(data: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    tmp.replace(STATE_PATH)


def _parse_dt(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


async def _corpus_truth() -> dict[str, int]:
    async with async_session() as session:
        post_count = int(
            (await session.execute(select(func.count(Post.id)))).scalar() or 0
        )
        max_post_id = int(
            (await session.execute(select(func.max(Post.id)))).scalar() or 0
        )
        candidate_count = int(
            (await session.execute(select(func.count(ProblemCandidate.id)))).scalar() or 0
        )
        case_count = int(
            (await session.execute(select(func.count(RadarCase.id)))).scalar() or 0
        )
    return {
        "post_count": post_count,
        "max_post_id": max_post_id,
        "candidate_count": candidate_count,
        "case_count": case_count,
    }


def discovery_due(
    state: dict[str, Any],
    truth: dict[str, int],
    *,
    force: bool = False,
    stale_hours: float = DEFAULT_STALE_HOURS,
) -> tuple[bool, str]:
    if force:
        return True, "FORCED"
    if str(state.get("engine_version") or "") != ENGINE_VERSION:
        return True, "ENGINE_UPGRADE"
    if int(state.get("max_post_id", -1) or -1) != int(truth.get("max_post_id", 0) or 0):
        return True, "CORPUS_CHANGED"
    last_success = _parse_dt(state.get("last_success_at"))
    if last_success is None:
        return True, "NEVER_SUCCEEDED"
    if _utcnow() - last_success >= timedelta(hours=max(1.0, float(stale_hours))):
        return True, "STALE"
    return False, "FRESH"


async def run_problem_discovery_refresh(
    *,
    ai_call_allowance: int = MAX_DISCOVERY_AI_CALLS,
    force: bool = False,
    stale_hours: float = DEFAULT_STALE_HOURS,
) -> dict[str, Any]:
    before = await _corpus_truth()
    state = _read_state()
    due, reason = discovery_due(
        state,
        before,
        force=force,
        stale_hours=stale_hours,
    )
    allowance = max(0, min(int(ai_call_allowance), MAX_DISCOVERY_AI_CALLS))

    if not due:
        return {
            "engine_version": ENGINE_VERSION,
            "status": "FRESH_SKIP",
            "reason": reason,
            "before": before,
            "after": before,
            "llm_calls": 0,
            "llm_tokens": 0,
            "llm_cost_twd": 0.0,
        }

    # V5.2 runs change-first discovery before the legacy pain-first path.
    # With the normal allowance=4, two calls are reserved for cross-source
    # transition-gap formation and the remaining two are split between narrow
    # community fingerprinting and evidence verification. No extra calls are
    # invented when the caller supplies a smaller budget.
    transition_calls = min(2, allowance)
    transition = await run_transition_gap_discovery(
        ai_call_allowance=transition_calls,
        max_persist=12,
    )
    remaining = max(0, allowance - int(transition.get("llm_calls", 0) or 0))
    fingerprint_calls = min(1, remaining)
    verify_calls = max(0, remaining - fingerprint_calls)

    result = await run_problem_candidates(
        fingerprint_ai_call_allowance=fingerprint_calls,
        profile_ai_call_allowance=0,
        verify_ai_call_allowance=verify_calls,
        translate=False,
        incremental_only=True,
        max_incremental_candidates=16,
    )
    processed_candidate_ids = sorted({
        int(x)
        for x in (
            list(result.get("processed_candidate_ids") or [])
            + list(transition.get("active_candidate_ids") or [])
            + list(transition.get("candidate_ids") or [])
        )
        if str(x).isdigit() and int(x) > 0
    })
    brain_advisory = safe_brain_research_advisory(limit=24)
    ledger = await run_radar_ledger(
        candidate_ids=processed_candidate_ids,
        admit_new=True,
        brain_candidate_ids=brain_advisory.get("candidate_ids") or [],
    )
    after = await _corpus_truth()

    payload = {
        "engine_version": ENGINE_VERSION,
        "status": "PASS",
        "reason": reason,
        "before": before,
        "after": after,
        "new_candidates": max(0, after["candidate_count"] - before["candidate_count"]),
        "new_cases": max(0, after["case_count"] - before["case_count"]),
        "transition_gap_discovery": transition,
        "candidate_engine": result,
        "ledger": ledger,
        "processed_candidate_ids": processed_candidate_ids,
        "candidates_deferred_before_radar": int(ledger.get("candidates_deferred", 0) or 0),
        "admission_states": ledger.get("admission_states") or {},
        "enrichment_batch": int(result.get("enrichment_batch", 0) or 0),
        "pre_enrichment_deferred": int(result.get("pre_enrichment_deferred", 0) or 0),
        "pre_enrichment_deferred_reasons": result.get("pre_enrichment_deferred_reasons") or {},
        "discovery_portfolio": result.get("discovery_portfolio") or {},
        "llm_calls": int(transition.get("llm_calls", 0) or 0) + int(result.get("llm_calls", 0) or 0),
        "llm_tokens": int(transition.get("llm_tokens", 0) or 0) + int(result.get("llm_tokens", 0) or 0),
        "llm_cost_twd": float(result.get("llm_cost_twd", 0) or 0),
    }
    state.update({
        "engine_version": ENGINE_VERSION,
        "last_success_at": _utcnow().isoformat(timespec="seconds"),
        "last_reason": reason,
        "post_count": after["post_count"],
        "max_post_id": after["max_post_id"],
        "candidate_count": after["candidate_count"],
        "case_count": after["case_count"],
        "last_result": {
            "new_candidates": payload["new_candidates"],
            "new_cases": payload["new_cases"],
            "llm_calls": payload["llm_calls"],
            "pre_enrichment_deferred": payload["pre_enrichment_deferred"],
            "transition_candidates": int(transition.get("inserted", 0) or 0) + int(transition.get("updated", 0) or 0),
            "transition_pair_pool": int(transition.get("pair_pool", 0) or 0),
        },
    })
    _write_state(state)
    return payload


def discovery_status() -> dict[str, Any]:
    state = _read_state()
    return {
        "engine_version": ENGINE_VERSION,
        "state_path": str(STATE_PATH),
        **state,
    }
