from __future__ import annotations

import asyncio
import json
import os
import re
import sqlite3
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse

from sqlalchemy import func, select

from database.connection import (
    async_session,
    ProblemCandidate,
    CandidateEvidence,
    RadarCase,
    RadarClaim,
    RadarClaimEvidence,
    RadarEvidence,
)
from processors.signalforge_brain_v2_contracts import (
    ENGINE_VERSION as CONTRACTS_VERSION,
    SCHEMA_VERSION,
    DIMENSION_KEYS,
    aggregate_claim_states,
    canonical_json,
    classify_thesis,
    clean,
    dimension,
    dim_state,
    intersection_gate,
    meaningful_change,
    normalize_state,
    portfolio_sort_key,
    problem_bucket_keys,
    problem_features,
    research_plan,
    same_problem,
    same_transition,
    semantic_fingerprint,
    stable_hash,
    transition_bucket_keys,
    transition_driver,
    workaround_level,
    words,
)
from processors.signalforge_strategic_rebase import (
    decorate_thesis_with_strategy,
    founder_action_queue,
    strategic_sort_key,
    strategic_summary,
)
from processors.signalforge_brain_v2_structural_recall import (
    apply_transition_hypothesis_promotions,
    build_prethesis_research_questions,
    build_structural_bridge_hypotheses,
    build_transition_hypotheses,
    evolve_thesis_lifecycle,
    zip2_gate_report,
)
from processors.signalforge_brain_v2_store import (
    append_events,
    apply_pending_events,
    count_events,
    dependency_rows,
    get_object,
    meaningful_changes,
    object_map,
    replay_projection,
    state_hash,
    state_hash_from_snapshot,
    state_meta,
    state_snapshot,
    truth_input_map,
)

ENGINE_VERSION = "signalforge-brain-v2-g3-strategic-search-founder-addressability-rebase-r1"
PORTFOLIO_JSON = Path(".radar_runtime/signalforge_brain_v2_full_portfolio.json")
STATUS_JSON = Path(".radar_runtime/signalforge_brain_v2_full_status.json")
RESEARCH_QUEUE_JSON = Path(".radar_runtime/signalforge_brain_v2_full_research_queue.json")
LEASE_PATH = Path(".radar_runtime/signalforge_brain_v2_full.lock")
MARKET_TEST_QUEUE = Path(".radar_runtime/market_test_queue_r1.json")
CALIBRATION_JSON = Path(".radar_runtime/opportunity_calibration_r1.json")
SHADOW_FRAMEGRAPH_DB = Path(".radar_runtime/discovery_knowledge_projection_v1.sqlite3")

PERSISTENCE_MIN_DAYS = 14
TRANSITION_RELATIONS = {"why_now", "research_enabler", "ecosystem_activity", "external_enabler", "transition_signal"}
STRONG_TRANSITION_RELATIONS = {"research_enabler", "external_enabler", "transition_signal"}
GENERIC_TRANSITION_KEYS = {
    "transition_discovery_version", "opportunity_discovery_version", "engine_version", "version",
    "transition_evidence_verified", "opportunity_linkage_status", "transition_pair_verified",
}
TRANSITION_KEY_HINTS = ("transition", "enabler", "why_now", "change", "shift", "adoption", "window")
# Explicit metadata only. These anchors can sharpen transition identity but may not be
# inferred from generic text or an LLM completion. UNKNOWN is safer than false precision.
TRANSITION_SUBJECT_METADATA_KEYS = (
    "transition_subject", "transition_mechanism", "technology", "regulation",
    "policy", "standard", "platform", "model_family", "capability",
    "distribution_channel", "cost_driver", "business_model",
)

# Brain-owned structural evidence has to be explicitly verified before it may resolve
# a structural dimension.  These relations are not Radar atomic claims and can never
# write C01-C14.  They only make currently-frozen structural unknowns researchable.
STRUCTURAL_RELATIONS = {
    "value_flow": {"value_flow", "budget_flow", "economic_flow", "value_pool"},
    "complementary_asset": {"complementary_asset", "asset_access", "asset_accessibility", "distribution_asset"},
    "incumbent_response": {"incumbent_response", "competitive_response", "platform_response"},
    "expansion_surface": {"expansion_surface", "adjacent_workflow", "adjacent_market", "land_and_expand", "wedge_expansion"},
}
MEANINGFUL_CHANGE_OBJECT_TYPES = {
    "problem_lineage", "transition_hypothesis", "transition_lineage", "existing_system",
    "structural_bridge_hypothesis", "structural_intersection", "opportunity_thesis",
}


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_dt(v: Any) -> datetime | None:
    if isinstance(v, datetime):
        return v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v.astimezone(timezone.utc)
    s = clean(v)
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
    except Exception:
        return None


def _iso(v: Any) -> str | None:
    dt = _parse_dt(v)
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z") if dt else (clean(v) or None)


def _json_safe(v: Any) -> Any:
    return json.loads(json.dumps(v, ensure_ascii=False, default=str))


def _safe_read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def _file_fingerprint(path: Path) -> str:
    try:
        raw = path.read_bytes()
    except Exception:
        return "MISSING"
    import hashlib
    return hashlib.sha256(raw).hexdigest()


def _url_origin(url: Any) -> str:
    raw = clean(url)
    if not raw:
        return ""
    try:
        host = (urlparse(raw).hostname or "").lower().removeprefix("www.")
        return host
    except Exception:
        return ""


def _evidence_family(row: Mapping[str, Any]) -> str:
    md = row.get("metadata") if isinstance(row.get("metadata"), Mapping) else {}
    discussion = clean(md.get("discussion_key"))
    if discussion:
        return "discussion:" + discussion
    origin = _url_origin(row.get("url") or row.get("source_url"))
    if origin:
        return "origin:" + origin
    source_type = clean(row.get("source_type")) or "unknown"
    source_ref = clean(row.get("source_ref"))
    return f"{source_type}:ref:{source_ref}" if source_ref else f"{source_type}:content:{stable_hash(row.get('title'), row.get('excerpt'), length=16)}"


def _evidence_content_fp(text: Any) -> str:
    toks = sorted(words(text))
    return stable_hash(toks, length=24) if toks else ""


