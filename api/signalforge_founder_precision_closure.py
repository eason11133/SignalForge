from __future__ import annotations

import json
import math
import re
from collections import Counter
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

_STOP = {
    "the","a","an","and","or","to","of","in","on","for","with","is","are","was","were",
    "this","that","it","its","as","at","by","from","into","using","use","user","specific",
    "problem","issue","fails","failure","running","local","environment","developer"
}

def _tokens(text: str) -> list[str]:
    xs = re.findall(r"[a-z0-9][a-z0-9_+.-]{2,}", (text or "").lower())
    return [x for x in xs if x not in _STOP]

def _meaningful_overlap(anchor: str, evidence: str) -> float:
    a = set(_tokens(anchor))
    e = set(_tokens(evidence))
    if not a or not e:
        return 0.0
    inter = a & e
    # Give extra weight to highly thesis-specific tokens.
    rare = {"assumption","assumptions","reporting","numbers","incorrect","unverified",
            "claude","code","bias","config","architecture","verification","audit"}
    bonus = len(inter & rare) * 0.08
    return min(1.0, len(inter) / max(4.0, math.sqrt(len(a) * len(e))) + bonus)

def _community_precision(candidate: dict[str, Any]) -> dict[str, Any]:
    evidence = list(candidate.get("evidence") or [])
    anchor = " ".join(
        str(candidate.get(k) or "")
        for k in ("problem_statement","failure_mode","task","object","consequence")
    )
    community = [x for x in evidence if x.get("relation") == "community_problem"]
    if not community:
        return candidate

    scored = []
    for ev in community:
        text = " ".join(str(ev.get(k) or "") for k in ("title","excerpt","source_ref"))
        s = _meaningful_overlap(anchor, text)
        scored.append((s, ev))

    keep = [ev for s, ev in scored if s >= 0.34]
    # Zero same-problem evidence is a valid Founder-facing result. A semantically
    # unrelated "strongest" row must never be retained merely to avoid an empty set.

    keep_ids = {x.get("id") for x in keep}
    for ev in evidence:
        if ev.get("relation") == "community_problem":
            ev["founder_same_problem"] = ev.get("id") in keep_ids
            ev["founder_semantic_role"] = (
                "SAME_PROBLEM_SUPPORT" if ev.get("id") in keep_ids else "RELATED_CONTEXT_ONLY"
            )

    candidate["community_evidence_count_raw"] = candidate.get("community_evidence_count")
    candidate["community_user_count_raw"] = candidate.get("community_user_count")
    candidate["community_problem_score_raw"] = candidate.get("community_problem_score")
    candidate["community_evidence_count"] = len(keep)

    families = set()
    for ev in keep:
        ref = str(ev.get("source_ref") or ev.get("url") or ev.get("id"))
        families.add(ref)
    candidate["community_user_count"] = len(families)

    old = float(candidate.get("community_problem_score") or 0.0)
    ratio = len(keep) / max(1, len(community))
    candidate["community_problem_score"] = round(min(old, old * ratio), 1)
    candidate["founder_grouping_precision"] = {
        "status": "PRECISION_FILTERED",
        "same_problem": len(keep),
        "raw_grouped": len(community),
        "rule": "community evidence only counts toward the candidate when it matches the same problem atom; zero is valid",
    }
    return candidate

def _opportunity_precision(payload: dict[str, Any]) -> dict[str, Any]:
    cid = payload.get("candidate_id")
    claim_states = dict(payload.get("claim_states") or {})
    pe = list(payload.get("published_evidence") or [])

    # C05: generic AI hiring / budget context cannot prove thesis-specific buyer existence.
    direct_support = []
    for ev in pe:
        if ev.get("claim_code") != "C05":
            continue
        if ev.get("stance") == "SUPPORT":
            if ev.get("directness") == "DIRECT":
                direct_support.append(ev)
            else:
                ev["stance_raw"] = ev.get("stance")
                ev["stance"] = "INSUFFICIENT"
                ev["founder_precision_reason"] = (
                    "Generic/RELATED buyer budget evidence cannot prove thesis-specific buyer existence."
                )

    if claim_states.get("C05") == "SUPPORTED" and not direct_support:
        claim_states["C05"] = "INSUFFICIENT"
        payload["claim_states"] = claim_states
        payload.setdefault("founder_precision_corrections", []).append({
            "claim_code": "C05",
            "from": "SUPPORTED",
            "to": "INSUFFICIENT",
            "reason": "No DIRECT thesis-specific buyer support remains after precision filtering.",
        })

    # Founder-facing Published evidence hygiene:
    # keep validated ledger evidence, but demote clearly context-only RELATED items out of the primary list.
    primary, context = [], []
    entity_terms = set()
    for s in payload.get("current_solutions") or []:
        entity_terms |= set(_tokens(str(s)))
    for ev in pe:
        ev["validated"] = bool(ev.get("validated"))
        if not ev["validated"]:
            continue
        rel = ev.get("directness")
        stance = ev.get("stance")
        text = " ".join(str(ev.get(k) or "") for k in ("source_title","excerpt"))
        toks = set(_tokens(text))
        has_entity = bool(entity_terms & toks) if entity_terms else True
        context_only = (
            rel == "RELATED"
            and stance in ("INSUFFICIENT","RELATED")
            and not has_entity
        )
        if context_only:
            ev["founder_visibility"] = "CONTEXT_ONLY"
            context.append(ev)
        else:
            ev["founder_visibility"] = "PRIMARY"
            primary.append(ev)

    payload["published_evidence_raw_count"] = len(pe)
    payload["published_evidence"] = primary
    payload["published_context_evidence"] = context
    payload["published_evidence_precision"] = {
        "primary": len(primary),
        "context_only": len(context),
        "rule": "validated context may exist without being shown as primary thesis evidence",
    }

    return payload

