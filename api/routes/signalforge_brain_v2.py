from __future__ import annotations

from pathlib import Path
from fastapi import APIRouter, Query

router = APIRouter()


def _unavailable(exc: BaseException) -> dict:
    return {
        "status": "BRAIN_V2_UNAVAILABLE_NON_BLOCKING",
        "error": f"{type(exc).__name__}: {exc}",
        "read_only": True,
        "production_impact": "NONE",
    }


@router.get("/status")
async def status():
    try:
        from processors.signalforge_brain_v2_engine import get_brain_v2_status
        from processors.signalforge_brain_v2_runtime import get_brain_v2_runtime_status
        return {"brain": get_brain_v2_status(), "runtime": get_brain_v2_runtime_status(), "read_only": True}
    except Exception as exc:
        return _unavailable(exc)


@router.get("/portfolio")
async def portfolio(limit: int = Query(default=50, ge=1, le=200)):
    try:
        from processors.signalforge_brain_v2_engine import get_brain_v2_portfolio
        p = dict(get_brain_v2_portfolio())
        p["portfolio"] = list(p.get("portfolio", []) or [])[:limit]
        p["read_only"] = True
        return p
    except Exception as exc:
        return _unavailable(exc)


@router.get("/research-queue")
async def research_queue(limit: int = Query(default=30, ge=1, le=200)):
    try:
        from processors.signalforge_brain_v2_engine import get_brain_v2_research_advisory
        return {**get_brain_v2_research_advisory(limit=limit), "read_only": True}
    except Exception as exc:
        return _unavailable(exc)


@router.get("/changes")
async def changes(limit: int = Query(default=50, ge=1, le=200)):
    try:
        from processors.signalforge_brain_v2_store import meaningful_changes
        items = meaningful_changes(Path.cwd().resolve(), limit=limit)
        return {
            "items": items,
            "count": len(items),
            "read_only": True,
            "truth_boundary": "SEMANTIC_STRUCTURAL_CHANGES_ONLY_NOT_RECENCY_FEED",
        }
    except Exception as exc:
        return _unavailable(exc)


@router.get("/problem-lineage/{lineage_id}")
async def problem_lineage(lineage_id: str):
    try:
        from processors.signalforge_brain_v2_engine import get_problem_lineage
        row = get_problem_lineage(lineage_id)
        return row if row is not None else {"status": "NOT_FOUND", "lineage_id": lineage_id}
    except Exception as exc:
        return _unavailable(exc)


@router.get("/transition-hypothesis/{hypothesis_id}")
async def transition_hypothesis(hypothesis_id: str):
    try:
        from processors.signalforge_brain_v2_engine import get_transition_hypothesis
        row = get_transition_hypothesis(hypothesis_id)
        return row if row is not None else {"status": "NOT_FOUND", "hypothesis_id": hypothesis_id}
    except Exception as exc:
        return _unavailable(exc)


@router.get("/bridge-hypothesis/{hypothesis_id}")
async def bridge_hypothesis(hypothesis_id: str):
    try:
        from processors.signalforge_brain_v2_engine import get_structural_bridge_hypothesis
        row = get_structural_bridge_hypothesis(hypothesis_id)
        return row if row is not None else {"status": "NOT_FOUND", "hypothesis_id": hypothesis_id}
    except Exception as exc:
        return _unavailable(exc)


@router.get("/transition-lineage/{lineage_id}")
async def transition_lineage(lineage_id: str):
    try:
        from processors.signalforge_brain_v2_engine import get_transition_lineage
        row = get_transition_lineage(lineage_id)
        return row if row is not None else {"status": "NOT_FOUND", "lineage_id": lineage_id}
    except Exception as exc:
        return _unavailable(exc)


@router.get("/existing-system/{system_id}")
async def existing_system(system_id: str):
    try:
        from processors.signalforge_brain_v2_engine import get_existing_system
        row = get_existing_system(system_id)
        return row if row is not None else {"status": "NOT_FOUND", "system_id": system_id}
    except Exception as exc:
        return _unavailable(exc)


@router.get("/intersection/{intersection_id}")
async def intersection(intersection_id: str):
    try:
        from processors.signalforge_brain_v2_engine import get_structural_intersection
        row = get_structural_intersection(intersection_id)
        return row if row is not None else {"status": "NOT_FOUND", "intersection_id": intersection_id}
    except Exception as exc:
        return _unavailable(exc)


@router.get("/thesis/{thesis_id}")
async def thesis(thesis_id: str):
    try:
        from processors.signalforge_brain_v2_engine import get_thesis
        row = get_thesis(thesis_id)
        return row if row is not None else {"status": "NOT_FOUND", "thesis_id": thesis_id}
    except Exception as exc:
        return _unavailable(exc)


@router.get("/diagnostics")
async def brain_diagnostics():
    try:
        from processors.signalforge_brain_v2_engine import diagnostics
        return {**diagnostics(), "read_only": True}
    except Exception as exc:
        return _unavailable(exc)