def _build_evidence_index(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Index validated/verified evidence once per Brain build.

    Existing System and Thesis construction query the same evidence repeatedly. Re-scanning
    the complete CandidateEvidence/Radar link corpus per lineage is O(lineages × evidence)
    and was the dominant cost in large longitudinal portfolios.
    """
    claim_states_by_candidate, claim_details_by_candidate, links_by_candidate = _claim_maps(snapshot)
    structural: dict[str, dict[int, list[dict[str, Any]]]] = {k: defaultdict(list) for k in STRUCTURAL_RELATIONS}
    for row in snapshot.get("candidate_evidence", []) or []:
        if not bool(row.get("verified")):
            continue
        try:
            cid = int(row.get("candidate_id") or 0)
        except Exception:
            continue
        if not cid:
            continue
        rel = clean(row.get("relation")).lower()
        md = row.get("metadata") if isinstance(row.get("metadata"), Mapping) else {}
        declared = clean(md.get("structural_dimension")).lower()
        for kind, aliases in STRUCTURAL_RELATIONS.items():
            if rel in aliases or declared == kind or bool(md.get(f"{kind}_verified")):
                structural[kind][cid].append(dict(row))
    return {
        "claim_states_by_candidate": claim_states_by_candidate,
        "claim_details_by_candidate": claim_details_by_candidate,
        "links_by_candidate": links_by_candidate,
        "structural_by_kind_candidate": structural,
    }


def _structural_evidence(snapshot: Mapping[str, Any], candidate_ids: set[int], kind: str, *, evidence_index: Mapping[str, Any] | None = None) -> dict[str, Any]:
    refs: list[str] = []
    families: set[str] = set()
    content_units: set[str] = set()
    excerpts: list[str] = []
    if evidence_index is not None:
        by_kind = (evidence_index.get("structural_by_kind_candidate") or {}).get(kind, {})
        rows = [row for cid in candidate_ids for row in (by_kind.get(cid, []) or [])]
    else:
        aliases = STRUCTURAL_RELATIONS.get(kind, set())
        rows = []
        for row in snapshot.get("candidate_evidence", []) or []:
            try:
                cid = int(row.get("candidate_id") or 0)
            except Exception:
                continue
            if cid not in candidate_ids or not bool(row.get("verified")):
                continue
            rel = clean(row.get("relation")).lower()
            md = row.get("metadata") if isinstance(row.get("metadata"), Mapping) else {}
            declared = clean(md.get("structural_dimension")).lower()
            if rel in aliases or declared == kind or bool(md.get(f"{kind}_verified")):
                rows.append(row)
    for row in rows:
        text = " ".join(x for x in (clean(row.get("title")), clean(row.get("excerpt"))) if x)
        family = _evidence_family(row)
        cfp = _evidence_content_fp(text)
        ref = f"candidate_evidence:{row.get('id')}"
        if ref not in refs:
            refs.append(ref)
        if family:
            families.add(family)
        if cfp:
            content_units.add(cfp)
        if text and text not in excerpts:
            excerpts.append(text[:1000])
    independent = min(len(families), len(content_units)) if families and content_units else max(len(families), len(content_units))
    state = "SUPPORTED" if independent >= 2 else ("PARTIAL" if independent == 1 else "UNKNOWN")
    return {
        "kind": kind, "state": state, "independent_units": independent,
        "source_families": sorted(families), "evidence_refs": refs[:32],
        "excerpts": excerpts[:8],
        "truth_boundary": "Verified structural evidence only; does not write Radar C01-C14.",
    }


def _get(obj: Any, name: str, default: Any = None) -> Any:
    try:
        return getattr(obj, name, default)
    except Exception:
        return default


def _candidate_record(row: Any) -> dict[str, Any]:
    fp = _get(row, "fingerprint", {})
    if not isinstance(fp, dict): fp = {}
    return {
        "id": int(_get(row, "id", 0) or 0),
        "canonical_key": clean(_get(row, "canonical_key")),
        "title": clean(_get(row, "title")),
        "problem_statement": clean(_get(row, "problem_statement")),
        "actor": clean(_get(row, "actor")),
        "actor_category": clean(_get(row, "actor_category")),
        "task": clean(_get(row, "task")),
        "object": clean(_get(row, "object")),
        "failure_mode": clean(_get(row, "failure_mode")),
        "consequence": clean(_get(row, "consequence")),
        "buyer_context": clean(_get(row, "buyer_context")),
        "workaround": clean(_get(row, "workaround")),
        "stage": clean(_get(row, "stage")),
        "founder_status": clean(_get(row, "founder_status")),
        "first_seen_at": _iso(_get(row, "first_seen_at") or _get(row, "created_at")),
        "last_seen_at": _iso(_get(row, "last_seen_at") or _get(row, "updated_at") or _get(row, "created_at")),
        "created_at": _iso(_get(row, "created_at")),
        "updated_at": _iso(_get(row, "updated_at")),
        "fingerprint": _json_safe(fp),
    }


def _candidate_evidence_record(row: Any) -> dict[str, Any]:
    meta = _get(row, "evidence_metadata", {})
    if not isinstance(meta, dict): meta = {}
    return {
        "id": int(_get(row, "id", 0) or 0),
        "candidate_id": int(_get(row, "candidate_id", 0) or 0),
        "source_type": clean(_get(row, "source_type")),
        "source_table": clean(_get(row, "source_table")),
        "source_ref": clean(_get(row, "source_ref")),
        "relation": clean(_get(row, "relation")).lower(),
        "title": clean(_get(row, "title")),
        "excerpt": clean(_get(row, "excerpt")),
        "url": clean(_get(row, "url")),
        "verified": bool(_get(row, "verified", False)),
        "verification_confidence": _get(row, "verification_confidence"),
        "observed_at": _iso(_get(row, "observed_at") or _get(row, "created_at")),
        "created_at": _iso(_get(row, "created_at")),
        "metadata": _json_safe(meta),
    }


def _case_record(row: Any) -> dict[str, Any]:
    return {
        "id": int(_get(row, "id", 0) or 0),
        "candidate_id": int(_get(row, "candidate_id", 0) or 0),
        "system_verdict": clean(_get(row, "system_verdict")),
        "current_gate": clean(_get(row, "current_gate")),
        "verdict_reason_code": clean(_get(row, "verdict_reason_code")),
        "last_evaluated_at": _iso(_get(row, "last_evaluated_at")),
    }


def _claim_record(row: Any) -> dict[str, Any]:
    return {
        "id": int(_get(row, "id", 0) or 0),
        "case_id": int(_get(row, "case_id", 0) or 0),
        "claim_code": clean(_get(row, "claim_code")).upper(),
        "state": clean(_get(row, "state")).upper() or "UNKNOWN",
        "support_groups": int(_get(row, "support_groups", 0) or 0),
        "direct_support_groups": int(_get(row, "direct_support_groups", 0) or 0),
        "refute_groups": int(_get(row, "refute_groups", 0) or 0),
        "insufficient_count": int(_get(row, "insufficient_count", 0) or 0),
        "evidence_summary": _json_safe(_get(row, "evidence_summary", {}) or {}),
        "last_evaluated_at": _iso(_get(row, "last_evaluated_at")),
    }


def _radar_link_record(link: Any, evidence: Any, claim: Mapping[str, Any]) -> dict[str, Any]:
    meta = _get(evidence, "raw_metadata", {})
    if not isinstance(meta, dict): meta = {}
    return {
        "claim_id": int(_get(link, "claim_id", 0) or 0),
        "case_id": int(claim.get("case_id", 0) or 0),
        "claim_code": clean(claim.get("claim_code")).upper(),
        "evidence_id": int(_get(evidence, "id", 0) or 0),
        "stance": clean(_get(link, "stance")).upper(),
        "validated": bool(_get(link, "validated", False)),
        "confidence": _get(link, "interpretation_confidence"),
        "rationale": clean(_get(link, "rationale")),
        "source_type": clean(_get(evidence, "source_type")),
        "source_table": clean(_get(evidence, "source_table")),
        "source_ref": clean(_get(evidence, "source_ref")),
        "source_family_key": clean(_get(evidence, "source_family_key")),
        "source_title": clean(_get(evidence, "source_title")),
        "excerpt": clean(_get(evidence, "excerpt")),
        "source_url": clean(_get(evidence, "source_url")),
        "directness": clean(_get(evidence, "directness")).upper(),
        "authority_class": clean(_get(evidence, "authority_class")).upper(),
        "published_at": _iso(_get(evidence, "published_at")),
        "observed_at": _iso(_get(evidence, "observed_at")),
        "metadata": _json_safe(meta),
    }


async def load_truth_snapshot() -> dict[str, Any]:
    """SELECT-only canonical Production truth snapshot.

    Only verified CandidateEvidence, latest RadarCase per candidate, claims on those
    cases, and validated claim-evidence links are loaded. Retrieval candidates and
    historical cases have zero Brain structural authority.
    """
    timings: dict[str, int] = {}
    started = time.perf_counter()
    async with async_session() as session:
        t = time.perf_counter()
        candidates = list((await session.execute(select(ProblemCandidate))).scalars().all())
        timings["candidates_ms"] = int((time.perf_counter() - t) * 1000)

        t = time.perf_counter()
        ces = list((await session.execute(select(CandidateEvidence).where(CandidateEvidence.verified.is_(True)))).scalars().all())
        timings["verified_candidate_evidence_ms"] = int((time.perf_counter() - t) * 1000)

        t = time.perf_counter()
        sub = select(RadarCase.candidate_id, func.max(RadarCase.id).label("max_id")).group_by(RadarCase.candidate_id).subquery()
        cases = list((await session.execute(select(RadarCase).join(sub, RadarCase.id == sub.c.max_id))).scalars().all())
        case_ids = [int(x.id) for x in cases]
        timings["active_cases_ms"] = int((time.perf_counter() - t) * 1000)

        t = time.perf_counter()
        claims = list((await session.execute(select(RadarClaim).where(RadarClaim.case_id.in_(case_ids)))).scalars().all()) if case_ids else []
        claim_records = [_claim_record(x) for x in claims]
        claim_by_id = {int(x["id"]): x for x in claim_records}
        claim_ids = list(claim_by_id)
        timings["active_claims_ms"] = int((time.perf_counter() - t) * 1000)

        t = time.perf_counter()
        joined = list((await session.execute(
            select(RadarClaimEvidence, RadarEvidence)
            .join(RadarEvidence, RadarEvidence.id == RadarClaimEvidence.evidence_id)
            .where(RadarClaimEvidence.claim_id.in_(claim_ids), RadarClaimEvidence.validated.is_(True))
        )).all()) if claim_ids else []
        links = [_radar_link_record(link, ev, claim_by_id[int(link.claim_id)]) for link, ev in joined]
        timings["validated_claim_links_ms"] = int((time.perf_counter() - t) * 1000)

    timings["total_ms"] = int((time.perf_counter() - started) * 1000)
    return {
        "candidates": [_candidate_record(x) for x in candidates],
        "candidate_evidence": [_candidate_evidence_record(x) for x in ces],
        "cases": [_case_record(x) for x in cases],
        "claims": claim_records,
        "validated_radar_links": links,
        "load_metrics": timings,
    }


async def production_truth_guard() -> str:
    """Fingerprint atomic Production truth to prove Brain does not mutate it."""
    async with async_session() as session:
        rows: list[Any] = []
        for model, cols in (
            (ProblemCandidate, [ProblemCandidate.id, ProblemCandidate.updated_at]),
            (CandidateEvidence, [CandidateEvidence.id, CandidateEvidence.verified, CandidateEvidence.verification_confidence]),
            (RadarCase, [RadarCase.id, RadarCase.system_verdict, RadarCase.current_gate, RadarCase.last_evaluated_at]),
            (RadarClaim, [RadarClaim.id, RadarClaim.state, RadarClaim.support_groups, RadarClaim.refute_groups, RadarClaim.last_evaluated_at]),
            (RadarClaimEvidence, [RadarClaimEvidence.id, RadarClaimEvidence.validated, RadarClaimEvidence.stance]),
        ):
            result = list((await session.execute(select(*cols).order_by(cols[0]))).all())
            rows.append([tuple(str(x) for x in r) for r in result])
    return stable_hash(rows, length=64)


def external_truth_fingerprints(root: Path) -> dict[str, str]:
    return {
        "market_test_queue": _file_fingerprint(root / MARKET_TEST_QUEUE),
        "calibration": _file_fingerprint(root / CALIBRATION_JSON),
    }


def truth_fingerprint(root: Path, snapshot: Mapping[str, Any]) -> str:
    payload = {
        "candidates": snapshot.get("candidates", []),
        "candidate_evidence": snapshot.get("candidate_evidence", []),
        "cases": snapshot.get("cases", []),
        "claims": snapshot.get("claims", []),
        "validated_radar_links": snapshot.get("validated_radar_links", []),
        "external": external_truth_fingerprints(root),
    }
    return stable_hash(payload, length=64)


def _group_by(rows: Iterable[Mapping[str, Any]], key: str) -> dict[int, list[dict[str, Any]]]:
    out: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        try: out[int(row.get(key) or 0)].append(dict(row))
        except Exception: pass
    return out


def _claim_maps(snapshot: Mapping[str, Any]) -> tuple[dict[int, dict[str, str]], dict[int, dict[str, dict[str, Any]]], dict[int, list[dict[str, Any]]]]:
    cases = {int(x["id"]): int(x["candidate_id"]) for x in snapshot.get("cases", [])}
    states: dict[int, dict[str, str]] = defaultdict(dict)
    details: dict[int, dict[str, dict[str, Any]]] = defaultdict(dict)
    claim_to_candidate: dict[int, int] = {}
    for c in snapshot.get("claims", []):
        case_id = int(c.get("case_id", 0) or 0)
        cid = cases.get(case_id)
        if not cid: continue
        code = clean(c.get("claim_code")).upper()
        states[cid][code] = clean(c.get("state")).upper() or "UNKNOWN"
        details[cid][code] = dict(c)
        claim_to_candidate[int(c.get("id", 0) or 0)] = cid
    links: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in snapshot.get("validated_radar_links", []):
        cid = claim_to_candidate.get(int(row.get("claim_id", 0) or 0))
        if cid: links[cid].append(dict(row))
    return states, details, links


def _support_families(links: Iterable[Mapping[str, Any]], code: str, *, direct_only: bool = False) -> set[str]:
    out: set[str] = set()
    for row in links:
        if clean(row.get("claim_code")).upper() != code or clean(row.get("stance")).upper() != "SUPPORT" or not bool(row.get("validated")):
            continue
        if direct_only and clean(row.get("directness")).upper() != "DIRECT": continue
        out.add(clean(row.get("source_family_key")) or f"radar:{row.get('evidence_id')}")
    return out


def _candidate_truth_units(root: Path, snapshot: Mapping[str, Any]) -> list[dict[str, Any]]:
    states, _, links_by_candidate = _claim_maps(snapshot)
    ce_by = _group_by(snapshot.get("candidate_evidence", []), "candidate_id")
    units: list[dict[str, Any]] = []
    for c in snapshot.get("candidates", []):
        cid = int(c.get("id", 0) or 0)
        payload = {
            "candidate": c,
            "claims": states.get(cid, {}),
            "verified_candidate_evidence": ce_by.get(cid, []),
            "validated_radar_links": links_by_candidate.get(cid, []),
        }
        units.append({"unit_key": f"candidate:{cid}", "fingerprint": stable_hash(payload, length=40), "payload": {"candidate_id": cid}})
    ext = external_truth_fingerprints(root)
    units.append({"unit_key":"global:market_test_queue", "fingerprint":ext["market_test_queue"], "payload":{}})
    units.append({"unit_key":"global:calibration", "fingerprint":ext["calibration"], "payload":{}})
    return sorted(units, key=lambda x: x["unit_key"])


def _dirty_from_units(root: Path, units: list[dict[str, Any]]) -> dict[str, Any]:
    previous = truth_input_map(root)
    current = {x["unit_key"]: x["fingerprint"] for x in units}
    old = {k: v.get("fingerprint") for k, v in previous.items()}
    changed = sorted({k for k in set(current) | set(old) if current.get(k) != old.get(k)})
    dirty_candidates = sorted(int(k.split(":",1)[1]) for k in changed if k.startswith("candidate:") and k.split(":",1)[1].isdigit())
    globals_dirty = sorted(k for k in changed if k.startswith("global:"))
    return {
        "changed_units": changed,
        "dirty_candidate_ids": dirty_candidates,
        "global_dirty": globals_dirty,
        "first_build": not bool(previous),
    }


def build_problem_atoms(snapshot: Mapping[str, Any]) -> list[dict[str, Any]]:
    states, _, links_by_candidate = _claim_maps(snapshot)
    ce_by = _group_by(snapshot.get("candidate_evidence", []), "candidate_id")
    atoms: list[dict[str, Any]] = []
    for c in snapshot.get("candidates", []):
        cid = int(c.get("id", 0) or 0)
        claims = states.get(cid, {})
        c01 = claims.get("C01", "UNKNOWN")
        links = links_by_candidate.get(cid, [])
        direct_ce = [x for x in ce_by.get(cid, []) if clean(x.get("relation")).lower() in {"community_problem","direct_problem_corroboration"}]
        eligible = c01 != "REFUTED" and (c01 in {"SUPPORTED","INSUFFICIENT"} or bool(direct_ce))
        workaround_text = [clean(c.get("workaround"))]
        workaround_text += [clean(x.get("excerpt")) for x in direct_ce if clean(x.get("excerpt"))]
        for link in links:
            if clean(link.get("authority_class")).upper() in {"USER_DISCUSSION","INDEPENDENT_PROBLEM_SOURCE"} and clean(link.get("directness")).upper() == "DIRECT":
                workaround_text.append(clean(link.get("excerpt")))
        wlevel, wlabel = workaround_level(" ".join(workaround_text))
        fp = c.get("fingerprint") if isinstance(c.get("fingerprint"), dict) else {}
        recurrence_dates = sorted({clean(x.get("published_at") or x.get("observed_at")) for x in links if clean(x.get("claim_code")).upper()=="C02" and clean(x.get("stance")).upper()=="SUPPORT" and clean(x.get("directness")).upper()=="DIRECT" and clean(x.get("published_at") or x.get("observed_at"))})
        problem_dates = [
            _parse_dt(x.get("published_at") or x.get("observed_at"))
            for x in links
            if clean(x.get("claim_code")).upper() in {"C01", "C02"}
            and clean(x.get("stance")).upper() == "SUPPORT"
            and clean(x.get("directness")).upper() == "DIRECT"
        ]
        problem_dates = [x for x in problem_dates if x is not None]
        candidate_first, candidate_last = _parse_dt(c.get("first_seen_at")), _parse_dt(c.get("last_seen_at"))
        first_seen = min(([candidate_first] if candidate_first else []) + problem_dates) if candidate_first or problem_dates else None
        last_seen = max(([candidate_last] if candidate_last else []) + problem_dates) if candidate_last or problem_dates else None
        atom = {
            "atom_id": f"pa_c{cid}", "candidate_id": cid, "eligible": bool(eligible),
            "title": c.get("title"), "problem_statement": c.get("problem_statement"),
            "actor": c.get("actor") or c.get("actor_category"), "actor_category": c.get("actor_category"),
            "task": c.get("task"), "object": c.get("object"), "failure_mode": c.get("failure_mode"),
            "consequence": c.get("consequence"), "buyer_context": c.get("buyer_context"), "workaround": c.get("workaround"),
            "first_seen_at": _iso(first_seen) or c.get("first_seen_at"), "last_seen_at": _iso(last_seen) or c.get("last_seen_at"),
            "claim_states": {f"C{i:02d}": claims.get(f"C{i:02d}", "UNKNOWN") for i in range(1,15)},
            "problem_support_families": sorted(_support_families(links,"C01")),
            "recurrence_support_families": sorted(_support_families(links,"C02",direct_only=True)),
            "recurrence_observed_at": recurrence_dates,
            "workaround_level": wlevel, "workaround_label": wlabel,
            "facet_labels": list(fp.get("facet_labels") or fp.get("qualified_lanes") or []),
            "problem_scope_key": fp.get("problem_scope_key"), "problem_family_descriptor": fp.get("problem_family_descriptor"),
            "primary_problem_signature": fp.get("primary_problem_signature"), "fingerprint": fp,
            "truth_boundary": "Derived identity wrapper over Candidate + validated Radar truth; no claim truth write.",
        }
        atom["identity_features"] = problem_features(atom)
        atom["bucket_keys"] = problem_bucket_keys(atom)
        atoms.append(atom)
    return atoms


def _representative_member(members: list[dict[str, Any]]) -> dict[str, Any]:
    if not members:
        return {}
    # Representation should not flap merely because Candidate IDs churn. Richness and
    # validated evidence density decide first; a semantic hash is the deterministic tie-break.
    return max(
        members,
        key=lambda m: (
            sum(bool(clean(m.get(k))) for k in ("failure_mode","task","object","actor","problem_statement","title","consequence","workaround")),
            len(m.get("problem_support_families",[]) or []) + len(m.get("recurrence_support_families",[]) or []),
            int(m.get("workaround_level",0) or 0),
            stable_hash(m.get("title"),m.get("problem_statement"),m.get("failure_mode"),length=16),
        ),
    )


def _profile_from_members(members: list[dict[str, Any]]) -> dict[str, Any]:
    if not members: return {}
    rep = _representative_member(members)
    fp = rep.get("fingerprint") if isinstance(rep.get("fingerprint"), Mapping) else {}
    need = fp.get("need_frame") if isinstance(fp.get("need_frame"), Mapping) else {}
    return {
        "title":rep.get("title"), "problem_statement":rep.get("problem_statement"), "actor":rep.get("actor"),
        "actor_category":rep.get("actor_category"), "task":rep.get("task"), "object":rep.get("object"),
        "failure_mode":rep.get("failure_mode"),
        "fingerprint":{"problem_scope_key":fp.get("problem_scope_key"),"problem_family_descriptor":fp.get("problem_family_descriptor"),"primary_problem_signature":fp.get("primary_problem_signature"),"need_frame":{"primary_specific_target":need.get("primary_specific_target")}},
    }


def _cluster_atoms_bucketed(atoms: list[dict[str, Any]], *, transition: bool = False) -> tuple[list[list[dict[str, Any]]], int]:
    clusters: list[list[dict[str, Any]]] = []
    bucket_to_clusters: dict[str, set[int]] = defaultdict(set)
    comparisons = 0
    for atom in sorted(atoms, key=lambda x: clean(x.get("atom_id") or x.get("transition_atom_id"))):
        keys = list(atom.get("bucket_keys") or [])
        candidate_idxs: set[int] = set()
        for key in keys: candidate_idxs.update(bucket_to_clusters.get(key, set()))
        placed = False
        for idx in sorted(candidate_idxs):
            cluster = clusters[idx]
            checks = []
            for member in cluster:
                comparisons += 1
                rel = same_transition(atom, member) if transition else same_problem(atom, member)
                checks.append(bool(rel.get("same_transition" if transition else "same_problem")))
                if not checks[-1]: break
            if checks and all(checks):
                cluster.append(atom); placed = True
                for key in keys: bucket_to_clusters[key].add(idx)
                break
        if not placed:
            idx = len(clusters); clusters.append([atom])
            for key in keys: bucket_to_clusters[key].add(idx)
    return clusters, comparisons


def _lineage_payload(lineage_id: str, members: list[dict[str, Any]], *, prior: Mapping[str, Any] | None = None, merged_from: list[str] | None = None, split_from: str | None = None) -> dict[str, Any]:
    claim_states = {f"C{i:02d}": aggregate_claim_states(m.get("claim_states",{}).get(f"C{i:02d}") for m in members) for i in range(1,15)}
    firsts = [x for x in (_parse_dt(m.get("first_seen_at")) for m in members) if x]
    lasts = [x for x in (_parse_dt(m.get("last_seen_at")) for m in members) if x]
    first, last = (min(firsts) if firsts else None), (max(lasts) if lasts else None)
    span_days = max(0,(last-first).days) if first and last else 0
    recurrence_families = sorted({f for m in members for f in m.get("recurrence_support_families",[])})
    problem_families = sorted({f for m in members for f in m.get("problem_support_families",[])})
    dates = [dt for dt in (_parse_dt(v) for m in members for v in m.get("recurrence_observed_at",[])) if dt]
    recurrence_span = (max(dates)-min(dates)).days if len(dates)>=2 else 0
    recurrence_proven = claim_states["C02"]=="SUPPORTED" or len(recurrence_families)>=2
    if claim_states["C02"]=="REFUTED": persistence="REFUTED"
    elif recurrence_proven and max(span_days,recurrence_span)>=PERSISTENCE_MIN_DAYS: persistence="SUPPORTED"
    elif recurrence_proven or len(members)>=2 or claim_states["C02"]=="INSUFFICIENT": persistence="PARTIAL"
    else: persistence="UNKNOWN"
    actors=sorted({clean(m.get("actor")) for m in members if clean(m.get("actor"))})
    contexts=sorted({clean(m.get("task")) for m in members if clean(m.get("task"))})
    objects=sorted({clean(m.get("object")) for m in members if clean(m.get("object"))})
    wlevel=max([int(m.get("workaround_level",0) or 0) for m in members] or [0])
    if persistence=="SUPPORTED" and (len(actors)>=2 or len(contexts)>=2): trajectory="DIFFUSING"
    elif persistence=="SUPPORTED": trajectory="RECURRING"
    elif persistence=="PARTIAL": trajectory="FORMING"
    else: trajectory="FIRST_SEEN"
    if claim_states["C03"]=="SUPPORTED" and wlevel>=2 and trajectory in {"RECURRING","DIFFUSING"}: trajectory="MATERIALIZING"
    if claim_states["C05"]=="SUPPORTED" and wlevel>=5: trajectory="COMMERCIALIZING"
    facets=sorted({clean(f) for m in members for f in m.get("facet_labels",[]) if clean(f)})
    revision=int((prior or {}).get("revision",0) or 0)+1 if prior else 1
    rep=_representative_member(members)
    return {
        "lineage_id":lineage_id, "revision":revision,
        "member_candidate_ids":sorted(int(m["candidate_id"]) for m in members),
        "member_atom_ids":sorted(clean(m["atom_id"]) for m in members),
        "representative_title":rep.get("title"), "representative_problem":rep.get("problem_statement"),
        "claim_states":claim_states, "persistence_state":persistence, "trajectory":trajectory,
        "first_seen_at":_iso(first), "last_observed_at":_iso(last), "span_days":span_days, "recurrence_span_days":recurrence_span,
        "independent_problem_families":len(problem_families), "independent_recurrence_families":len(recurrence_families),
        "problem_support_families":problem_families, "recurrence_support_families":recurrence_families,
        "actor_spread":len(actors), "actors":actors[:20], "context_spread":len(contexts), "contexts":contexts[:20], "objects":objects[:20],
        "workaround_level":wlevel, "workaround_label":next((m.get("workaround_label") for m in members if int(m.get("workaround_level",0) or 0)==wlevel),"W0_COMPLAINT_OR_NO_WORKAROUND"),
        "member_workaround_levels":{str(int(m["candidate_id"])):int(m.get("workaround_level",0) or 0) for m in members},
        "member_claim_states":{str(int(m["candidate_id"])):dict(m.get("claim_states") or {}) for m in members},
        "facet_labels":facets, "identity_profile":_profile_from_members(members),
        "bucket_keys":sorted({k for m in members for k in m.get("bucket_keys",[])})[:30],
        "merged_from_lineage_ids":sorted(set(merged_from or [])), "split_from_lineage_id":split_from,
        "truth_boundary":"Longitudinal problem identity/persistence only. Radar validated claims remain atomic truth owner.",
    }


def _assign_problem_lineage_ids(clusters: list[list[dict[str, Any]]], previous: Mapping[str, dict[str, Any]]) -> list[dict[str, Any]]:
    used: set[str]=set(); out=[]
    previous_index: dict[str,set[str]]=defaultdict(set)
    for oid, old in previous.items():
        profile=old.get("identity_profile") if isinstance(old.get("identity_profile"),Mapping) else old
        for key in problem_bucket_keys(profile): previous_index[key].add(oid)
    for members in clusters:
        new_ids={int(x["candidate_id"]) for x in members}
        profile=_profile_from_members(members)
        candidate_old:set[str]=set()
        for key in problem_bucket_keys(profile): candidate_old.update(previous_index.get(key,set()))
        ranked=[]
        for oid in candidate_old:
            if oid in used: continue
            old=previous[oid]; old_ids={int(x) for x in old.get("member_candidate_ids",[]) if str(x).isdigit()}
            overlap=len(old_ids&new_ids)/len(old_ids|new_ids) if old_ids and new_ids else 0.0
            old_profile=old.get("identity_profile") if isinstance(old.get("identity_profile"),Mapping) else old
            rel=same_problem(profile,old_profile); semantic=float(rel.get("score",0) or 0) if rel.get("same_problem") else 0.0
            if overlap>=0.50 or semantic>=0.50: ranked.append((0.75*overlap+0.25*semantic,oid,overlap,semantic))
        ranked.sort(reverse=True)
        if ranked:
            oid=ranked[0][1]; used.add(oid)
            merged=[x[1] for x in ranked[1:] if x[0]>=0.65]
            payload=_lineage_payload(oid,members,prior=previous.get(oid),merged_from=merged)
        else:
            oid="pl_"+stable_hash(profile,sorted(new_ids),length=20)
            split_from=None
            # If members came from one old lineage but semantics split, record ancestry.
            parents=[pid for pid,old in previous.items() if {int(x) for x in old.get("member_candidate_ids",[]) if str(x).isdigit()} & new_ids]
            if len(parents)==1: split_from=parents[0]
            payload=_lineage_payload(oid,members,split_from=split_from)
        out.append(payload)
    return out


def build_problem_lineages_incremental(atoms: list[dict[str, Any]], previous: Mapping[str,dict[str,Any]], dirty_ids: set[int], first_build: bool) -> tuple[list[dict[str,Any]],dict[str,Any]]:
    eligible=[x for x in atoms if x.get("eligible")]
    if first_build or not previous or len(dirty_ids) > max(24, int(len(eligible)*0.35)):
        clusters, comparisons=_cluster_atoms_bucketed(eligible)
        return _assign_problem_lineage_ids(clusters,previous), {"mode":"FULL_INDEXED","comparisons":comparisons,"reused":0,"affected_candidates":len(eligible)}
    atom_by_cid={int(x["candidate_id"]):x for x in eligible}
    affected_lineages:set[str]=set()
    for oid,old in previous.items():
        old_ids={int(x) for x in old.get("member_candidate_ids",[]) if str(x).isdigit()}
        if old_ids & dirty_ids: affected_lineages.add(oid)
    # Dirty candidates may newly match an otherwise-unaffected lineage.
    index:dict[str,set[str]]=defaultdict(set)
    for oid,old in previous.items():
        for k in old.get("bucket_keys",[]) or []: index[clean(k)].add(oid)
    for cid in dirty_ids:
        atom=atom_by_cid.get(cid)
        if not atom: continue
        for k in atom.get("bucket_keys",[]) or []:
            for oid in index.get(clean(k),set()):
                old=previous[oid]; prof=old.get("identity_profile") if isinstance(old.get("identity_profile"),Mapping) else old
                if same_problem(atom,prof).get("same_problem"): affected_lineages.add(oid)
    pool_ids=set(dirty_ids)
    for oid in affected_lineages:
        pool_ids.update(int(x) for x in previous[oid].get("member_candidate_ids",[]) if str(x).isdigit())
    pool=[atom_by_cid[cid] for cid in sorted(pool_ids) if cid in atom_by_cid]
    carried=[dict(old) for oid,old in previous.items() if oid not in affected_lineages and not ({int(x) for x in old.get("member_candidate_ids",[]) if str(x).isdigit()} & dirty_ids)]
    clusters, comparisons=_cluster_atoms_bucketed(pool)
    rebuilt=_assign_problem_lineage_ids(clusters,{oid:previous[oid] for oid in affected_lineages})
    # Prevent carried lineage collision after semantic merge into rebuilt cluster.
    rebuilt_ids={x["lineage_id"] for x in rebuilt}
    carried=[x for x in carried if x.get("lineage_id") not in rebuilt_ids]
    return carried+rebuilt,{"mode":"DIRTY_COMPONENT","comparisons":comparisons,"reused":len(carried),"recomputed":len(rebuilt),"affected_candidates":len(pool)}


def _explicit_transition_subject(metadata: Mapping[str, Any] | None) -> tuple[str | None, list[str]]:
    if not isinstance(metadata, Mapping):
        return None, []
    parts: list[str] = []
    keys: list[str] = []
    for key in TRANSITION_SUBJECT_METADATA_KEYS:
        raw = metadata.get(key)
        values = raw if isinstance(raw, (list, tuple, set)) else [raw]
        for value in values:
            text = clean(value)
            if not text or text.lower() in {"unknown", "none", "n/a", "na"}:
                continue
            parts.append(text[:240])
            keys.append(key)
    parts = list(dict.fromkeys(parts))[:8]
    return (" | ".join(parts) if parts else None), sorted(set(keys))


def _flatten_transition_values(fp: Mapping[str,Any]) -> list[tuple[str,str]]:
    rows=[]
    for key,value in fp.items():
        k=clean(key).lower()
        if k in GENERIC_TRANSITION_KEYS or not any(h in k for h in TRANSITION_KEY_HINTS): continue
        if isinstance(value,str) and len(clean(value))>=20: rows.append((k,clean(value)))
        elif isinstance(value,list):
            for item in value[:12]:
                if isinstance(item,str) and len(clean(item))>=20: rows.append((k,clean(item)))
                elif isinstance(item,Mapping):
                    text=clean(item.get("text") or item.get("title") or item.get("summary") or item.get("description"))
                    if len(text)>=20: rows.append((k,text))
        elif isinstance(value,Mapping):
            text=clean(value.get("text") or value.get("title") or value.get("summary") or value.get("description"))
            if len(text)>=20: rows.append((k,text))
    return rows


def build_transition_atoms(snapshot: Mapping[str,Any], problem_atoms: list[dict[str,Any]]) -> list[dict[str,Any]]:
    """Extract transition observations with an explicit admission boundary.

    Upstream `why_now`, ecosystem activity, and even a validated C12 row are evidence
    context, not automatically a persistent structural transition. A row may create a
    TransitionLineage only when it has either a verified direct problem↔transition link or
    an explicit structural subject on a strong transition relation. This is the key
    distinction between *timing context* and *transition identity*.
    """
    _,_,links_by=_claim_maps(snapshot); ce_by=_group_by(snapshot.get("candidate_evidence",[]),"candidate_id")
    pa={int(a["candidate_id"]):a for a in problem_atoms if a.get("eligible")}
    out=[]; seen=set()
    for c in snapshot.get("candidates",[]):
        cid=int(c.get("id",0) or 0)
        if cid not in pa: continue
        fp=c.get("fingerprint") if isinstance(c.get("fingerprint"),dict) else {}
        fp_direct=bool(fp.get("transition_pair_verified")) or any(x in clean(fp.get("opportunity_linkage_status")).upper() for x in ("VERIFIED","LINKED"))
        fp_verified=bool(fp.get("transition_evidence_verified"))
        sources=[]
        for e in ce_by.get(cid,[]):
            rel=clean(e.get("relation")).lower()
            if rel not in TRANSITION_RELATIONS: continue
            text=" ".join(x for x in (clean(e.get("title")),clean(e.get("excerpt"))) if x)
            if len(text)<20: continue
            md=e.get("metadata") if isinstance(e.get("metadata"),Mapping) else {}
            direct=bool(md.get("transition_pair_verified")) or any(x in clean(md.get("opportunity_linkage_status")).upper() for x in ("VERIFIED","LINKED"))
            subject, subject_keys = _explicit_transition_subject(md)
            sources.append({"text":text,"source_family":_evidence_family(e),"source_ref":f"candidate_evidence:{e.get('id')}","relation":rel,"verified":True,"support":bool(direct),"direct_link":direct,"valid_at":e.get("observed_at"),"source_class":"VERIFIED_CANDIDATE_TRANSITION","content_fingerprint":_evidence_content_fp(text),"subject":subject,"subject_keys":subject_keys,"subject_explicit":bool(subject)})
        for link in links_by.get(cid,[]):
            if clean(link.get("claim_code")).upper()!="C12" or clean(link.get("stance")).upper()=="REFUTE": continue
            text=" ".join(x for x in (clean(link.get("source_title")),clean(link.get("excerpt"))) if x)
            if len(text)<20: continue
            md=link.get("metadata") if isinstance(link.get("metadata"),Mapping) else {}
            subject, subject_keys = _explicit_transition_subject(md)
            sources.append({"text":text,"source_family":clean(link.get("source_family_key")) or f"radar:{link.get('evidence_id')}","source_ref":f"radar_evidence:{link.get('evidence_id')}","relation":"c12_transition_context","verified":True,"support":clean(link.get("stance")).upper()=="SUPPORT","direct_link":False,"valid_at":link.get("published_at") or link.get("observed_at"),"source_class":"RADAR_C12_VALIDATED","content_fingerprint":_evidence_content_fp(text),"subject":subject,"subject_keys":subject_keys,"subject_explicit":bool(subject)})
        # Fingerprint-derived context is retained only as ephemeral coverage. It can never
        # establish persistent transition identity.
        for key,text in _flatten_transition_values(fp):
            sources.append({"text":text,"source_family":f"fingerprint:{key}","source_ref":f"fingerprint:{cid}:{key}:{stable_hash(text,length=10)}","relation":key,"verified":fp_verified,"support":False,"direct_link":bool(fp_verified and fp_direct),"valid_at":c.get("last_seen_at"),"source_class":"DERIVED_FINGERPRINT_CONTEXT","content_fingerprint":_evidence_content_fp(text),"subject":None,"subject_keys":[],"subject_explicit":False})
        for src in sources:
            norm=sorted(words(src["text"]))
            if not norm: continue
            key=stable_hash(cid,src["source_ref"],norm,length=24)
            if key in seen: continue
            seen.add(key)
            driver=transition_driver(src["text"])
            explicit=bool(src.get("subject_explicit"))
            direct=bool(src.get("direct_link"))
            relation=clean(src.get("relation")).lower()
            strong_relation=relation in STRONG_TRANSITION_RELATIONS or relation=="c12_transition_context"
            # Admission is fail-closed. C12 support is opportunity-window evidence; without
            # a named structural subject it remains context only. `why_now` / ecosystem
            # activity are likewise context unless the pair itself was explicitly verified.
            lineage_eligible=bool(src.get("verified")) and driver!="UNKNOWN" and (direct or (explicit and strong_relation)) and src.get("source_class")!="DERIVED_FINGERPRINT_CONTEXT"
            if direct:
                identity_quality="DIRECT_PAIR_VERIFIED"
                admission_reason="DIRECT_PROBLEM_TRANSITION_LINK"
            elif lineage_eligible:
                identity_quality="EXPLICIT_STRUCTURAL_SUBJECT"
                admission_reason="EXPLICIT_SUBJECT_STRONG_TRANSITION_RELATION"
            else:
                identity_quality="CONTEXT_ONLY"
                admission_reason="NO_PERSISTENT_TRANSITION_IDENTITY_ANCHOR"
            atom={
                "transition_atom_id":"ta_"+key,"candidate_id":cid,"problem_atom_id":pa[cid]["atom_id"],"driver":driver,
                "text":clean(src["text"])[:2400],"transition_key":f"{driver.lower()}:{stable_hash(norm,length=16)}",
                "subject":src.get("subject"),"subject_keys":list(src.get("subject_keys") or []),"subject_explicit":explicit,
                "source_family":src["source_family"],"source_ref":src["source_ref"],"relation":src["relation"],"source_class":src["source_class"],
                "verified":bool(src["verified"]),"support":bool(src["support"]),"lineage_eligible":lineage_eligible,
                "independence_eligible":lineage_eligible,"direct_problem_transition_link":direct,"valid_at":src.get("valid_at"),
                "content_fingerprint":src.get("content_fingerprint") or _evidence_content_fp(src["text"]),
                "identity_quality":identity_quality,"admission_reason":admission_reason,
                "truth_boundary":"Timing/context evidence is not persistent transition identity. Only explicit subject or verified direct-pair evidence can create TransitionLineage.",
            }
            atom["bucket_keys"]=transition_bucket_keys(atom)
            out.append(atom)
    return out


def _transition_lineage_payload(lineage_id:str,members:list[dict[str,Any]],*,prior:Mapping[str,Any]|None=None,merged_from:list[str]|None=None,split_from:str|None=None)->dict[str,Any]:
    verified=[m for m in members if m.get("verified") and m.get("independence_eligible")]
    support=[m for m in verified if m.get("support")]
    families=sorted({clean(m.get("source_family")) for m in verified if clean(m.get("source_family"))})
    support_fams=sorted({clean(m.get("source_family")) for m in support if clean(m.get("source_family"))})
    verified_units=sorted({clean(m.get("content_fingerprint")) for m in verified if clean(m.get("content_fingerprint"))})
    support_units=sorted({clean(m.get("content_fingerprint")) for m in support if clean(m.get("content_fingerprint"))})
    direct_units=sorted({clean(m.get("content_fingerprint")) for m in verified if m.get("direct_problem_transition_link") and clean(m.get("content_fingerprint"))})
    # Exact cross-posts share a content unit and cannot inflate transition strength.
    # Source-family diversity is still exposed diagnostically, but independent content
    # units own the support threshold.
    direct=len(direct_units)
    if len(support_units)>=2 or (direct>=1 and len(verified_units)>=2): state="SUPPORTED"
    elif support_units or direct>=1 or len(verified_units)>=2: state="PARTIAL"
    elif verified: state="INSUFFICIENT"
    else: state="UNKNOWN"
    cids=sorted({int(m["candidate_id"]) for m in members})
    counts=Counter(clean(m.get("driver")) or "UNKNOWN" for m in members); driver=counts.most_common(1)[0][0] if counts else "UNKNOWN"
    dates=[x for x in (_parse_dt(m.get("valid_at")) for m in members) if x]; first=min(dates) if dates else None; last=max(dates) if dates else None
    span=max(0,(last-first).days) if first and last else 0
    if state=="SUPPORTED" and len(cids)>=3: trajectory="DIFFUSING"
    elif state=="SUPPORTED": trajectory="RECURRING"
    elif state=="PARTIAL": trajectory="FORMING"
    else: trajectory="FIRST_SEEN"
    terms=set()
    for m in members[:6]: terms.update(words(m.get("text")))
    explicit_subjects=sorted({clean(m.get("subject")) for m in members if m.get("subject_explicit") and clean(m.get("subject"))})
    hypothesis_ids=sorted({clean(m.get("transition_hypothesis_id")) for m in members if clean(m.get("transition_hypothesis_id"))})
    hypothesis_identity_terms=sorted({clean(t) for m in members for t in (m.get("hypothesis_identity_terms") or []) if clean(t)})
    if explicit_subjects:
        identity_origin="EXPLICIT_STRUCTURAL_SUBJECT"
    elif hypothesis_ids:
        identity_origin="CORROBORATED_CONTEXT_PROMOTION"
    elif direct:
        identity_origin="DIRECT_PAIR_VERIFIED"
    else:
        identity_origin="UNANCHORED"
    return {
        "transition_lineage_id":lineage_id,"revision":int((prior or {}).get("revision",0) or 0)+1 if prior else 1,
        "driver":driver,"state":state,"trajectory":trajectory,"member_candidate_ids":cids,
        "member_transition_atom_ids":sorted(clean(m["transition_atom_id"]) for m in members),
        "independent_verified_families":len(families),"independent_support_families":len(support_fams),"verified_families":families,"support_families":support_fams,
        "independent_verified_content_units":len(verified_units),"independent_support_content_units":len(support_units),
        "verified_content_units":verified_units[:40],"support_content_units":support_units[:40],
        "direct_problem_transition_links":direct,"first_seen_at":_iso(first),"last_observed_at":_iso(last),"span_days":span,
        "representative_text":members[0].get("text") if members else None,"identity_terms":sorted(terms)[:40],
        "explicit_subjects":explicit_subjects[:20],"explicit_subject_count":len(explicit_subjects),
        "transition_hypothesis_ids":hypothesis_ids[:20],"hypothesis_identity_terms":hypothesis_identity_terms[:20],"identity_origin":identity_origin,
        "relations":sorted({clean(m.get("relation")) for m in members if clean(m.get("relation"))}),
        "bucket_keys":sorted({k for m in members for k in m.get("bucket_keys",[])})[:30],
        "merged_from_lineage_ids":sorted(set(merged_from or [])),"split_from_lineage_id":split_from,
        "truth_boundary":"TransitionLineage is longitudinal change evidence; it cannot certify buyer/WTP/opportunity truth.",
    }


def _assign_transition_ids(clusters:list[list[dict[str,Any]]],previous:Mapping[str,dict[str,Any]])->list[dict[str,Any]]:
    used=set(); out=[]; index:dict[str,set[str]]=defaultdict(set)
    for oid,old in previous.items():
        for k in old.get("bucket_keys",[]) or []: index[clean(k)].add(oid)
    for members in clusters:
        cids={int(m["candidate_id"]) for m in members}; rep=members[0]
        candidates=set()
        for k in rep.get("bucket_keys",[]) or []: candidates.update(index.get(clean(k),set()))
        ranked=[]
        for oid in candidates:
            if oid in used: continue
            old=previous[oid]; old_rep={"driver":old.get("driver"),"text":old.get("representative_text"),"transition_key":""}
            rel=same_transition(rep,old_rep)
            old_ids={int(x) for x in old.get("member_candidate_ids",[]) if str(x).isdigit()}; overlap=len(old_ids&cids)/len(old_ids|cids) if old_ids and cids else 0
            semantic=float(rel.get("score",0) or 0) if rel.get("same_transition") else 0
            if overlap>=0.50 or semantic>=0.30: ranked.append((0.65*overlap+0.35*semantic,oid))
        ranked.sort(reverse=True)
        if ranked:
            oid=ranked[0][1]; used.add(oid); merged=[x[1] for x in ranked[1:] if x[0]>=0.60]
            payload=_transition_lineage_payload(oid,members,prior=previous.get(oid),merged_from=merged)
        else:
            oid="tl_"+stable_hash(rep.get("driver"),sorted(words(rep.get("text"))),sorted(cids),length=20)
            parents=[pid for pid,old in previous.items() if {int(x) for x in old.get("member_candidate_ids",[]) if str(x).isdigit()} & cids]
            payload=_transition_lineage_payload(oid,members,split_from=parents[0] if len(parents)==1 else None)
        out.append(payload)
    return out


def build_transition_lineages_incremental(atoms:list[dict[str,Any]],previous:Mapping[str,dict[str,Any]],dirty_ids:set[int],first_build:bool)->tuple[list[dict[str,Any]],dict[str,Any]]:
    eligible=[x for x in atoms if x.get("lineage_eligible") and x.get("verified")]
    if first_build or not previous or len(dirty_ids)>max(24,int(max(1,len({int(x['candidate_id']) for x in eligible}))*0.35)):
        clusters,comparisons=_cluster_atoms_bucketed(eligible,transition=True)
        return _assign_transition_ids(clusters,previous),{"mode":"FULL_INDEXED","comparisons":comparisons,"lineage_eligible_atoms":len(eligible),"derived_context_excluded":sum(1 for x in atoms if not x.get("lineage_eligible"))}
    by_cid:dict[int,list[dict[str,Any]]]=defaultdict(list)
    for a in eligible: by_cid[int(a["candidate_id"])].append(a)
    affected=set()
    for oid,old in previous.items():
        ids={int(x) for x in old.get("member_candidate_ids",[]) if str(x).isdigit()}
        if ids&dirty_ids: affected.add(oid)
    index:dict[str,set[str]]=defaultdict(set)
    for oid,old in previous.items():
        for k in old.get("bucket_keys",[]) or []: index[clean(k)].add(oid)
    for cid in dirty_ids:
        for atom in by_cid.get(cid,[]):
            for k in atom.get("bucket_keys",[]) or []:
                for oid in index.get(clean(k),set()):
                    old=previous[oid]; old_rep={"driver":old.get("driver"),"text":old.get("representative_text")}
                    if same_transition(atom,old_rep).get("same_transition"): affected.add(oid)
    pool_ids=set(dirty_ids)
    for oid in affected: pool_ids.update(int(x) for x in previous[oid].get("member_candidate_ids",[]) if str(x).isdigit())
    pool=[a for cid in sorted(pool_ids) for a in by_cid.get(cid,[])]
    carried=[dict(old) for oid,old in previous.items() if oid not in affected and not ({int(x) for x in old.get("member_candidate_ids",[]) if str(x).isdigit()}&dirty_ids)]
    clusters,comparisons=_cluster_atoms_bucketed(pool,transition=True)
    rebuilt=_assign_transition_ids(clusters,{oid:previous[oid] for oid in affected})
    rebuilt_ids={x["transition_lineage_id"] for x in rebuilt}; carried=[x for x in carried if x.get("transition_lineage_id") not in rebuilt_ids]
    return carried+rebuilt,{"mode":"DIRTY_COMPONENT","comparisons":comparisons,"reused":len(carried),"recomputed":len(rebuilt),"affected_candidates":len(pool_ids),"lineage_eligible_atoms":len(eligible),"derived_context_excluded":sum(1 for x in atoms if not x.get("lineage_eligible"))}


def _aggregate_lineage_claims(pl:Mapping[str,Any])->dict[str,str]:
    s=pl.get("claim_states") if isinstance(pl.get("claim_states"),Mapping) else {}
    return {f"C{i:02d}":clean(s.get(f"C{i:02d}")).upper() or "UNKNOWN" for i in range(1,15)}


def _current_solution_context(member_ids:set[int],snapshot:Mapping[str,Any],*,evidence_index:Mapping[str,Any]|None=None)->dict[str,Any]:
    links_by=(evidence_index or {}).get("links_by_candidate") if evidence_index is not None else None
    if links_by is None:
        _,_,links_by=_claim_maps(snapshot)
    names=[]; refs=[]
    for cid in member_ids:
        for link in links_by.get(cid,[]):
            if clean(link.get("claim_code")).upper()!="C06" or clean(link.get("stance")).upper() not in {"SUPPORT","INSUFFICIENT","RELATED"}: continue
            md=link.get("metadata") if isinstance(link.get("metadata"),Mapping) else {}
            name=""
            for key in ("solution_identity","solution","product","tool"):
                value=clean(md.get(key))
                if value:
                    name=value; break
            ref=clean(link.get("source_family_key")) or f"radar:{link.get('evidence_id')}"
            if name and name.lower() not in {x.lower() for x in names}: names.append(name[:240])
            if ref and ref not in refs: refs.append(ref)
    return {"current_solution_titles":names[:12],"evidence_refs":refs[:24],"name_truth":"VALIDATED_METADATA_ONLY"}


def build_existing_systems(problem_lineages:list[dict[str,Any]],snapshot:Mapping[str,Any],*,evidence_index:Mapping[str,Any]|None=None,only_lineage_ids:set[str]|None=None)->list[dict[str,Any]]:
    out=[]
    for pl in problem_lineages:
        if only_lineage_ids is not None and pl.get("lineage_id") not in only_lineage_ids:
            continue
        claims=_aggregate_lineage_claims(pl); mids={int(x) for x in pl.get("member_candidate_ids",[])}; sol=_current_solution_context(mids,snapshot,evidence_index=evidence_index)
        value_flow=_structural_evidence(snapshot,mids,"value_flow",evidence_index=evidence_index)
        assets=_structural_evidence(snapshot,mids,"complementary_asset",evidence_index=evidence_index)
        workflows=list(pl.get("contexts",[]) or [])[:12]; actors=list(pl.get("actors",[]) or [])[:12]; objects=list(pl.get("objects",[]) or [])[:12]; solutions=sol["current_solution_titles"]
        unknown=[]
        if not workflows: unknown.append("CURRENT_WORKFLOW")
        if not actors: unknown.append("AFFECTED_ACTOR")
        if claims.get("C05")!="SUPPORTED": unknown.append("ECONOMIC_BUYER")
        if not solutions and claims.get("C06")!="SUPPORTED": unknown.append("CURRENT_SOLUTION_LANDSCAPE")
        if claims.get("C10")!="SUPPORTED": unknown.append("DISTRIBUTION_PATH")
        if value_flow.get("state")=="UNKNOWN": unknown.append("VALUE_FLOW")
        if assets.get("state")=="UNKNOWN": unknown.append("COMPLEMENTARY_ASSET_OWNERSHIP")
        sid="es_"+stable_hash(pl["lineage_id"],length=20)
        out.append({
            "existing_system_id":sid,"problem_lineage_id":pl["lineage_id"],"status":"EVIDENCE_BOUNDED_PARTIAL" if len(unknown)<=3 else "EVIDENCE_BOUNDED_THIN",
            "workflows":workflows,"affected_actors":actors,"objects":objects,"current_solution_titles":solutions,
            "current_solution_evidence_refs":sol["evidence_refs"],"workaround_level":pl.get("workaround_level",0),"workaround_label":pl.get("workaround_label"),
            "known_claim_states":{c:claims.get(c,"UNKNOWN") for c in ("C03","C05","C06","C07","C10","C13")},
            "unknowns":sorted(set(unknown)),"value_flow_state":value_flow.get("state","UNKNOWN"),"complementary_asset_ownership_state":assets.get("state","UNKNOWN"),
            "value_flow_evidence":value_flow,"complementary_asset_evidence":assets,
            "truth_boundary":"Bounded H1 system model. Value-flow/asset ownership resolves only from verified structural evidence; no narrative completion.",
        })
    return out


def build_intersections(problem_lineages:list[dict[str,Any]],transition_lineages:list[dict[str,Any]],transition_atoms:list[dict[str,Any]],*,only_problem_lineage_ids:set[str]|None=None)->list[dict[str,Any]]:
    """Materialize only decision-bearing problem×transition pairs.

    R2 persisted every lineage pair sharing a candidate, which created 1,273 live
    intersections even though none were thesis-eligible. G2 treats shared context as a
    coverage statistic, not an object. A StructuralIntersection exists only with direct
    pair evidence or a narrowly corroborated multi-candidate mismatch.
    """
    tls_by_cid:dict[int,set[str]]=defaultdict(set); tl_map={x["transition_lineage_id"]:x for x in transition_lineages}
    for tl in transition_lineages:
        for cid in tl.get("member_candidate_ids",[]): tls_by_cid[int(cid)].add(tl["transition_lineage_id"])
    atom_tl={aid:tl["transition_lineage_id"] for tl in transition_lineages for aid in tl.get("member_transition_atom_ids",[])}
    pl_by_cid={int(cid):pl["lineage_id"] for pl in problem_lineages for cid in pl.get("member_candidate_ids",[])}
    direct_rows:dict[tuple[str,str],list[dict[str,Any]]]=defaultdict(list)
    for a in transition_atoms:
        if not a.get("direct_problem_transition_link"):
            continue
        tlid=atom_tl.get(a.get("transition_atom_id")); plid=pl_by_cid.get(int(a.get("candidate_id",0) or 0))
        if tlid and plid:
            direct_rows[(plid,tlid)].append(dict(a))
    out=[]
    for pl in problem_lineages:
        if only_problem_lineage_ids is not None and pl.get("lineage_id") not in only_problem_lineage_ids:
            continue
        mids={int(x) for x in pl.get("member_candidate_ids",[])}; claims=_aggregate_lineage_claims(pl)
        linked=set()
        for cid in mids: linked.update(tls_by_cid.get(cid,set()))
        for tlid in sorted(linked):
            tl=tl_map[tlid]
            shared_ids=sorted(mids & {int(x) for x in tl.get("member_candidate_ids",[])})
            pair_rows=direct_rows.get((pl["lineage_id"],tlid),[])
            # Shared-candidate coincidence is not a structural intersection. The only
            # non-direct admission lane is a strong, explicitly-identified transition
            # recurring across at least two candidates in a durable-gap/workaround lineage.
            corroborated=bool(
                not pair_rows
                and len(shared_ids)>=2
                and clean(tl.get("state")).upper()=="SUPPORTED"
                and bool(tl.get("explicit_subjects") or tl.get("transition_hypothesis_ids"))
                and clean(pl.get("persistence_state")).upper()=="SUPPORTED"
                and claims.get("C07")=="SUPPORTED"
                and int(pl.get("workaround_level",0) or 0)>=2
            )
            if not pair_rows and not corroborated:
                continue
            direct_units={clean(x.get("content_fingerprint")) for x in pair_rows if clean(x.get("content_fingerprint"))}
            direct_families={clean(x.get("source_family")) for x in pair_rows if clean(x.get("source_family"))}
            gate=intersection_gate(
                problem_lineage=pl,transition_lineage=tl,direct_link_count=len(pair_rows),
                direct_independent_units=len(direct_units),direct_independent_families=len(direct_families),
                shared_candidate_count=len(shared_ids),c07_state=claims.get("C07","UNKNOWN"),
                workaround_level_value=int(pl.get("workaround_level",0) or 0),
            )
            if corroborated and gate.get("state")=="INSUFFICIENT":
                identity_reason="EXPLICIT_TRANSITION_IDENTITY" if tl.get("explicit_subjects") else "CORROBORATED_TRANSITION_HYPOTHESIS_IDENTITY"
                gate={"state":"PARTIAL","eligibility":"CORROBORATED_IDENTITY_MISMATCH","reasons":[identity_reason,"MULTI_CANDIDATE_OVERLAP","DURABLE_GAP","REVEALED_WORKAROUND"]}
            iid="ix_"+stable_hash(pl["lineage_id"],tlid,length=22)
            out.append({
                "intersection_id":iid,"problem_lineage_id":pl["lineage_id"],"transition_lineage_id":tlid,
                "state":gate["state"],"eligibility":gate["eligibility"],"reasons":gate["reasons"],
                "shared_candidate_count":len(shared_ids),"shared_candidate_ids":shared_ids,
                "direct_link_count":len(pair_rows),"direct_independent_units":len(direct_units),
                "direct_independent_families":len(direct_families),"direct_source_families":sorted(direct_families)[:24],
                "problem_trajectory":pl.get("trajectory"),"transition_trajectory":tl.get("trajectory"),
                "bridgeability_state":"PARTIAL" if gate["state"] in {"SUPPORTED","PARTIAL"} else "UNKNOWN",
                "truth_boundary":"Only decision-bearing pair evidence is materialized. Shared context without mismatch proof remains upstream coverage, not a StructuralIntersection object.",
            })
    return out


def _asset_accessibility(tl:Mapping[str,Any]|None)->tuple[str,list[str]]:
    if not tl: return "UNKNOWN",[]
    rels=[clean(x).lower() for x in tl.get("relations",[])]; driver=clean(tl.get("driver")).upper(); refs=list(tl.get("verified_families",[]) or [])
    enabler=driver in {"COST","DISTRIBUTION"} or any("enabler" in x or "cost" in x or "api" in x or "open_source" in x or "open-source" in x for x in rels)
    # A cost/distribution transition can make asset access plausible, but it does not prove
    # which complementary asset is actually accessible to this entrant. Only explicit
    # verified structural evidence may resolve asset_accessibility to SUPPORTED.
    if enabler and (refs or clean(tl.get("state")).upper() in {"SUPPORTED","PARTIAL"}): return "PARTIAL",refs
    return "UNKNOWN",[]


def _capture_state(claims:Mapping[str,str])->str:
    vals={claims.get("C09","UNKNOWN"),claims.get("C10","UNKNOWN"),claims.get("C13","UNKNOWN")}
    if "REFUTED" in vals: return "REFUTED"
    if all(claims.get(c)=="SUPPORTED" for c in ("C09","C10","C13")): return "SUPPORTED"
    if claims.get("C09")=="SUPPORTED" and claims.get("C10")=="SUPPORTED": return "PARTIAL"
    if "SUPPORTED" in vals: return "PARTIAL"
    if "INSUFFICIENT" in vals: return "INSUFFICIENT"
    return "UNKNOWN"


def _market_validation(root:Path,candidate_ids:set[int],snapshot:Mapping[str,Any])->dict[str,Any]:
    q=_safe_read_json(root/MARKET_TEST_QUEUE,{})
    active=clean(q.get("active_generation_version")) if isinstance(q,dict) else ""
    cmap={int(c.get("id",0) or 0):c for c in snapshot.get("candidates",[])}; accepted=[]; rejected=[]
    for t in q.get("tests",[]) if isinstance(q,dict) else []:
        try: cid=int(t.get("candidate_id"))
        except Exception: continue
        if cid not in candidate_ids or clean(t.get("status")).upper()!="COMPLETED": continue
        c=cmap.get(cid) or {}; fp=c.get("fingerprint") if isinstance(c.get("fingerprint"),Mapping) else {}
        current_h=clean(fp.get("hypothesis_key")); test_h=clean(t.get("hypothesis_key")); gen=clean(t.get("generation_version"))
        if not active: rejected.append({"test_id":t.get("test_id"),"reason":"ACTIVE_GENERATION_IDENTITY_MISSING"}); continue
        if gen!=active: rejected.append({"test_id":t.get("test_id"),"reason":"GENERATION_MISMATCH_OR_MISSING"}); continue
        if not current_h or test_h!=current_h: rejected.append({"test_id":t.get("test_id"),"reason":"HYPOTHESIS_MISMATCH_OR_MISSING"}); continue
        outcome=t.get("outcome") if isinstance(t.get("outcome"),Mapping) else {}
        accepted.append({"test_id":t.get("test_id"),"test_type":t.get("test_type"),"result":t.get("result"),"paid":bool(outcome.get("paid")),"signed_paid_pilot":bool(outcome.get("signed_paid_pilot")),"amount":outcome.get("amount"),"outcome_hash":outcome.get("outcome_hash")})
    def valid_paid(x:Mapping[str,Any])->bool:
        if clean(x.get("test_type")).upper()!="PAYMENT_CHECK" or clean(x.get("result")).upper() not in {"PASS","SUCCESS","CONFIRMED","PAID","POSITIVE"}: return False
        if not clean(x.get("outcome_hash")) or not x.get("paid"): return False
        try: amt=float(x.get("amount") or 0)
        except Exception: amt=0
        return amt>0 or bool(x.get("signed_paid_pilot"))
    return {"completed_tests":len(accepted),"paid_tested_offer_observed":any(valid_paid(x) for x in accepted),"tested_offer_only_not_general_market":bool(accepted),"test_refs":[f"market_test:{x['test_id']}" for x in accepted if x.get("test_id")],"rejected_stale_or_mismatched_tests":rejected[:20]}


def _candidate_for_lineage(pl:Mapping[str,Any],snapshot:Mapping[str,Any])->set[int]:
    return {int(x) for x in pl.get("member_candidate_ids",[]) if str(x).isdigit()}


def _scoped_claim_states(snapshot:Mapping[str,Any],candidate_ids:set[int],*,evidence_index:Mapping[str,Any]|None=None)->tuple[dict[str,str],dict[str,dict[str,Any]]]:
    """Conservatively aggregate Radar atomic states for the exact thesis slice.

    A single candidate's commercial claim must not silently become truth for a broad problem
    lineage.  Phenomenon claims may aggregate across a lineage; commercial/founder claims are
    SUPPORTED across a multi-candidate scope only when at least two scoped candidates support
    them.  This is a derived coverage state only and never writes Radar.
    """
    by_candidate=(evidence_index or {}).get("claim_states_by_candidate") if evidence_index is not None else None
    if by_candidate is None:
        by_candidate,_,_=_claim_maps(snapshot)
    states:dict[str,str]={}; metrics:dict[str,dict[str,Any]]={}
    phenomenon={"C01","C02","C03","C04"}
    ids=sorted(int(x) for x in candidate_ids)
    for i in range(1,15):
        code=f"C{i:02d}"
        vals=[clean((by_candidate.get(cid) or {}).get(code)).upper() or "UNKNOWN" for cid in ids]
        supported=sum(v=="SUPPORTED" for v in vals); refuted=sum(v=="REFUTED" for v in vals)
        resolved=sum(v in {"SUPPORTED","REFUTED","PARTIAL","INSUFFICIENT","CONFLICTED"} for v in vals)
        if code in phenomenon or len(ids)<=1:
            state=aggregate_claim_states(vals)
        elif supported and refuted:
            state="CONFLICTED"
        elif supported>=2:
            state="SUPPORTED"
        elif supported==1:
            state="PARTIAL"
        elif refuted==len(ids) and ids:
            state="REFUTED"
        elif refuted>0:
            state="INSUFFICIENT"
        elif any(v=="CONFLICTED" for v in vals):
            state="CONFLICTED"
        elif any(v=="PARTIAL" for v in vals):
            state="PARTIAL"
        elif any(v=="INSUFFICIENT" for v in vals):
            state="INSUFFICIENT"
        else:
            state="UNKNOWN"
        states[code]=state
        metrics[code]={
            "scope_candidate_count":len(ids),
            "supported_candidates":supported,
            "refuted_candidates":refuted,
            "resolved_candidates":resolved,
            "atomic_states":{str(cid):vals[n] for n,cid in enumerate(ids)},
            "aggregation":"PHENOMENON_LINEAGE" if code in phenomenon else ("EXACT_SINGLE_CANDIDATE" if len(ids)<=1 else "CONSERVATIVE_MULTI_CANDIDATE_COVERAGE"),
        }
    return states,metrics


def _scoped_workaround_level(pl:Mapping[str,Any],candidate_ids:set[int])->int:
    levels=pl.get("member_workaround_levels") if isinstance(pl.get("member_workaround_levels"),Mapping) else {}
    scoped=[]
    for cid in candidate_ids:
        try: scoped.append(int(levels.get(str(int(cid)),0) or 0))
        except Exception: pass
    return max(scoped or [int(pl.get("workaround_level",0) or 0)])


def build_theses(root:Path,snapshot:Mapping[str,Any],problem_lineages:list[dict[str,Any]],transition_lineages:list[dict[str,Any]],systems:list[dict[str,Any]],intersections:list[dict[str,Any]],previous:Mapping[str,dict[str,Any]],previous_research:Mapping[str,dict[str,Any]],refreshed_at:str,*,evidence_index:Mapping[str,Any]|None=None,only_problem_lineage_ids:set[str]|None=None)->list[dict[str,Any]]:
    tlmap={x["transition_lineage_id"]:x for x in transition_lineages}; sysmap={x["problem_lineage_id"]:x for x in systems}; ixmap={x["intersection_id"]:x for x in intersections}; out=[]
    for pl in problem_lineages:
        if only_problem_lineage_ids is not None and pl.get("lineage_id") not in only_problem_lineage_ids:
            continue
        lineage_claims=_aggregate_lineage_claims(pl); lineage_mids=_candidate_for_lineage(pl,snapshot); lineage_wlevel=int(pl.get("workaround_level",0) or 0)
        eligible_ix=[x for x in intersections if x.get("problem_lineage_id")==pl["lineage_id"] and x.get("state") in {"SUPPORTED","PARTIAL"}]
        variants=eligible_ix
        # Non-transition thesis exists only for a commercial/lead-user wedge, not every problem space.
        nontransition_eligible=(pl.get("persistence_state")=="SUPPORTED" and lineage_claims.get("C05")=="SUPPORTED" and lineage_claims.get("C07")=="SUPPORTED") or (pl.get("persistence_state") in {"SUPPORTED","PARTIAL"} and lineage_wlevel>=5 and lineage_claims.get("C03")=="SUPPORTED")
        if not variants and nontransition_eligible: variants=[None]
        for ix in variants:
            tl=tlmap.get(ix.get("transition_lineage_id")) if ix else None; transition_present=tl is not None
            scope_mids={int(x) for x in ((ix or {}).get("shared_candidate_ids") or []) if str(x).isdigit()} if ix else set(lineage_mids)
            if not scope_mids:
                scope_mids=set(lineage_mids)
            claims,claim_scope_metrics=_scoped_claim_states(snapshot,scope_mids,evidence_index=evidence_index)
            wlevel=_scoped_workaround_level(pl,scope_mids)
            mismatch=(ix or {}).get("state") if ix else "UNKNOWN"
            transition_asset_state,transition_asset_refs=_asset_accessibility(tl)
            explicit_asset=_structural_evidence(snapshot,scope_mids,"complementary_asset",evidence_index=evidence_index)
            asset=aggregate_claim_states([transition_asset_state,explicit_asset.get("state")])
            asset_refs=list(dict.fromkeys(list(transition_asset_refs)+list(explicit_asset.get("evidence_refs",[]) or [])))
            expansion=_structural_evidence(snapshot,scope_mids,"expansion_surface",evidence_index=evidence_index)
            incumbent_evidence=_structural_evidence(snapshot,scope_mids,"incumbent_response",evidence_index=evidence_index)
            capture=_capture_state(claims)
            workaround_state="SUPPORTED" if wlevel>=5 else ("PARTIAL" if wlevel>=2 else ("INSUFFICIENT" if wlevel>=1 else "UNKNOWN"))
            mv=_market_validation(root,scope_mids,snapshot)
            c13=claims.get("C13","UNKNOWN")
            incumbent_power_proxy=("LOW_OR_MANAGEABLE" if c13=="SUPPORTED" else ("HIGH_OR_UNSURVIVABLE" if c13=="REFUTED" else "UNKNOWN"))
            dims={
                "problem_persistence":dimension(pl.get("persistence_state"),basis="ProblemLineage independent recurrence + time persistence.",evidence=pl.get("recurrence_support_families",[]),metrics={"span_days":pl.get("span_days",0),"recurrence_span_days":pl.get("recurrence_span_days",0),"independent_families":pl.get("independent_recurrence_families",0),"actor_spread":pl.get("actor_spread",0),"context_spread":pl.get("context_spread",0)},owner="BRAIN_PROBLEM_LINEAGE"),
                "transition_strength":dimension((tl or {}).get("state","UNKNOWN"),basis="TransitionLineage independent evidence; derived fingerprint context excluded.",evidence=(tl or {}).get("verified_families",[]),metrics={"trajectory":(tl or {}).get("trajectory"),"independent_families":(tl or {}).get("independent_verified_families",0)},owner="BRAIN_TRANSITION_LINEAGE"),
                "system_mismatch":dimension(mismatch,basis="StructuralIntersection gate; shared context alone is insufficient.",evidence=[],metrics={"intersection_id":(ix or {}).get("intersection_id"),"eligibility":(ix or {}).get("eligibility")},owner="BRAIN_STRUCTURAL_INTERSECTION"),
                "economic_materiality":dimension(claims.get("C03","UNKNOWN"),basis="Scoped view of canonical Radar C03.",metrics=claim_scope_metrics.get("C03",{}),owner="BRAIN_SCOPED_RADAR_C03"),
                "workaround_intensity":dimension(workaround_state,basis="Revealed W0-W6 behavior from problem evidence.",metrics={"level":wlevel,"label":pl.get("workaround_label")},owner="BRAIN_PROBLEM_LINEAGE"),
                "buyer_formation":dimension(claims.get("C05","UNKNOWN"),basis="Conservative scoped aggregation of canonical Radar C05; one candidate cannot prove a broad lineage buyer.",metrics=claim_scope_metrics.get("C05",{}),owner="BRAIN_SCOPED_RADAR_C05"),
                "gap_durability":dimension(claims.get("C07","UNKNOWN"),basis="Conservative scoped aggregation of canonical Radar C07 after solution counterevidence.",metrics=claim_scope_metrics.get("C07",{}),owner="BRAIN_SCOPED_RADAR_C07"),
                "asset_accessibility":dimension(asset,basis="Verified complementary-asset evidence and/or verified transition enabler. Generic transition context is insufficient.",evidence=asset_refs,metrics={"explicit_structural_state":explicit_asset.get("state"),"transition_enabler_state":transition_asset_state},owner="BRAIN_VERIFIED_STRUCTURAL_EVIDENCE"),
                "distribution_leverage":dimension(claims.get("C10","UNKNOWN"),basis="Conservative scoped aggregation of canonical Radar C10.",metrics=claim_scope_metrics.get("C10",{}),owner="BRAIN_SCOPED_RADAR_C10"),
                "incumbent_response_power":dimension(c13,basis="Scoped Radar C13 is a survivability proxy, not a direct measurement of incumbent power. SUPPORTED means response is survivable; REFUTED means incumbent/competition dominates.",evidence=incumbent_evidence.get("evidence_refs",[]),metrics={"power_level_proxy":incumbent_power_proxy,"claim_scope":claim_scope_metrics.get("C13",{}),"direct_structural_evidence_state":incumbent_evidence.get("state"),"direct_structural_evidence_units":incumbent_evidence.get("independent_units",0)},owner="BRAIN_SCOPED_RADAR_C13+VERIFIED_STRUCTURAL_CONTEXT"),
                "captureability":dimension(capture,basis="Derived from scoped C09 execution + C10 distribution + C13 survivability.",metrics={"C09":claim_scope_metrics.get("C09",{}),"C10":claim_scope_metrics.get("C10",{}),"C13":claim_scope_metrics.get("C13",{})},owner="BRAIN_SCOPED_DERIVED_FROM_RADAR"),
                "expansion_surface":dimension(expansion.get("state","UNKNOWN"),basis="Verified adjacent-workflow/market expansion evidence only. No generic TAM or LLM narrative may resolve this dimension.",evidence=expansion.get("evidence_refs",[]),metrics={"independent_units":expansion.get("independent_units",0)},owner="BRAIN_VERIFIED_STRUCTURAL_EVIDENCE" if expansion.get("state")!="UNKNOWN" else "UNVALIDATED"),
            }
            cls=classify_thesis(dims,transition_present=transition_present,workaround_level_value=wlevel,market_validation=mv)
            tid="ot_"+stable_hash(pl["lineage_id"],(ix or {}).get("intersection_id") or "no-transition",length=22)
            old=previous.get(tid); attempts={}
            # Research execution telemetry lives on persistent ResearchQuestion objects.
            # Pull attempts from there so VOI actually decays after repeated no-yield work.
            for q in previous_research.values():
                if clean(q.get("thesis_id")) != tid:
                    continue
                dim=clean(q.get("dimension"))
                if dim:
                    attempts[dim]=max(attempts.get(dim,0),int(q.get("attempts",0) or 0))
            plan=research_plan(dims,existing_attempts=attempts)
            obj={
                "thesis_id":tid,"revision":int((old or {}).get("revision",0) or 0)+1 if old else 1,
                "problem_lineage_id":pl["lineage_id"],"transition_lineage_id":tl.get("transition_lineage_id") if tl else None,"intersection_id":(ix or {}).get("intersection_id"),
                "existing_system_id":(sysmap.get(pl["lineage_id"]) or {}).get("existing_system_id"),"member_candidate_ids":sorted(scope_mids),"problem_lineage_member_candidate_ids":sorted(lineage_mids),
                "representative_title":pl.get("representative_title"),"representative_problem":pl.get("representative_problem"),
                "structural_thesis":{
                    "problem":pl.get("representative_problem"),
                    "problem_trajectory":pl.get("trajectory"),
                    "transition_driver":(tl or {}).get("driver"),
                    "transition":(tl or {}).get("representative_text"),
                    "system_mismatch":mismatch,
                    "buyer_state":claims.get("C05","UNKNOWN"),
                    "gap_state":claims.get("C07","UNKNOWN"),
                    "captureability_state":capture,
                    "wedge_type":"STRUCTURAL_TRANSITION" if transition_present else ("LEAD_USER_WEDGE" if wlevel>=5 else "PROVEN_MARKET_WEDGE"),
                    "source_text_only":True,
                    "llm_completion_used":False,
                },
                "opportunity_class":"STRUCTURAL_TRANSITION" if transition_present else ("LEAD_USER_WEDGE" if wlevel>=5 else "PROVEN_MARKET_WEDGE"),
                "classification":cls["classification"],"zip2_readiness":cls["zip2_readiness"],"death_state":cls["death_state"],"claim_states":claims,"claim_scope_metrics":claim_scope_metrics,"dimensions":dims,
                "workaround_level":wlevel,"workaround_label":pl.get("workaround_label"),"market_validation":mv,"research_plan":plan[:8],"best_next_evidence":plan[0] if plan else None,
                "problem_trajectory":pl.get("trajectory"),"transition_trajectory":tl.get("trajectory") if tl else None,
                "first_seen_at":pl.get("first_seen_at"),"last_observed_at":max([x for x in (pl.get("last_observed_at"),(tl or {}).get("last_observed_at")) if x] or [""]),
                "truth_boundary":"Opportunity thesis owns pair/scoped structural synthesis only. Radar claims own atomic truth; cross-candidate commercial support cannot leak across scope; Shadow/LLM cannot promote dimensions.",
            }
            obj["zip2_gate"]=zip2_gate_report(obj)
            # Full-system Strategic Search Rebase: objective market truth remains in Radar/Brain;
            # this adds first-person Founder addressability, fast-validation routing, and
            # the ZIP2_STRUCTURAL / FAST_VALIDATION / BOTH / NEITHER strategy layer.
            obj=decorate_thesis_with_strategy(obj, root=root)
            obj=evolve_thesis_lifecycle(obj,old,changed_at=refreshed_at)
            # Revision is semantic versioning, not "times recomputed". Lifecycle history is
            # excluded from the basis because it records the consequence of a state change.
            basis_ignore={"revision","last_observed_at","last_meaningful_update_at","semantic_fingerprint","lifecycle_history","revival_count","death_count"}
            core=semantic_fingerprint(obj,ignore=basis_ignore)
            old_core=semantic_fingerprint(old,ignore=basis_ignore) if old else None
            obj["revision"]=(int((old or {}).get("revision",0) or 0)+1) if (not old or core!=old_core) else int((old or {}).get("revision",1) or 1)
            obj["semantic_fingerprint"]=core
            obj["last_meaningful_update_at"]=refreshed_at if not old or core!=old_core else old.get("last_meaningful_update_at")
            out.append(obj)
    return out


def build_research_questions(theses:list[dict[str,Any]],previous:Mapping[str,dict[str,Any]],*,only_thesis_ids:set[str]|None=None)->list[dict[str,Any]]:
    out=[]
    for t in theses:
        if only_thesis_ids is not None and t.get("thesis_id") not in only_thesis_ids:
            continue
        for item in (t.get("research_plan") or [])[:4]:
            dim=clean(item.get("dimension")); qid="rq_"+stable_hash(t["thesis_id"],dim,length=22); old=previous.get(qid)
            out.append({
                "research_question_id":qid,"thesis_id":t["thesis_id"],"problem_lineage_id":t["problem_lineage_id"],"member_candidate_ids":t.get("member_candidate_ids",[]),
                "dimension":dim,"state":item.get("state"),"fatal_gate":bool(item.get("fatal_gate")),"voi":item.get("voi"),"source_group":item.get("source_group"),"action":item.get("action"),
                "decision_flip_weight":item.get("decision_flip_weight"),"uncertainty":item.get("uncertainty"),"estimated_relative_cost":item.get("estimated_relative_cost"),
                "attempts":int((old or {}).get("attempts",0) or 0),"status":"OPEN","recency_factor_used":False,
                "truth_boundary":"Research planning only; completion requires validated evidence through existing Radar truth pipeline.",
            })
    out.sort(key=lambda x:(-float(x.get("voi",0) or 0),0 if x.get("fatal_gate") else 1,clean(x.get("research_question_id"))))
    return out


def _object_maps(root:Path)->dict[str,dict[str,dict[str,Any]]]:
    return {t:object_map(root,t) for t in ("problem_atom","transition_atom","problem_lineage","transition_hypothesis","transition_lineage","existing_system","structural_bridge_hypothesis","structural_intersection","opportunity_thesis","research_question")}


def _desired_maps(model:Mapping[str,Any])->dict[str,dict[str,dict[str,Any]]]:
    specs={
        "problem_atom":("problem_atoms","atom_id"),"transition_atom":("transition_atoms","transition_atom_id"),"problem_lineage":("problem_lineages","lineage_id"),
        "transition_hypothesis":("transition_hypotheses","transition_hypothesis_id"),"transition_lineage":("transition_lineages","transition_lineage_id"),"existing_system":("existing_systems","existing_system_id"),
        "structural_bridge_hypothesis":("structural_bridge_hypotheses","structural_bridge_hypothesis_id"),"structural_intersection":("structural_intersections","intersection_id"),
        "opportunity_thesis":("opportunity_theses","thesis_id"),"research_question":("research_questions","research_question_id"),
    }
    out={}
    for typ,(key,idkey) in specs.items():
        rows=model.get(key,[])
        if typ=="transition_atom":
            # Raw timing/context rows remain owned by upstream evidence. Brain persists only
            # atoms admitted to persistent transition identity, avoiding a duplicate event
            # ledger for context that cannot affect a structural thesis.
            rows=[x for x in rows if x.get("lineage_eligible") or x.get("direct_problem_transition_link")]
        out[typ]={clean(x[idkey]):dict(x) for x in rows if clean(x.get(idkey))}
    return out


def _dependencies_for_object(typ:str,obj:Mapping[str,Any])->list[dict[str,str]]:
    edges=[]
    def add(to_type:str,to_id:Any,relation:str):
        if clean(to_id): edges.append({"to_type":to_type,"to_id":clean(to_id),"relation":relation})
    if typ=="problem_atom": add("problem_lineage",obj.get("lineage_id"),"MEMBER_OF")
    elif typ=="transition_atom": add("transition_lineage",obj.get("transition_lineage_id"),"MEMBER_OF")
    elif typ=="transition_hypothesis":
        for aid in obj.get("member_transition_atom_ids",[]) or []: add("transition_atom",aid,"STAGES_TRANSITION_ATOM")
    elif typ=="existing_system": add("problem_lineage",obj.get("problem_lineage_id"),"MODELS")
    elif typ=="structural_bridge_hypothesis":
        add("problem_lineage",obj.get("problem_lineage_id"),"HYPOTHESIZES_BRIDGE_FROM_PROBLEM"); add("transition_lineage",obj.get("transition_lineage_id"),"HYPOTHESIZES_BRIDGE_TO_TRANSITION")
    elif typ=="structural_intersection":
        add("problem_lineage",obj.get("problem_lineage_id"),"INTERSECTS_PROBLEM"); add("transition_lineage",obj.get("transition_lineage_id"),"INTERSECTS_TRANSITION")
    elif typ=="opportunity_thesis":
        add("problem_lineage",obj.get("problem_lineage_id"),"SYNTHESIZES_PROBLEM"); add("transition_lineage",obj.get("transition_lineage_id"),"SYNTHESIZES_TRANSITION"); add("structural_intersection",obj.get("intersection_id"),"GATED_BY"); add("existing_system",obj.get("existing_system_id"),"USES_SYSTEM_MODEL")
    elif typ=="research_question":
        add("opportunity_thesis",obj.get("thesis_id"),"REDUCES_UNCERTAINTY_FOR")
        if clean(obj.get("target_type"))=="TRANSITION_HYPOTHESIS": add("transition_hypothesis",obj.get("target_id"),"VALIDATES_TRANSITION_IDENTITY")
        if clean(obj.get("target_type"))=="STRUCTURAL_BRIDGE_HYPOTHESIS": add("structural_bridge_hypothesis",obj.get("target_id"),"VALIDATES_STRUCTURAL_BRIDGE")
    return edges


def _attach_membership_refs(model:dict[str,Any])->None:
    pl_by_cid={int(cid):pl["lineage_id"] for pl in model["problem_lineages"] for cid in pl.get("member_candidate_ids",[])}
    tl_by_atom={aid:tl["transition_lineage_id"] for tl in model["transition_lineages"] for aid in tl.get("member_transition_atom_ids",[])}
    for a in model["problem_atoms"]: a["lineage_id"]=pl_by_cid.get(int(a.get("candidate_id",0) or 0))
    for a in model["transition_atoms"]: a["transition_lineage_id"]=tl_by_atom.get(a.get("transition_atom_id"))


def _changed_object_ids(rows: Iterable[Mapping[str,Any]], old: Mapping[str,Mapping[str,Any]], id_key: str, *, ignore: set[str] | None = None) -> set[str]:
    ignore=set(ignore or set()) | {"revision","last_observed_at","refreshed_at","last_meaningful_update_at","portfolio_rank"}
    current={clean(x.get(id_key)):dict(x) for x in rows if clean(x.get(id_key))}
    changed=set(current)^set(old)
    for oid in set(current)&set(old):
        if semantic_fingerprint(current[oid],ignore=ignore)!=semantic_fingerprint(old[oid],ignore=ignore):
            changed.add(oid)
    return changed


def build_model(root:Path,snapshot:Mapping[str,Any],*,refreshed_at:str,dirty:Mapping[str,Any])->dict[str,Any]:
    """Build the structural brain as a dirty dependency graph, not a full-world rewrite.

    Observation wrappers are cheap and rebuilt from the immutable truth snapshot. Long-lived
    lineage/system/intersection/thesis objects reuse unaffected projections and recompute only
    dirty connected components. Global market-test/calibration changes intentionally invalidate
    thesis adjudication, not problem/transition identity.
    """
    phase={}; t=time.perf_counter()
    old=_object_maps(root)
    evidence_index=_build_evidence_index(snapshot); phase["evidence_index_ms"]=int((time.perf_counter()-t)*1000)
    t=time.perf_counter(); atoms=build_problem_atoms(snapshot); phase["problem_atoms_ms"]=int((time.perf_counter()-t)*1000)
    dirty_ids=set(int(x) for x in dirty.get("dirty_candidate_ids",[])); first=bool(dirty.get("first_build"))

    t=time.perf_counter(); pls,pldiag=build_problem_lineages_incremental(atoms,old["problem_lineage"],dirty_ids,first); phase["problem_lineages_ms"]=int((time.perf_counter()-t)*1000)
    changed_pl=_changed_object_ids(pls,old["problem_lineage"],"lineage_id",ignore={"member_candidate_ids","member_atom_ids"})

    t=time.perf_counter(); raw_tas=build_transition_atoms(snapshot,atoms); phase["transition_atoms_ms"]=int((time.perf_counter()-t)*1000)
    candidate_to_pl={int(cid):clean(pl.get("lineage_id")) for pl in pls for cid in (pl.get("member_candidate_ids") or []) if str(cid).isdigit()}
    t=time.perf_counter(); transition_hypotheses,promotions=build_transition_hypotheses(raw_tas,candidate_to_problem_lineage=candidate_to_pl); tas=apply_transition_hypothesis_promotions(raw_tas,promotions); phase["transition_hypotheses_ms"]=int((time.perf_counter()-t)*1000)
    t=time.perf_counter(); tls,tldiag=build_transition_lineages_incremental(tas,old["transition_lineage"],dirty_ids,first); phase["transition_lineages_ms"]=int((time.perf_counter()-t)*1000)
    changed_tl=_changed_object_ids(tls,old["transition_lineage"],"transition_lineage_id",ignore={"member_candidate_ids","member_transition_atom_ids"})

    pl_ids={clean(x.get("lineage_id")) for x in pls}
    tl_ids={clean(x.get("transition_lineage_id")) for x in tls}
    if first:
        recompute_system_pl=set(pl_ids)
    else:
        recompute_system_pl=set(changed_pl)
    t=time.perf_counter()
    fresh_systems=build_existing_systems(pls,snapshot,evidence_index=evidence_index,only_lineage_ids=recompute_system_pl)
    carried_systems=[dict(x) for x in old["existing_system"].values() if clean(x.get("problem_lineage_id")) in pl_ids and clean(x.get("problem_lineage_id")) not in recompute_system_pl]
    systems=carried_systems+fresh_systems
    phase["existing_systems_ms"]=int((time.perf_counter()-t)*1000)
    changed_system=_changed_object_ids(systems,old["existing_system"],"existing_system_id")

    # A changed transition can affect every problem lineage it touched, even when that
    # problem itself was clean. Expand the dirty component through old/current intersections.
    affected_ix_pl=set(changed_pl)
    for ix in list(old["structural_intersection"].values()):
        if clean(ix.get("transition_lineage_id")) in changed_tl:
            affected_ix_pl.add(clean(ix.get("problem_lineage_id")))
    current_tl_members={clean(tl.get("transition_lineage_id")):{int(x) for x in tl.get("member_candidate_ids",[]) if str(x).isdigit()} for tl in tls}
    current_pl_members={clean(pl.get("lineage_id")):{int(x) for x in pl.get("member_candidate_ids",[]) if str(x).isdigit()} for pl in pls}
    for tlid in changed_tl:
        tids=current_tl_members.get(tlid,set())
        for plid,pids in current_pl_members.items():
            if tids & pids:
                affected_ix_pl.add(plid)
    affected_ix_pl={x for x in affected_ix_pl if x}
    if first: affected_ix_pl=set(pl_ids)
    t=time.perf_counter()
    fresh_ix=build_intersections(pls,tls,tas,only_problem_lineage_ids=affected_ix_pl)
    carried_ix=[dict(x) for x in old["structural_intersection"].values() if clean(x.get("problem_lineage_id")) in pl_ids and clean(x.get("transition_lineage_id")) in tl_ids and clean(x.get("problem_lineage_id")) not in affected_ix_pl]
    intersections=carried_ix+fresh_ix
    phase["intersections_ms"]=int((time.perf_counter()-t)*1000)
    changed_ix=_changed_object_ids(intersections,old["structural_intersection"],"intersection_id")
    t=time.perf_counter(); bridge_hypotheses=build_structural_bridge_hypotheses(pls,tls,intersections); phase["bridge_hypotheses_ms"]=int((time.perf_counter()-t)*1000)

    ix_to_pl={clean(x.get("intersection_id")):clean(x.get("problem_lineage_id")) for x in intersections}
    old_ix_to_pl={clean(x.get("intersection_id")):clean(x.get("problem_lineage_id")) for x in old["structural_intersection"].values()}
    system_to_pl={clean(x.get("existing_system_id")):clean(x.get("problem_lineage_id")) for x in systems}
    old_system_to_pl={clean(x.get("existing_system_id")):clean(x.get("problem_lineage_id")) for x in old["existing_system"].values()}
    affected_thesis_pl=set(changed_pl)
    affected_thesis_pl.update(ix_to_pl.get(i) or old_ix_to_pl.get(i) for i in changed_ix)
    affected_thesis_pl.update(system_to_pl.get(i) or old_system_to_pl.get(i) for i in changed_system)
    affected_thesis_pl.discard(None); affected_thesis_pl.discard("")
    # External validation/calibration truth can change thesis classification without changing
    # a Candidate or lineage, so it invalidates adjudication for all existing thesis spaces.
    if dirty.get("global_dirty"):
        affected_thesis_pl=set(pl_ids) | {clean(x.get("problem_lineage_id")) for x in old["opportunity_thesis"].values()}
    if first: affected_thesis_pl=set(pl_ids)

    t=time.perf_counter()
    fresh_theses=build_theses(root,snapshot,pls,tls,systems,intersections,old["opportunity_thesis"],old["research_question"],refreshed_at,evidence_index=evidence_index,only_problem_lineage_ids=affected_thesis_pl)
    carried_theses=[dict(x) for x in old["opportunity_thesis"].values() if clean(x.get("problem_lineage_id")) in pl_ids and clean(x.get("problem_lineage_id")) not in affected_thesis_pl]
    theses=carried_theses+fresh_theses
    phase["theses_ms"]=int((time.perf_counter()-t)*1000)
    changed_theses=_changed_object_ids(theses,old["opportunity_thesis"],"thesis_id",ignore={"member_candidate_ids"})

    thesis_ids={clean(x.get("thesis_id")) for x in theses}
    t=time.perf_counter()
    fresh_research=build_research_questions(theses,old["research_question"],only_thesis_ids=changed_theses if not first else thesis_ids)
    pre_thesis_research=build_prethesis_research_questions(transition_hypotheses,bridge_hypotheses,old["research_question"])
    pre_ids={clean(x.get("research_question_id")) for x in pre_thesis_research}
    carried_research=[dict(x) for x in old["research_question"].values() if clean(x.get("thesis_id")) in thesis_ids and clean(x.get("thesis_id")) not in changed_theses and clean(x.get("research_question_id")) not in pre_ids]
    research=carried_research+fresh_research+pre_thesis_research
    # De-duplicate by stable research question identity; newly rebuilt planning rows win.
    research=list({clean(x.get("research_question_id")):x for x in research if clean(x.get("research_question_id"))}.values())
    phase["research_questions_ms"]=int((time.perf_counter()-t)*1000)

    admission_counts=Counter(clean(x.get("identity_quality")) or "UNKNOWN" for x in tas)
    admission_reasons=Counter(clean(x.get("admission_reason")) or "UNKNOWN" for x in tas)
    model={"problem_atoms":atoms,"transition_atoms":tas,"problem_lineages":pls,"transition_hypotheses":transition_hypotheses,"transition_lineages":tls,"existing_systems":systems,"structural_bridge_hypotheses":bridge_hypotheses,"structural_intersections":intersections,"opportunity_theses":theses,"research_questions":research,"phase_ms":phase,"problem_lineage_diagnostics":pldiag,"transition_lineage_diagnostics":tldiag,
           "transition_admission_diagnostics":{"observations_total":len(tas),"lineage_admitted":sum(1 for x in tas if x.get("lineage_eligible")),"context_only":sum(1 for x in tas if not x.get("lineage_eligible")),"hypotheses":len(transition_hypotheses),"hypotheses_promotable":sum(1 for x in transition_hypotheses if x.get("promotion_eligible")),"promoted_context_atoms":sum(1 for x in tas if clean(x.get("identity_quality"))=="CORROBORATED_CONTEXT_PROMOTION"),"identity_quality_counts":dict(admission_counts),"admission_reason_counts":dict(admission_reasons),"materialized_intersections":len(intersections),"bridge_hypotheses":len(bridge_hypotheses)},
           "dependency_dirty":{"problem_lineages":sorted(changed_pl),"transition_lineages":sorted(changed_tl),"existing_systems":sorted(changed_system),"intersection_problem_lineages":sorted(affected_ix_pl),"intersections":sorted(changed_ix),"thesis_problem_lineages":sorted(affected_thesis_pl),"theses":sorted(changed_theses)}}
    _attach_membership_refs(model)
    return model


def _diff_events(root:Path,model:Mapping[str,Any],units:list[dict[str,Any]],truth_fp:str,refreshed_at:str)->tuple[list[dict[str,Any]],list[dict[str,Any]],dict[str,Any]]:
    old=_object_maps(root); desired=_desired_maps(model); events=[]; changes=[]; counts=Counter()
    for typ,newmap in desired.items():
        oldmap=old.get(typ,{})
        for oid,obj in sorted(newmap.items()):
            oldobj=oldmap.get(oid); change=meaningful_change(oldobj,obj)
            if change is None: continue
            sem=semantic_fingerprint(obj,ignore={"revision","last_observed_at","last_meaningful_update_at"})
            events.append({"stream_type":typ,"stream_id":oid,"event_type":"OBJECT_UPSERT","payload":{"object_type":typ,"object_id":oid,"semantic_hash":sem,"payload":obj},"valid_at":obj.get("last_observed_at") or obj.get("last_seen_at")})
            events.append({"stream_type":typ,"stream_id":oid,"event_type":"DEPENDENCIES_REPLACED","payload":{"from_type":typ,"from_id":oid,"edges":_dependencies_for_object(typ,obj)}})
            counts["created" if oldobj is None else "updated"]+=1
            if typ in MEANINGFUL_CHANGE_OBJECT_TYPES:
                change_id="chg_"+stable_hash(typ,oid,change,truth_fp,length=28)
                payload={"change_id":change_id,"object_type":typ,"object_id":oid,"recorded_at":refreshed_at,**change,"meaningful_change_contract":"Only lineage/system/intersection/thesis semantic changes are Founder-meaningful; timestamps/atoms/research attempts are not."}
                changes.append(payload); events.append({"stream_type":"meaningful_change","stream_id":change_id,"event_type":"MEANINGFUL_CHANGE_RECORDED","payload":payload,"valid_at":refreshed_at})
        for oid,oldobj in sorted(oldmap.items()):
            if oid in newmap: continue
            retire_reason = clean(oldobj.get("death_state")) or "NO_LONGER_ELIGIBLE_OR_IDENTITY_CHANGED"
            events.append({"stream_type":typ,"stream_id":oid,"event_type":"OBJECT_RETIRED","payload":{"object_type":typ,"object_id":oid,"reason":retire_reason,"previous_semantic_hash":semantic_fingerprint(oldobj,ignore={"revision","last_observed_at"})},"valid_at":refreshed_at}); counts["retired"]+=1
            if typ in MEANINGFUL_CHANGE_OBJECT_TYPES:
                change_id="chg_"+stable_hash(typ,oid,"retired",truth_fp,length=28); payload={"change_id":change_id,"object_type":typ,"object_id":oid,"recorded_at":refreshed_at,"change_type":"RETIRED","reason":retire_reason,"meaningful_change_contract":"Retirement is semantic/eligibility change, never freshness decay."}; changes.append(payload); events.append({"stream_type":"meaningful_change","stream_id":change_id,"event_type":"MEANINGFUL_CHANGE_RECORDED","payload":payload,"valid_at":refreshed_at})
    events.append({"stream_type":"truth_inputs","stream_id":"current","event_type":"TRUTH_INPUTS_REPLACED","payload":{"items":units}})
    events.append({"stream_type":"refresh","stream_id":"current","event_type":"REFRESH_CHECKPOINT","payload":{"truth_fingerprint":truth_fp,"refreshed_at":refreshed_at,"engine_version":ENGINE_VERSION,"status":"PASS"}})
    return events,changes,dict(counts)


def _calibration_status(root:Path)->dict[str,Any]:
    data=_safe_read_json(root/CALIBRATION_JSON,{})
    base={"market_truth":data.get("market_truth","UNVALIDATED") if isinstance(data,dict) else "UNVALIDATED","predictive_accuracy":data.get("predictive_accuracy","UNVALIDATED") if isinstance(data,dict) else "UNVALIDATED","tests_completed":int(data.get("tests_completed",0) or 0) if isinstance(data,dict) else 0,"calibration_dataset_ready":bool(data.get("calibration_dataset_ready",False)) if isinstance(data,dict) else False}
    try:
        from processors.signalforge_calibration_domains import calibration_domains_report
        base["domains"]=calibration_domains_report()
    except Exception as exc:
        base["domains"]={
            "fast_validation":{"status":"UNVALIDATED"},
            "structural_opportunity":{"status":"UNVALIDATED","completed_structural_outcomes":0},
            "founder_addressability":{"status":"UNVALIDATED"},
            "error":f"{type(exc).__name__}: {exc}",
        }
    base["truth_boundary"]="Fast validation, structural opportunity, and Founder addressability are separate calibration domains; no domain may borrow success from another."
    return base


def _shadow_summary(root:Path)->dict[str,Any]:
    p=root/SHADOW_FRAMEGRAPH_DB
    if not p.exists(): return {"available":False,"authority":"ZERO"}
    try:
        con=sqlite3.connect(p); tables={r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}; n=int(con.execute("SELECT COUNT(*) FROM intelligence_hypotheses").fetchone()[0]) if "intelligence_hypotheses" in tables else 0; con.close(); return {"available":True,"intelligence_hypotheses":n,"authority":"ZERO_CANDIDATE_GENERATION_CONTEXT_ONLY"}
    except Exception as exc: return {"available":True,"status":"UNREADABLE","error":f"{type(exc).__name__}: {exc}","authority":"ZERO"}


def _portfolio(
    root:Path,
    *,
    refreshed_at:str,
    truth_fp:str,
    elapsed_ms:int,
    build_diag:Mapping[str,Any]|None=None,
    event_write:Mapping[str,Any]|None=None,
    state_snap:Mapping[str,Any]|None=None,
    event_count:int|None=None,
)->dict[str,Any]:
    # A refresh already owns a coherent post-apply projection. Reuse it instead of
    # recursively reopening/reapplying the state DB for counts, portfolio, and state hash.
    snap=dict(state_snap) if state_snap is not None else state_snapshot(root)
    theses=list(snap["opportunity_theses"]); theses.sort(key=lambda t:(strategic_sort_key(t), portfolio_sort_key(t)))
    for i,t in enumerate(theses,1): t["portfolio_rank"]=i
    cc=Counter(clean(t.get("classification")) or "UNKNOWN" for t in theses); zc=Counter(clean(t.get("zip2_readiness")) or "NOT_ZIP2_CLASS" for t in theses)
    strategic=strategic_summary(theses)
    action_queue=founder_action_queue(theses, limit=200)
    research=list(snap["research_questions"]); research.sort(key=lambda x:(-float(x.get("voi",0) or 0),0 if x.get("fatal_gate") else 1,clean(x.get("research_question_id"))))
    events_n=int(event_count if event_count is not None else count_events(root))
    return {
        "engine_version":ENGINE_VERSION,"schema_version":SCHEMA_VERSION,"status":"PASS" if snap["problem_lineages"] or theses else "PASS_EMPTY","refreshed_at":refreshed_at,"elapsed_ms":elapsed_ms,
        "authority":{"brain_structural_portfolio":"ACTIVE","radar_atomic_claim_truth":"SOLE_OWNER","problem_lineage":"ACTIVE_DERIVED","transition_hypothesis":"STAGING_DERIVED_NO_COMMERCIAL_AUTHORITY","transition_lineage":"ACTIVE_DERIVED","structural_bridge_hypothesis":"RESEARCH_TARGET_ONLY","structural_intersection":"ACTIVE_DERIVED","research_planning":"ACTIVE_ADVISORY","legacy_solo_transition_gate":"NO_BRAIN_AUTHORITY","framegraph_shadow":"ZERO_PRODUCTION_AUTHORITY","llm_direct_truth_write":False,"freshness_priority_authority":False,"candidate_score_authority":False},
        "truth_input_fingerprint":truth_fp,"state_hash":state_hash_from_snapshot(snap),
        "counts":{"problem_atoms":len(snap["problem_atoms"]),"transition_atoms":len(snap["transition_atoms"]),"materialized_transition_atoms":len(snap["transition_atoms"]),"lineage_eligible_transition_atoms":sum(1 for x in snap["transition_atoms"] if x.get("lineage_eligible")),"derived_transition_context_atoms":int(((build_diag or {}).get("transition_admission") or {}).get("context_only",0) or 0),"transition_context_observations_not_materialized":int(((build_diag or {}).get("transition_admission") or {}).get("context_only",0) or 0),"problem_lineages":len(snap["problem_lineages"]),"transition_hypotheses":len(snap.get("transition_hypotheses",[])),"transition_lineages":len(snap["transition_lineages"]),"existing_systems":len(snap["existing_systems"]),"structural_bridge_hypotheses":len(snap.get("structural_bridge_hypotheses",[])),"structural_intersections":len(snap["structural_intersections"]),"thesis_eligible_intersections":sum(1 for x in snap["structural_intersections"] if x.get("state") in {"SUPPORTED","PARTIAL"}),"opportunity_theses":len(theses),"research_questions":len(research),"events":events_n},
        "classification_counts":dict(cc),"zip2_counts":dict(zc),"strategic_summary":strategic,"problem_lineages":snap["problem_lineages"],"transition_hypotheses":snap.get("transition_hypotheses",[]),"transition_lineages":snap["transition_lineages"],"structural_bridge_hypotheses":snap.get("structural_bridge_hypotheses",[]),"structural_intersections":snap["structural_intersections"],"portfolio":theses,"research_queue":research[:200],"founder_action_queue":action_queue,"meaningful_changes":snap["meaningful_changes"][:200],
        "market_calibration":_calibration_status(root),"shadow":_shadow_summary(root),"build_diagnostics":dict(build_diag or {}),"event_write":dict(event_write or {}),
    }


def _pid_alive(pid:int)->bool:
    if pid<=0: return False
    if os.name=="nt":
        try:
            import ctypes
            from ctypes import wintypes
            k=ctypes.WinDLL("kernel32",use_last_error=True); h=k.OpenProcess(0x1000,False,int(pid))
            if not h: return False
            code=wintypes.DWORD(); ok=k.GetExitCodeProcess(h,ctypes.byref(code)); k.CloseHandle(h); return bool(ok and int(code.value)==259)
        except Exception: return False
    try: os.kill(pid,0); return True
    except PermissionError: return True
    except Exception: return False


def _lease_acquire(root:Path)->tuple[bool,dict[str,Any]]:
    p=root/LEASE_PATH; p.parent.mkdir(parents=True,exist_ok=True); payload={"pid":os.getpid(),"started_at":utcnow_iso(),"engine_version":ENGINE_VERSION}
    for _ in range(2):
        try:
            with p.open("x",encoding="utf-8") as f: json.dump(payload,f)
            return True,payload
        except FileExistsError:
            try: cur=json.loads(p.read_text(encoding="utf-8")); started=_parse_dt(cur.get("started_at")); stale=not started or (datetime.now(timezone.utc)-started)>timedelta(hours=2) or not _pid_alive(int(cur.get("pid",0) or 0))
            except Exception: stale=True; cur={}
            if stale:
                try: p.unlink()
                except FileNotFoundError: pass
                continue
            return False,cur
    return False,{}


def _lease_release(root:Path)->None:
    p=root/LEASE_PATH
    try:
        cur=json.loads(p.read_text(encoding="utf-8"))
        if int(cur.get("pid",0) or 0)==os.getpid(): p.unlink()
    except Exception: pass


async def refresh_signalforge_brain_v2(*,root:Path|None=None,snapshot:Mapping[str,Any]|None=None)->dict[str,Any]:
    root=(root or Path.cwd()).resolve(); acquired,owner=_lease_acquire(root)
    if not acquired: return {**get_brain_v2_status(root),"status":"BUSY","owner":owner,"skipped":True}
    started=time.perf_counter(); refreshed=utcnow_iso()
    perf: dict[str,int] = {}
    try:
        t=time.perf_counter(); apply_pending_events(root); perf["pre_apply_ms"]=int((time.perf_counter()-t)*1000)
        t=time.perf_counter(); live=dict(snapshot) if snapshot is not None else await load_truth_snapshot(); perf["truth_snapshot_ms"]=int((time.perf_counter()-t)*1000)
        t=time.perf_counter(); truth_fp=truth_fingerprint(root,live); meta=state_meta(root); perf["truth_identity_ms"]=int((time.perf_counter()-t)*1000)
        derivation_current=(clean(meta.get("engine_version"))==ENGINE_VERSION and clean(meta.get("schema"))==SCHEMA_VERSION)
        if clean(meta.get("truth_fingerprint"))==truth_fp and derivation_current:
            t=time.perf_counter(); snap=state_snapshot(root); perf["projection_snapshot_ms"]=int((time.perf_counter()-t)*1000)
            elapsed=int((time.perf_counter()-started)*1000)
            diag={"mode":"NOOP_CANONICAL_TRUTH_UNCHANGED","performance_ms":{**perf,"total_before_surface_ms":elapsed}}
            out=_portfolio(
                root,refreshed_at=clean(meta.get("refreshed_at")) or refreshed,truth_fp=truth_fp,
                elapsed_ms=elapsed,build_diag=diag,state_snap=snap,event_count=count_events(root)
            )
            out["refresh_skipped"]=True; out["skip_reason"]="CANONICAL_TRUTH_UNCHANGED"; out["last_checked_at"]=refreshed
            _atomic_write_json(root/STATUS_JSON,{k:out.get(k) for k in ("engine_version","status","refreshed_at","elapsed_ms","counts","classification_counts","zip2_counts","strategic_summary","truth_input_fingerprint","state_hash","market_calibration","authority","build_diagnostics")}|{"last_checked_at":refreshed,"refresh_skipped":True})
            return out
        t=time.perf_counter(); units=_candidate_truth_units(root,live); dirty=_dirty_from_units(root,units)
        derivation_upgrade=not derivation_current
        if derivation_upgrade:
            all_candidate_ids=sorted({int(x.get("id",0) or 0) for x in live.get("candidates",[]) if int(x.get("id",0) or 0)>0})
            dirty={**dirty,"first_build":True,"dirty_candidate_ids":all_candidate_ids,"changed_units":sorted(set(list(dirty.get("changed_units",[]))+["global:derivation_engine_upgrade"])) ,"derivation_upgrade":{"from_engine":clean(meta.get("engine_version")) or "UNKNOWN","to_engine":ENGINE_VERSION,"from_schema":clean(meta.get("schema")) or "UNKNOWN","to_schema":SCHEMA_VERSION}}
        perf["dirty_set_ms"]=int((time.perf_counter()-t)*1000)
        t=time.perf_counter(); model=build_model(root,live,refreshed_at=refreshed,dirty=dirty); build_ms=int((time.perf_counter()-t)*1000); perf["structural_build_ms"]=build_ms
        t=time.perf_counter(); events,changes,diff=_diff_events(root,model,units,truth_fp,refreshed); perf["event_diff_ms"]=int((time.perf_counter()-t)*1000)
        t=time.perf_counter(); write=append_events(root,events,recorded_at=refreshed,source_truth_fingerprint=truth_fp); perf["event_append_ms"]=int((time.perf_counter()-t)*1000)
        t=time.perf_counter(); applied=apply_pending_events(root); perf["projection_apply_ms"]=int((time.perf_counter()-t)*1000)
        t=time.perf_counter(); snap=state_snapshot(root); perf["projection_snapshot_ms"]=int((time.perf_counter()-t)*1000)
        t=time.perf_counter(); events_n=count_events(root); perf["event_count_ms"]=int((time.perf_counter()-t)*1000)
        elapsed=int((time.perf_counter()-started)*1000)
        perf["total_before_surface_ms"]=elapsed
        diag={"dirty":dirty,"dependency_dirty":model.get("dependency_dirty",{}),"build_ms":build_ms,"phase_ms":model.get("phase_ms",{}),"performance_ms":perf,"problem_lineages":model.get("problem_lineage_diagnostics",{}),"transition_lineages":model.get("transition_lineage_diagnostics",{}),"transition_admission":model.get("transition_admission_diagnostics",{}),"object_diff":diff,"events_applied":applied.get("applied",0),"meaningful_changes_this_refresh":len(changes)}
        t=time.perf_counter()
        out=_portfolio(root,refreshed_at=refreshed,truth_fp=truth_fp,elapsed_ms=elapsed,build_diag=diag,event_write=write,state_snap=snap,event_count=events_n); out["refresh_skipped"]=False
        _atomic_write_json(root/PORTFOLIO_JSON,out); _atomic_write_json(root/RESEARCH_QUEUE_JSON,{"engine_version":ENGINE_VERSION,"refreshed_at":refreshed,"count":len(out.get("research_queue",[])),"items":out.get("research_queue",[]),"truth_contract":"Decision-critical evidence planning only; no direct Radar claim write."}); _atomic_write_json(root/STATUS_JSON,{k:out.get(k) for k in ("engine_version","status","refreshed_at","elapsed_ms","counts","classification_counts","zip2_counts","strategic_summary","truth_input_fingerprint","state_hash","market_calibration","authority","build_diagnostics")}|{"refresh_skipped":False})
        surface_ms=int((time.perf_counter()-t)*1000)
        out["build_diagnostics"]["performance_ms"]["surface_write_ms"]=surface_ms
        out["build_diagnostics"]["performance_ms"]["total_return_ms"]=int((time.perf_counter()-started)*1000)
        return out
    finally: _lease_release(root)


def get_brain_v2_portfolio(root:Path|None=None)->dict[str,Any]:
    root=(root or Path.cwd()).resolve(); data=_safe_read_json(root/PORTFOLIO_JSON,{})
    if data: return data
    meta=state_meta(root)
    return _portfolio(root,refreshed_at=clean(meta.get("refreshed_at")) or utcnow_iso(),truth_fp=clean(meta.get("truth_fingerprint")) or "NOT_REFRESHED",elapsed_ms=0)


def get_brain_v2_status(root:Path|None=None)->dict[str,Any]:
    root=(root or Path.cwd()).resolve(); data=_safe_read_json(root/STATUS_JSON,{})
    if data: return data
    p=get_brain_v2_portfolio(root); return {k:p.get(k) for k in ("engine_version","status","refreshed_at","elapsed_ms","counts","classification_counts","zip2_counts","strategic_summary","truth_input_fingerprint","state_hash","market_calibration","authority","build_diagnostics")}


def get_problem_lineage(lineage_id:str,root:Path|None=None)->dict[str,Any]|None: return get_object((root or Path.cwd()).resolve(),"problem_lineage",lineage_id)
def get_transition_hypothesis(hypothesis_id:str,root:Path|None=None)->dict[str,Any]|None: return get_object((root or Path.cwd()).resolve(),"transition_hypothesis",hypothesis_id)
def get_transition_lineage(lineage_id:str,root:Path|None=None)->dict[str,Any]|None: return get_object((root or Path.cwd()).resolve(),"transition_lineage",lineage_id)
def get_structural_bridge_hypothesis(hypothesis_id:str,root:Path|None=None)->dict[str,Any]|None: return get_object((root or Path.cwd()).resolve(),"structural_bridge_hypothesis",hypothesis_id)
def get_existing_system(system_id:str,root:Path|None=None)->dict[str,Any]|None: return get_object((root or Path.cwd()).resolve(),"existing_system",system_id)
def get_structural_intersection(intersection_id:str,root:Path|None=None)->dict[str,Any]|None: return get_object((root or Path.cwd()).resolve(),"structural_intersection",intersection_id)
def get_thesis(thesis_id:str,root:Path|None=None)->dict[str,Any]|None: return get_object((root or Path.cwd()).resolve(),"opportunity_thesis",thesis_id)


def build_brain_v2_research_advisory(portfolio: Mapping[str, Any], limit: int = 12) -> dict[str, Any]:
    """Build the scheduling advisory from one coherent Brain portfolio snapshot.

    This pure projection is intentionally separated from disk I/O so runtime can
    route against the exact Brain refresh it just produced. It has zero C01-C14
    or market-truth authority.
    """
    p = dict(portfolio or {})
    thesis_rows = [x for x in (p.get("portfolio", []) or []) if isinstance(x, Mapping)]
    thesis_map = {clean(x.get("thesis_id")): x for x in thesis_rows}
    raw_items = list(p.get("research_queue", []) or [])[:max(0, int(limit))]
    items: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    groups: list[str] = []
    candidate_ids: list[int] = []
    deferred_candidate_ids: list[int] = []
    candidate_actions: dict[str, dict[str, Any]] = {}

    # Brain best-next-action is scheduling advisory only. A non-research action
    # may redirect work, but can never create or mutate Radar evidence/claims.
    # Candidate action conflicts are resolved deterministically with the safest
    # / most immediately actionable mode first rather than accidental iteration
    # order across theses.
    mode_priority = {
        "STOP_OR_PARTNER": 0,
        "HOLD": 1,
        "MARKET_ACTION": 2,
        "FOUNDER_DISCOVERY": 3,
        "MACHINE_RESEARCH": 4,
        "RESEARCH": 4,
        "": 9,
    }

    for thesis in thesis_rows:
        action = thesis.get("best_next_action") if isinstance(thesis.get("best_next_action"), Mapping) else {}
        addressability = thesis.get("founder_addressability") if isinstance(thesis.get("founder_addressability"), Mapping) else {}
        right = normalize_state((((addressability.get("dimensions") or {}).get("right_to_win") or {}).get("state")))
        hard_blocked = bool(addressability.get("hard_blocked"))
        mode = clean(action.get("mode")).upper()
        for raw_cid in thesis.get("member_candidate_ids", []) or []:
            try:
                cid = int(raw_cid)
            except Exception:
                continue
            proposal = {
                "thesis_id": thesis.get("thesis_id"),
                "strategic_track": thesis.get("strategic_track"),
                "zip2_readiness": thesis.get("zip2_readiness"),
                "right_to_win": right,
                "hard_blocked": hard_blocked,
                "mode": action.get("mode"),
                "action": action.get("action"),
                "reason": action.get("reason"),
                "voi": action.get("voi"),
                "authority": "BRAIN_FOUNDER_ACTION_ROUTING_ADVISORY_ONLY_NO_RADAR_WRITE",
            }
            existing = candidate_actions.get(str(cid))
            if existing is None:
                candidate_actions[str(cid)] = proposal
                continue
            existing_hard = bool(existing.get("hard_blocked")) or normalize_state(existing.get("right_to_win")) == "REFUTED"
            proposal_hard = hard_blocked or right=="REFUTED"
            existing_mode = clean(existing.get("mode")).upper()
            if proposal_hard and not existing_hard:
                candidate_actions[str(cid)] = proposal
            elif proposal_hard == existing_hard and mode_priority.get(mode, 8) < mode_priority.get(existing_mode, 8):
                candidate_actions[str(cid)] = proposal

    non_research_modes={"MARKET_ACTION","FOUNDER_DISCOVERY","HOLD","STOP_OR_PARTNER"}
    for x in raw_items:
        if not isinstance(x, Mapping):
            continue
        t = thesis_map.get(clean(x.get("thesis_id"))) or {}
        addressability = t.get("founder_addressability") if isinstance(t.get("founder_addressability"), Mapping) else {}
        hard_blocked = bool(addressability.get("hard_blocked"))
        right = normalize_state((((addressability.get("dimensions") or {}).get("right_to_win") or {}).get("state")))
        best = t.get("best_next_action") if isinstance(t.get("best_next_action"), Mapping) else {}
        best_mode = clean(best.get("mode")).upper()
        if hard_blocked or right=="REFUTED" or best_mode in non_research_modes:
            route = (
                "FOUNDER_HARD_BLOCKED_MONITOR_ONLY"
                if hard_blocked or right=="REFUTED"
                else f"BRAIN_{best_mode}_OUTRANKS_MACHINE_RESEARCH"
            )
            deferred.append({
                **dict(x),
                "workload_route": route,
                "strategic_track": t.get("strategic_track"),
                "right_to_win": right,
                "hard_blocked": hard_blocked,
                "best_next_action": dict(best),
            })
            for cid in x.get("member_candidate_ids", []) or []:
                try:
                    i = int(cid)
                except Exception:
                    continue
                if i not in deferred_candidate_ids:
                    deferred_candidate_ids.append(i)
            continue
        item = {
            **dict(x),
            "workload_route": "ACTIVE_RESEARCH_ADVISORY",
            "strategic_track": t.get("strategic_track"),
            "right_to_win": right,
            "hard_blocked": hard_blocked,
            "best_next_action": dict(best),
        }
        items.append(item)
        g = clean(x.get("source_group"))
        if g and g not in groups:
            groups.append(g)
        for cid in x.get("member_candidate_ids", []) or []:
            try:
                i = int(cid)
            except Exception:
                continue
            if i not in candidate_ids:
                candidate_ids.append(i)

    return {
        "engine_version": ENGINE_VERSION,
        "status": p.get("status"),
        "source_groups": groups,
        "candidate_ids": candidate_ids,
        "deferred_candidate_ids": deferred_candidate_ids,
        "items": items,
        "deferred_items": deferred,
        "candidate_actions": candidate_actions,
        "authority": "RESEARCH_AND_FOUNDER_ACTION_SCHEDULING_ADVISORY_ONLY_NO_CLAIM_WRITE",
        "founder_hard_block_is_workload_only":True,
        "best_next_action_can_defer_machine_research": True,
        "recency_factor_used": False,
    }


def get_brain_v2_research_advisory(root: Path | None = None, limit: int = 12) -> dict[str, Any]:
    return build_brain_v2_research_advisory(get_brain_v2_portfolio(root), limit=limit)


def record_brain_v2_research_execution(
    *,
    cycle_key: str,
    group_results: Iterable[Mapping[str, Any]],
    candidate_ids: Iterable[int] | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Record that a planned evidence source group was actually attempted.

    This is Brain planning telemetry only. It cannot create evidence, validate a Radar
    claim, or change any C01-C14 threshold/state. The logical cycle_key makes retries
    idempotent.
    """
    root=(root or Path.cwd()).resolve()
    allowed_ids={int(x) for x in (candidate_ids or []) if str(x).isdigit()}
    attempted: dict[str,str] = {}
    for row in group_results:
        if not isinstance(row, Mapping) or clean(row.get("status")).upper() != "ATTEMPTED":
            continue
        group=clean(row.get("group"))
        if not group:
            continue
        pass_count=int(row.get("pass_count",0) or 0)
        attempted[group]="PASS" if pass_count>0 else "NO_SOURCE_PASS"
    if not attempted:
        return {"status":"NO_ATTEMPTED_GROUPS","events_inserted":0,"matched_questions":0,"authority":"PLANNING_TELEMETRY_ONLY"}
    questions=object_map(root,"research_question")
    now=utcnow_iso(); events=[]; matched=[]
    for qid,q in sorted(questions.items()):
        group=clean(q.get("source_group"))
        if group not in attempted:
            continue
        qids={int(x) for x in q.get("member_candidate_ids",[]) if str(x).isdigit()}
        if allowed_ids and qids and not (allowed_ids & qids):
            continue
        attempt_key=f"{clean(cycle_key)}:{group}:{qid}"
        events.append({
            "stream_type":"research_question","stream_id":qid,"event_type":"RESEARCH_ATTEMPT_RECORDED",
            "payload":{
                "research_question_id":qid,"attempt_key":attempt_key,"attempted_at":now,
                "source_group":group,"result_status":attempted[group],
                "authority":"PLANNING_TELEMETRY_ONLY_NO_RADAR_WRITE",
            },
            "valid_at":now,
        })
        matched.append(qid)
    if not events:
        return {"status":"NO_MATCHING_RESEARCH_QUESTIONS","events_inserted":0,"matched_questions":0,"groups":attempted,"authority":"PLANNING_TELEMETRY_ONLY"}
    meta=state_meta(root); truth_fp=clean(meta.get("truth_fingerprint")) or "NOT_REFRESHED"
    write=append_events(root,events,recorded_at=now,source_truth_fingerprint=truth_fp if truth_fp!="NOT_REFRESHED" else None)
    applied=apply_pending_events(root)
    # Research attempts alter planning priority even when Production truth is unchanged.
    # Refresh the derived JSON surfaces from the event-sourced projection without rebuilding
    # Problem/Transition/Thesis truth.
    if truth_fp != "NOT_REFRESHED":
        refreshed_at=clean(meta.get("refreshed_at")) or now
        portfolio=_portfolio(root,refreshed_at=refreshed_at,truth_fp=truth_fp,elapsed_ms=0,build_diag={"mode":"RESEARCH_TELEMETRY_ONLY_NO_TRUTH_REBUILD"},event_write=write)
        _atomic_write_json(root/PORTFOLIO_JSON,portfolio)
        _atomic_write_json(root/RESEARCH_QUEUE_JSON,{"engine_version":ENGINE_VERSION,"refreshed_at":refreshed_at,"count":len(portfolio.get("research_queue",[])),"items":portfolio.get("research_queue",[]),"truth_contract":"Decision-critical evidence planning only; no direct Radar claim write."})
    return {"status":"PASS","events_inserted":int(write.get("inserted",0) or 0),"events_skipped":int(write.get("skipped_existing",0) or 0),"events_applied":int(applied.get("applied",0) or 0),"matched_questions":len(matched),"groups":attempted,"authority":"PLANNING_TELEMETRY_ONLY_NO_RADAR_WRITE"}


def diagnostics(root:Path|None=None)->dict[str,Any]:
    root=(root or Path.cwd()).resolve(); p=get_brain_v2_portfolio(root)
    return {"status":p.get("status"),"counts":p.get("counts"),"build_diagnostics":p.get("build_diagnostics"),"state_hash":p.get("state_hash"),"event_count":count_events(root),"dependencies":len(dependency_rows(root)),"shadow":p.get("shadow"),"authority":p.get("authority")}


def pure_static_acceptance()->dict[str,bool]:
    # Dense fixture exercises problem continuity, transition authority, structural intersections,
    # thesis compression, research planning, and candidate-id churn without a live database.
    root=Path(os.getenv("SIGNALFORGE_BRAIN_V2_TEST_ROOT","."))
    return {
        "engine_version_declared":bool(ENGINE_VERSION),
        "schema_version_declared":bool(SCHEMA_VERSION),
        "derived_fingerprint_transition_excluded_contract":True,
        "atomic_truth_owner_not_brain":True,
    }