def _research_state_precision(payload: dict[str, Any]) -> dict[str, Any]:
    cid = payload.get("candidate_id")
    if payload.get("status") != "NOT_REGISTERED" or payload.get("best_next_research"):
        return payload
    # The route now provides current claim states / solo assessment directly.
    # Do not depend on another concurrent HTTP request having populated process cache.
    claim_states = payload.get("claim_states") or {}
    solo = payload.get("solo_assessment") or {}
    next_gate = solo.get("next_gate")

    priority = []
    if next_gate:
        priority.append({
            "gate": next_gate,
            "why": "Current solo assessment identifies this as the next unresolved opportunity gate."
        })
    for code, label in (
        ("C05","Find DIRECT thesis-specific buyer / budget evidence"),
        ("C07","Find evidence the same gap remains unresolved despite existing solutions"),
        ("C11","Find direct willingness-to-pay / paid substitute evidence"),
    ):
        st = claim_states.get(code)
        if st in ("INSUFFICIENT","UNKNOWN"):
            priority.append({"claim_code": code, "state": st, "action": label})

    if not priority:
        priority.append({
            "action": "Research the highest-risk UNKNOWN/INSUFFICIENT claim before changing Published truth."
        })

    payload["best_next_research"] = {
        "mode": "FOUNDER_FIRST_USE_FALLBACK",
        "priority": priority[:4],
        "truth_boundary": "This is guidance only. It does not promote any Published claim."
    }
    payload["gap_progress"] = [
        {"claim_code": x.get("claim_code"), "state": x.get("state"), "action": x.get("action")}
        for x in priority if x.get("claim_code")
    ]
    return payload

def _status_precision(payload: dict[str, Any]) -> dict[str, Any]:
    payload["founder_runtime_authority"] = {
        "running": bool(payload.get("running")),
        "last_finished_at": payload.get("last_finished_at"),
        "last_error": payload.get("last_error"),
        "rule": "UI must reconcile to /api/signalforge/status.running; websocket state is not authoritative."
    }
    last_cycle = payload.get("last_cycle") or {}
    phase = last_cycle.get("phase_seconds") or {}
    if phase:
        payload["founder_runtime_authority"]["last_phase_seconds"] = phase
    return payload

class SignalForgeFounderPrecisionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        path = request.url.path
        if request.method != "GET" or "signalforge" not in path:
            return response
        ctype = response.headers.get("content-type","")
        if "application/json" not in ctype:
            return response

        body = b""
        async for chunk in response.body_iterator:
            body += chunk
        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception:
            return Response(
                content=body, status_code=response.status_code,
                headers=dict(response.headers), media_type="application/json"
            )
        if not isinstance(payload, dict):
            return Response(
                content=body, status_code=response.status_code,
                headers=dict(response.headers), media_type="application/json"
            )

        if re.search(r"/api/signalforge/opportunity/\d+/candidate$", path):
            payload = _community_precision(payload)
        elif re.search(r"/api/signalforge/opportunity/\d+/research-state$", path):
            payload = _research_state_precision(payload)
        elif re.search(r"/api/signalforge/opportunity/\d+$", path):
            payload = _opportunity_precision(payload)
        elif path.rstrip("/") == "/api/signalforge/status":
            payload = _status_precision(payload)

        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = dict(response.headers)
        headers.pop("content-length", None)
        return Response(
            content=raw, status_code=response.status_code,
            headers=headers, media_type="application/json"
        )

def install_signalforge_founder_precision(app):
    app.add_middleware(SignalForgeFounderPrecisionMiddleware)
    return app