@router.get("/strategic-portfolio")
async def strategic_portfolio(limit: int = Query(default=50, ge=1, le=200)):
    """Founder-facing strategy surface built from Brain thesis objects.

    It intentionally separates objective opportunity truth from first-person Founder
    addressability and exposes BOTH / ZIP2_STRUCTURAL / FAST_VALIDATION / NEITHER.
    """
    try:
        from processors.signalforge_brain_v2_engine import get_brain_v2_portfolio
        p = dict(get_brain_v2_portfolio())
        rows = list(p.get("portfolio", []) or [])
        return {
            "engine_version": p.get("engine_version"),
            "status": p.get("status"),
            "refreshed_at": p.get("refreshed_at"),
            "strategic_summary": p.get("strategic_summary") or {},
            "items": rows[:limit],
            "count": len(rows),
            "market_calibration": p.get("market_calibration") or {},
            "authority": "DERIVED_FOUNDER_STRATEGY_NO_ATOMIC_MARKET_TRUTH_WRITE",
            "read_only": True,
        }
    except Exception as exc:
        return _unavailable(exc)


@router.get("/research-workspace")
async def research_workspace(limit: int = Query(default=100, ge=1, le=300)):
    """Opportunity-bound research workspace.

    Legacy free-form research projects are not the canonical SignalForge research flow.
    Every row here is bound to a Brain thesis/problem lineage and remains planning-only.
    """
    try:
        from processors.signalforge_brain_v2_engine import get_brain_v2_portfolio
        p = dict(get_brain_v2_portfolio())
        thesis_map = {str(x.get("thesis_id")): x for x in (p.get("portfolio") or [])}
        rows = []
        for q in list(p.get("research_queue", []) or [])[:limit]:
            t = thesis_map.get(str(q.get("thesis_id"))) or {}
            rows.append({
                **dict(q),
                "representative_title": t.get("representative_title"),
                "representative_problem": t.get("representative_problem"),
                "strategic_track": t.get("strategic_track"),
                "zip2_readiness": t.get("zip2_readiness"),
                "fast_validation": t.get("fast_validation") or {},
                "founder_addressability": t.get("founder_addressability") or {},
                "best_next_action": t.get("best_next_action") or {},
            })
        return {
            "engine_version": p.get("engine_version"),
            "status": p.get("status"),
            "refreshed_at": p.get("refreshed_at"),
            "count": len(rows),
            "items": rows,
            "truth_boundary": "Opportunity-bound planning only. Research output must return through validated Radar evidence before changing market truth.",
            "read_only": True,
        }
    except Exception as exc:
        return _unavailable(exc)


@router.get("/search")
async def brain_search(q: str = Query(min_length=2, max_length=200), limit: int = Query(default=40, ge=1, le=100)):
    """Search persistent SignalForge intelligence separately from the raw corpus search."""
    try:
        from processors.signalforge_brain_v2_engine import get_brain_v2_portfolio
        p = dict(get_brain_v2_portfolio())
        needle = q.strip().lower()
        results = []
        specs = (
            ("OPPORTUNITY_THESIS", p.get("portfolio") or [], "thesis_id", ("representative_title", "representative_problem", "strategic_track", "classification", "zip2_readiness")),
            ("PROBLEM_LINEAGE", p.get("problem_lineages") or [], "lineage_id", ("representative_title", "representative_problem", "trajectory")),
            ("TRANSITION_LINEAGE", p.get("transition_lineages") or [], "transition_lineage_id", ("representative_text", "driver", "trajectory")),
            ("STRUCTURAL_INTERSECTION", p.get("structural_intersections") or [], "intersection_id", ("state", "eligibility")),
        )
        for typ, rows, id_key, fields in specs:
            for row in rows:
                hay = " ".join(str(row.get(k) or "") for k in fields).lower()
                if needle not in hay:
                    continue
                results.append({
                    "object_type": typ,
                    "object_id": row.get(id_key),
                    "title": row.get("representative_title") or row.get("representative_problem") or row.get("representative_text") or row.get(id_key),
                    "subtitle": row.get("representative_problem") or row.get("driver") or row.get("eligibility"),
                    "strategic_track": row.get("strategic_track"),
                    "zip2_readiness": row.get("zip2_readiness"),
                    "classification": row.get("classification"),
                })
                if len(results) >= limit:
                    break
            if len(results) >= limit:
                break
        return {
            "query": q,
            "count": len(results),
            "items": results,
            "search_scope": "PERSISTENT_SIGNALFORGE_INTELLIGENCE_NOT_RAW_CORPUS",
            "read_only": True,
        }
    except Exception as exc:
        return _unavailable(exc)


@router.get("/founder-profile")
async def founder_profile():
    """Expose non-secret company capability policy used by first-person addressability."""
    try:
        import json
        root = Path.cwd().resolve()
        path = root / "config/company_capability_profile.json"
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        return {
            "profile": data,
            "truth_boundary": "Profile is explicit Company Truth input. It may constrain Founder addressability but never rewrite objective market truth.",
            "read_only": True,
        }
    except Exception as exc:
        return _unavailable(exc)


@router.get("/action-queue")
async def founder_action_queue(limit: int = Query(default=100, ge=1, le=300)):
    """Return Brain-derived Founder actions, including market-action handoff.

    MARKET_ACTION means the next uncertainty is better reduced by observed buyer behavior;
    it never records a successful outcome by itself.
    """
    try:
        from processors.signalforge_brain_v2_engine import get_brain_v2_portfolio
        p = dict(get_brain_v2_portfolio())
        rows = list(p.get("founder_action_queue", []) or [])[:limit]
        return {
            "engine_version": p.get("engine_version"),
            "status": p.get("status"),
            "refreshed_at": p.get("refreshed_at"),
            "count": len(rows),
            "items": rows,
            "truth_boundary": "Action routing only. Market outcomes must be observed and recorded separately before calibration changes.",
            "read_only": True,
        }
    except Exception as exc:
        return _unavailable(exc)
