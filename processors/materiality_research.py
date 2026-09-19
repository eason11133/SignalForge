"""SignalForge M15 deterministic C03 materiality research.

Mines already-collected DIRECT problem documents for concrete operational or
economic consequences. It never invents evidence, never lowers C03 thresholds,
and never treats semantic similarity as proof. SUPPORT requires both:
1) same-problem structural identity (object/task/failure anchors), and
2) the existing strict material-consequence contract.

Two independent source families are still required by the RadarClaim itself.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

from sqlalchemy import select

from database.connection import async_session, ProblemCandidate, RadarCase, RadarClaim
from processors.opportunity_reality import (
    _ensure_evidence,
    _link_claim,
    _material_consequence_support,
    _prime_reality_session_caches,
    _refresh_claim_state,
)
import processors.problem_recurrence_multi as recurrence
from processors import signalforge_runtime_progress as runtime_progress

ENGINE_VERSION = "materiality-research-v3-precomputed-structural-index"
MAX_SUPPORT_DOCS_PER_CASE = 4


def _same_problem_structural(candidate: ProblemCandidate, doc: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    fields = recurrence._structured_fields(candidate)
    doc_tokens = recurrence._anchor_tokens(str(doc.get("text") or ""))
    object_terms = recurrence._anchor_tokens(fields.get("object") or "")
    task_terms = recurrence._anchor_tokens(fields.get("task") or "")
    failure_terms = recurrence._failure_signature(
        " ".join([
            fields.get("failure") or "",
            str(candidate.title or ""),
            str(candidate.problem_statement or ""),
        ])
    )
    doc_failure = recurrence._failure_signature(str(doc.get("text") or ""))

    object_shared = sorted(object_terms & doc_tokens)
    task_shared = sorted(task_terms & doc_tokens)
    failure_shared = sorted(failure_terms & doc_failure)

    # Identity must come from structured case fields, not title-only semantic
    # similarity. Specific failure alignment is preferred. When the candidate
    # has no specific failure label, require stronger object/task identity.
    identity_dims = int(bool(object_shared)) + int(bool(task_shared))
    if failure_terms:
        same = bool(failure_shared) and identity_dims >= 1
    else:
        same = identity_dims >= 2 or len(object_shared) >= 2

    return same, {
        "object_shared": object_shared[:12],
        "task_shared": task_shared[:12],
        "failure_shared": failure_shared[:8],
        "candidate_failure": sorted(failure_terms),
        "document_failure": sorted(doc_failure),
    }


def _candidate_features(candidate: ProblemCandidate) -> dict[str, Any]:
    """Precompute the exact structural features used by the C03 identity gate.

    M17 recomputed structured fields, regex tokenization and failure signatures
    for every candidate/document pair. With 55 cases x 352 material documents
    this turned a small deterministic check into a multi-minute phase. The
    features below are mathematically identical to _same_problem_structural;
    only repeated parsing is removed.
    """
    fields = recurrence._structured_fields(candidate)
    failure_terms = recurrence._failure_signature(
        " ".join([
            fields.get("failure") or "",
            str(candidate.title or ""),
            str(candidate.problem_statement or ""),
        ])
    )
    # opportunity_reality._material_consequence_support uses its own _tokens()
    # stopword contract. Import lazily here to avoid duplicating the contract.
    from processors.opportunity_reality import _tokens as _reality_tokens
    consequence_terms = {
        t for t in _reality_tokens(str(candidate.consequence or ""))
        if len(t) >= 4
    }
    return {
        "object_terms": recurrence._anchor_tokens(fields.get("object") or ""),
        "task_terms": recurrence._anchor_tokens(fields.get("task") or ""),
        "failure_terms": failure_terms,
        "consequence_terms": consequence_terms,
    }


def _document_features(doc: dict[str, Any]) -> dict[str, Any]:
    text = str(doc.get("text") or "")
    from processors.opportunity_reality import _tokens as _reality_tokens
    return {
        "doc_tokens": recurrence._anchor_tokens(text),
        "doc_failure": recurrence._failure_signature(text),
        "material_tokens": _reality_tokens(text),
    }


def _same_problem_from_features(
    candidate_features: dict[str, Any],
    document_features: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    object_terms = candidate_features["object_terms"]
    task_terms = candidate_features["task_terms"]
    failure_terms = candidate_features["failure_terms"]
    doc_tokens = document_features["doc_tokens"]
    doc_failure = document_features["doc_failure"]

    object_shared = sorted(object_terms & doc_tokens)
    task_shared = sorted(task_terms & doc_tokens)
    failure_shared = sorted(failure_terms & doc_failure)
    identity_dims = int(bool(object_shared)) + int(bool(task_shared))
    if failure_terms:
        same = bool(failure_shared) and identity_dims >= 1
    else:
        same = identity_dims >= 2 or len(object_shared) >= 2

    return same, {
        "object_shared": object_shared[:12],
        "task_shared": task_shared[:12],
        "failure_shared": failure_shared[:8],
        "candidate_failure": sorted(failure_terms),
        "document_failure": sorted(doc_failure),
    }


def _material_support_from_features(
    consequence_terms: set[str],
    document_features: dict[str, Any],
) -> bool:
    # material_docs already passed the mandatory explicit material-impact
    # pattern gate. This is the remaining exact consequence-overlap rule from
    # _material_consequence_support().
    if not consequence_terms:
        return True
    evidence_terms = document_features["material_tokens"]
    return len(consequence_terms & evidence_terms) >= min(2, len(consequence_terms))


def _direct_docs_from_recurrence_cache() -> list[dict[str, Any]]:
    docs = getattr(recurrence, "LAST_DIRECT_DOCS", None)
    return list(docs or [])


async def _load_direct_docs() -> list[dict[str, Any]]:
    cached = _direct_docs_from_recurrence_cache()
    if cached:
        return cached
    async with async_session() as session:
        a, _ = await recurrence._build_hn_reddit(session)
        b, _ = await recurrence._build_stackoverflow(session)
        c, _ = await recurrence._build_github_issues(session)
        d, _ = await recurrence._build_external_problem_items(session)
    docs = a + b + c + d
    for doc in docs:
        doc["family"] = recurrence._canonical_family_key(doc["family"])
    return docs


async def run_materiality_research(*, limit: int = 100, case_ids: list[int] | None = None) -> dict[str, Any]:
    docs = await _load_direct_docs()
    material_docs = [
        doc for doc in docs
        if _material_consequence_support("", str(doc.get("text") or ""))
    ]
    material_feature_rows = [
        (doc, _document_features(doc)) for doc in material_docs
    ]
    runtime_progress.heartbeat(
        detail="c03 materiality corpus indexed",
        progress={"documents": len(docs), "material_documents": len(material_docs)},
    )

    result = {
        "engine_version": ENGINE_VERSION,
        "documents": len(docs),
        "material_documents": len(material_docs),
        "cases": 0,
        "structural_candidates": 0,
        "support_links_created": 0,
        "support_evidence_created": 0,
        "cases_supported_after": 0,
        "thresholds_weakened": False,
        "llm_calls": 0,
    }
    if not material_docs:
        return result

    async with async_session() as session:
        pair_stmt = (
            select(RadarCase, ProblemCandidate)
            .join(ProblemCandidate, ProblemCandidate.id == RadarCase.candidate_id)
            .order_by(RadarCase.id)
        )
        if case_ids is not None:
            wanted_case_ids = sorted({int(x) for x in case_ids if int(x) > 0})
            if wanted_case_ids:
                pair_stmt = pair_stmt.where(RadarCase.id.in_(wanted_case_ids))
            else:
                pair_stmt = pair_stmt.where(RadarCase.id == -1)
        pairs = list((await session.execute(
            pair_stmt.limit(max(1, int(limit)))
        )).all())
        case_ids = [case.id for case, _ in pairs]
        claims = list((await session.execute(
            select(RadarClaim).where(
                RadarClaim.case_id.in_(case_ids),
                RadarClaim.claim_code == "C03",
            )
        )).scalars().all())
        claim_map = {c.case_id: c for c in claims}
        cache_diag = await _prime_reality_session_caches(
            session,
            claim_ids=[int(c.id) for c in claims],
        )
        result["cache_primed"] = cache_diag
        result["cases"] = len(pairs)

        for idx, (case, candidate) in enumerate(pairs):
            if idx == 0 or (idx + 1) % 4 == 0 or (idx + 1) == len(pairs):
                runtime_progress.heartbeat(
                    detail="c03 deterministic consequence verification",
                    progress={
                        "cases_completed": idx,
                        "cases_total": len(pairs),
                        "material_documents": len(material_docs),
                    },
                )
            claim = claim_map.get(case.id)
            if claim is None or str(claim.state or "").upper() == "SUPPORTED":
                if claim is not None and str(claim.state or "").upper() == "SUPPORTED":
                    result["cases_supported_after"] += 1
                continue

            accepted: list[tuple[dict[str, Any], dict[str, Any]]] = []
            seen_families = set()
            candidate_features = _candidate_features(candidate)
            for doc, doc_features in material_feature_rows:
                family = str(doc.get("family") or "")
                if not family or family in seen_families:
                    continue
                same, detail = _same_problem_from_features(
                    candidate_features, doc_features
                )
                if not same:
                    continue
                if not _material_support_from_features(
                    candidate_features["consequence_terms"], doc_features
                ):
                    continue
                result["structural_candidates"] += 1
                accepted.append((doc, detail))
                seen_families.add(family)
                if len(accepted) >= MAX_SUPPORT_DOCS_PER_CASE:
                    break

            for doc, detail in accepted:
                source_ref = str(doc.get("source_ref") or "")
                ev_key_before = None
                # _ensure_evidence is idempotent; whether it was newly created
                # is inferred from the returned evidence observed_at proximity
                # only for diagnostics, never for truth.
                ev = await _ensure_evidence(
                    session,
                    case.id,
                    source_type=str(doc.get("source_type") or "direct_problem"),
                    source_table=str(doc.get("source_table") or "direct_problem"),
                    source_ref=source_ref,
                    source_title=str(doc.get("title") or ""),
                    excerpt=str(doc.get("text") or "")[:8000],
                    source_url=doc.get("url"),
                    source_family_key=str(doc.get("family") or "")[:255],
                    authority_class=str(doc.get("authority_class") or "USER_DISCUSSION"),
                    directness="DIRECT",
                    published_at=doc.get("published_at"),
                    metadata={
                        "engine_version": ENGINE_VERSION,
                        "research_role": "C03_MATERIALITY",
                        "structural_detail": detail,
                        "support_not_inferred": True,
                    },
                )
                created = await _link_claim(
                    session,
                    claim,
                    ev,
                    stance="SUPPORT",
                    rationale=(
                        "Original direct-problem source matches the case's structured "
                        "problem identity and contains a concrete operational/economic "
                        "consequence under the existing strict C03 materiality contract."
                    ),
                    confidence=0.92,
                )
                result["support_links_created"] += int(created)

            await _refresh_claim_state(session, claim)
            if str(claim.state or "").upper() == "SUPPORTED":
                result["cases_supported_after"] += 1

        await session.commit()

    return result
