
"""Radar Production — Same-Problem Verification Pipeline.

Production C02 recurrence pipeline:
1. existing strict lexical/character retrieval (unchanged acceptance gates);
2. local semantic LSA retrieval for recall;
3. deterministic structured-field verification for precision;
4. at most four narrow same_problem_verify AI adjudications per run;
5. deterministic validation of AI output before any SUPPORT link is written;
6. persistent pair cache in RadarResearchAction.result_metadata;
7. coverage-aware abstention using V4.4a Coverage Truth.

Policies:
- Semantic similarity alone never creates evidence.
- AI never searches, invents evidence, scores opportunities, or changes verdicts directly.
- RELATED / DIFFERENT / INSUFFICIENT pair judgments never refute C02 globally.
- Only original source content becomes RadarEvidence; AI only interprets the pair.
- Existing strict lexical STRONG thresholds are unchanged.
- Coverage errors/rate limits never become negative market evidence.
"""

from __future__ import annotations

import hashlib
import html
import json
import math
import os
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
import uuid
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import numpy as np
import structlog
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.preprocessing import normalize
from sqlalchemy import func, select

import database.connection as db
from database.connection import (
    async_session,
    Platform,
    Post,
    ProblemCandidate,
    RadarCase,
    RadarClaim,
    RadarEvidence,
    RadarClaimEvidence,
    RadarUnknown,
    RadarResearchAction,
    RadarAIBudgetLedger,
    RadarDecisionEvent,
    GithubIssue,
    ExternalProblemItem,
)
from processors.ai_budget_gate import evaluate_ai_gate
from processors import signalforge_runtime_progress as runtime_progress
from processors.llm_client import TokenUsage, call_llm
from scrapers.coverage_controller import coverage_snapshot
from processors.problem_recurrence import (
    FRICTION_RE,
    PRODUCT_CONTEXT_RE,
    build_hn_parent,
    clean_text,
    content_hash,
    discussion_key_for_hn,
    discussion_key_for_reddit,
    failure_buckets,
    norm_text,
    query_text,
    strict_match,
    word_set,
)

log = structlog.get_logger().bind(processor="problem_recurrence_multi")
ENGINE_VERSION = "radar-production-same-problem-v2-cycle-budgeted"
LAST_DIRECT_DOCS: list[dict[str, Any]] = []
LAST_DIRECT_CORPUS_COUNTS: dict[str, int] = {}
C02_RETRIEVAL_CACHE_DIR = Path(".radar_runtime/retrieval_cache")
C02_RETRIEVAL_CACHE_SCHEMA = "c02-exact-matrix-r7-v1"

SO_PROBLEM_RE = re.compile(
    r"""(?ix)\b(
        error|exception|fail|fails|failed|failing|failure|
        unable|cannot|can't|cant|won't|doesn't|doesnt|
        not\s+working|not\s+work|does\s+not\s+work|
        issue|problem|invalid|validation|unexpected|
        wrong|broken|missing|stuck|timeout|crash|
        how\s+to\s+(?:fix|resolve|solve|debug)|
        why\s+(?:does|is|can|can't|cannot)
    )\b"""
)



def _hash_text_sequence(h: "hashlib._Hash", values: list[str]) -> None:
    for value in values:
        raw = str(value or "").encode("utf-8", errors="ignore")
        h.update(len(raw).to_bytes(8, "little", signed=False))
        h.update(raw)


def _c02_retrieval_cache_key(
    *,
    abstracts: list[str],
    exemplars: list[str],
    field_queries: list[str],
    doc_texts: list[str],
) -> str:
    h = hashlib.sha256()
    h.update(C02_RETRIEVAL_CACHE_SCHEMA.encode("ascii"))
    _hash_text_sequence(h, abstracts)
    _hash_text_sequence(h, exemplars)
    _hash_text_sequence(h, field_queries)
    _hash_text_sequence(h, doc_texts)
    return h.hexdigest()[:32]


def _load_c02_retrieval_cache(key: str, *, n: int, docs: int) -> dict[str, np.ndarray] | None:
    path = C02_RETRIEVAL_CACHE_DIR / f"c02_{key}.npz"
    try:
        if not path.is_file():
            return None
        with np.load(path, allow_pickle=False) as z:
            out = {name: z[name] for name in ("a_word", "e_word", "a_char", "e_char", "semantic")}
        expected = (n, docs)
        if any(tuple(arr.shape) != expected for arr in out.values()):
            return None
        return out
    except Exception:
        return None


def _save_c02_retrieval_cache(key: str, matrices: dict[str, np.ndarray]) -> None:
    """Best-effort exact derived cache. Failure never changes research truth."""
    try:
        C02_RETRIEVAL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        final = C02_RETRIEVAL_CACHE_DIR / f"c02_{key}.npz"
        tmp = C02_RETRIEVAL_CACHE_DIR / f"c02_{key}.{os.getpid()}.{uuid.uuid4().hex[:8]}.npz"
        np.savez_compressed(tmp, **matrices)
        os.replace(tmp, final)
        files = sorted(C02_RETRIEVAL_CACHE_DIR.glob("c02_*.npz"), key=lambda x: x.stat().st_mtime, reverse=True)
        for old in files[6:]:
            try:
                old.unlink()
            except OSError:
                pass
    except Exception:
        try:
            if 'tmp' in locals() and tmp.exists():
                tmp.unlink()
        except Exception:
            pass


def normalize_url(url: str | None) -> str:
    raw = str(url or "").strip()
    if not raw:
        return ""
    try:
        p = urlsplit(raw)
        return urlunsplit((
            p.scheme.lower(),
            p.netloc.lower().removeprefix("www."),
            p.path.rstrip("/"),
            "",
            "",
        ))
    except Exception:
        return raw


def normalize_piece(text: str | None, limit: int = 4200) -> str:
    x = html.unescape(str(text or ""))
    x = re.sub(r"<[^>]+>", " ", x)
    x = re.sub(r"https?://\S+", " ", x)
    x = re.sub(r"\s+", " ", x).strip()
    return x[:limit]


def raw_meta_text(meta: Any) -> str:
    if not isinstance(meta, dict):
        return ""
    keys = (
        "body",
        "body_markdown",
        "content",
        "question",
        "description",
        "excerpt",
        "text",
    )
    chunks = []
    for k in keys:
        v = meta.get(k)
        if isinstance(v, str) and v.strip():
            chunks.append(v)
    return normalize_piece(" ".join(chunks), 5000)


def tags_text(tags: Any) -> str:
    if tags is None:
        return ""
    if isinstance(tags, (list, tuple, set)):
        return " ".join(str(x) for x in tags)
    if isinstance(tags, str):
        return tags.replace("<", " ").replace(">", " ")
    return str(tags)


def _claim_state_local(
    claim_code: str,
    required_support_groups: int,
    links: list[tuple[RadarClaimEvidence, RadarEvidence]],
) -> tuple[str, dict[str, Any]]:
    support_families = {
        ev.source_family_key
        for link, ev in links
        if bool(link.validated) and link.stance == "SUPPORT"
    }
    direct_support_families = {
        ev.source_family_key
        for link, ev in links
        if bool(link.validated)
        and link.stance == "SUPPORT"
        and ev.directness == "DIRECT"
    }
    refute_families = {
        ev.source_family_key
        for link, ev in links
        if bool(link.validated) and link.stance == "REFUTE"
    }
    insufficient_count = sum(
        1
        for link, _ in links
        if bool(link.validated) and link.stance in {"INSUFFICIENT", "RELATED"}
    )

    support_count = (
        len(direct_support_families)
        if claim_code == "C02"
        else len(support_families)
    )
    required = max(1, int(required_support_groups or 1))

    if len(refute_families) >= required and support_count >= required:
        state = "CONFLICTED"
    elif len(refute_families) >= required:
        state = "REFUTED"
    elif support_count >= required:
        state = "SUPPORTED"
    elif support_count > 0 or len(refute_families) > 0 or insufficient_count > 0:
        state = "INSUFFICIENT"
    else:
        state = "UNKNOWN"

    return state, {
        "support_groups": len(support_families),
        "direct_support_groups": len(direct_support_families),
        "refute_groups": len(refute_families),
        "insufficient_or_related": insufficient_count,
        "required_support_groups": required,
    }


async def _one_or_none(session, stmt):
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def _build_hn_reddit(session) -> tuple[list[dict[str, Any]], int]:
    raw_rows = list((await session.execute(
        select(
            Post.id.label("id"),
            Post.user_id.label("user_id"),
            Post.platform_post_id.label("platform_post_id"),
            Post.post_type.label("post_type"),
            Post.title.label("title"),
            Post.body.label("body"),
            Post.url.label("url"),
            Post.score.label("score"),
            Post.num_comments.label("num_comments"),
            Post.posted_at.label("posted_at"),
            Post.raw_metadata.label("raw_metadata"),
            Platform.name.label("platform"),
        )
        .join(Platform, Post.platform_id == Platform.id)
        .where(
            Post.body.isnot(None),
            Platform.name.in_(["reddit", "hackernews"]),
        )
        .order_by(Post.posted_at.desc().nullslast())
        .limit(12000)
    )).all())

    hn_parent = build_hn_parent(raw_rows)
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen_exact = set()

    for row in raw_rows:
        meta = row.raw_metadata if isinstance(row.raw_metadata, dict) else {}
        text = clean_text(row.title, row.body)
        if len(text) < 45:
            continue
        if not FRICTION_RE.search(text):
            continue
        if not PRODUCT_CONTEXT_RE.search(text):
            continue

        digest = content_hash(norm_text(text))
        if digest in seen_exact:
            continue
        seen_exact.add(digest)

        if row.platform == "reddit":
            dkey = discussion_key_for_reddit(
                row.id, row.platform_post_id, row.url, meta
            )
        else:
            dkey = discussion_key_for_hn(
                row.id, row.platform_post_id, meta, hn_parent
            )

        groups[dkey].append({
            "post_id": row.id,
            "user_id": row.user_id,
            "post_type": row.post_type,
            "title": row.title or "",
            "text": text,
            "url": row.url,
            "score": int(row.score or 0),
            "num_comments": int(row.num_comments or 0),
            "posted_at": row.posted_at,
            "platform": row.platform,
            "discussion_key": dkey,
        })

    docs = []
    for dkey, posts in groups.items():
        posts.sort(
            key=lambda p: (
                p["score"] + min(p["num_comments"], 100),
                p["post_type"] == "submission",
            ),
            reverse=True,
        )
        snippets = []
        seen = set()
        for p in posts:
            n = norm_text(p["text"])
            if not n or n in seen:
                continue
            seen.add(n)
            snippets.append(p["text"][:650])
            if len(snippets) >= 6:
                break

        merged = " ".join(snippets)[:3200]
        if len(merged) < 45:
            continue

        docs.append({
            "family": f"discussion:{dkey}",
            "source_type": posts[0]["platform"],
            "source_table": "posts",
            "source_ref": dkey,
            "title": posts[0]["title"],
            "text": merged,
            "url": posts[0]["url"],
            "published_at": max(
                [p["posted_at"] for p in posts if p["posted_at"]],
                default=None,
            ),
            "authority_class": "USER_DISCUSSION",
        })

    return docs, len(raw_rows)


async def _build_stackoverflow(session) -> tuple[list[dict[str, Any]], int]:
    table = db.Base.metadata.tables.get("so_questions")
    if table is None:
        return [], 0

    rows = list((await session.execute(select(table))).mappings().all())
    docs = []

    for row in rows:
        title = normalize_piece(row.get("title"), 900)
        tags = tags_text(row.get("tags"))
        meta = row.get("raw_metadata")
        body = raw_meta_text(meta)

        text = normalize_piece(
            " ".join([
                title,
                f"Tags: {tags}" if tags else "",
                body,
            ]),
            4200,
        )

        if len(text) < 25:
            continue

        # Precision-first admission.
        # Technical tags can provide context even when PRODUCT_CONTEXT_RE
        # doesn't match the natural-language title.
        issue_signal = bool(SO_PROBLEM_RE.search(text) or FRICTION_RE.search(text))
        tech_context = bool(tags.strip()) or bool(PRODUCT_CONTEXT_RE.search(text))
        if not issue_signal or not tech_context:
            continue

        qid = row.get("so_question_id") or row.get("id")
        link = row.get("link")
        created = row.get("creation_date")

        docs.append({
            "family": f"stackoverflow:question:{qid}",
            "source_type": "stackoverflow",
            "source_table": "so_questions",
            "source_ref": str(qid),
            "title": title,
            "text": text,
            "url": link,
            "published_at": created,
            "authority_class": "TECHNICAL_QUESTION",
            "tags": tags,
        })

    return docs, len(rows)



async def _build_github_issues(session) -> tuple[list[dict[str, Any]], int]:
    rows = list((await session.execute(
        select(GithubIssue)
        .order_by(GithubIssue.updated_at.desc().nullslast())
        .limit(10000)
    )).scalars().all())

    docs = []
    for row in rows:
        title = normalize_piece(row.title, 1000)
        body = normalize_piece(row.body, 5000)
        text = normalize_piece(f"{title} {body}", 5200)

        if len(text) < 45:
            continue

        # GitHub Issue is already product/technical context.
        # Only explicit friction enters the C02 recurrence corpus.
        if not FRICTION_RE.search(text):
            continue

        docs.append({
            "family": f"github:issue:{row.github_issue_id}",
            "source_type": "github_issue",
            "source_table": "github_issues",
            "source_ref": str(row.github_issue_id),
            "title": title,
            "text": text,
            "url": row.html_url,
            "published_at": row.created_at,
            "authority_class": "TECHNICAL_ISSUE",
            "repo_full_name": row.repo_full_name,
            "author_login": row.author_login,
        })

    return docs, len(rows)


async def _build_external_problem_items(session) -> tuple[list[dict[str, Any]], int]:
    allowed = {"stackexchange", "gitlab_issue", "discourse_feed"}
    rows = list((await session.execute(
        select(ExternalProblemItem)
        .where(
            ExternalProblemItem.is_direct_problem.is_(True),
            ExternalProblemItem.source_type.in_(sorted(allowed)),
        )
        .order_by(ExternalProblemItem.updated_at.desc().nullslast())
        .limit(20000)
    )).scalars().all())

    docs = []
    for row in rows:
        title = normalize_piece(row.title, 1000)
        body = normalize_piece(row.body, 5000)
        text = normalize_piece(f"{title} {body}", 5200)
        if len(text) < 45:
            continue
        if not FRICTION_RE.search(text):
            continue

        if row.source_type == "stackexchange":
            authority = "TECHNICAL_QUESTION"
        elif row.source_type == "gitlab_issue":
            authority = "TECHNICAL_ISSUE"
        else:
            authority = "USER_DISCUSSION"

        docs.append({
            "family": f"external:{row.source_type}:{row.source_key}:{row.external_id}",
            "source_type": row.source_type,
            "source_table": "external_problem_items",
            "source_ref": str(row.id),
            "title": title,
            "text": text,
            "url": row.url,
            "published_at": row.published_at,
            "authority_class": authority,
        })

    return docs, len(rows)


def _representations(
    case: RadarCase,
    candidate: ProblemCandidate,
    original_evidence: list[RadarEvidence],
) -> tuple[str, str]:
    abstract = query_text(candidate)

    pieces = []
    seen = set()
    for ev in original_evidence:
        piece = normalize_piece(
            " ".join([
                str(ev.source_title or ""),
                str(ev.excerpt or ""),
            ]),
            1800,
        )
        npiece = norm_text(piece)
        if len(piece) >= 45 and npiece not in seen:
            seen.add(npiece)
            pieces.append(piece)

    exemplar = " ".join(pieces[:4])[:4200]
    return abstract, exemplar


def _match_detail(
    abstract: str,
    exemplar: str,
    doc_text: str,
    a_word: float,
    e_word: float,
    a_char: float,
    e_char: float,
) -> tuple[str, dict[str, Any]]:
    a_comb = 0.68 * a_word + 0.32 * a_char
    e_comb = 0.68 * e_word + 0.32 * e_char

    if e_comb > a_comb:
        rep = "EXEMPLAR"
        query = exemplar
        word_sim = e_word
        char_sim = e_char
    else:
        rep = "ABSTRACT"
        query = abstract
        word_sim = a_word
        char_sim = a_char

    verdict, detail = strict_match(query, doc_text, word_sim, char_sim)
    detail = dict(detail)
    detail.update({
        "representation": rep,
        "abstract_combined": round(float(a_comb), 4),
        "exemplar_combined": round(float(e_comb), 4),
        "hybrid_combined": round(float(max(a_comb, e_comb)), 4),
    })
    return verdict, detail


def _balanced_ranked_indices(
    scores: np.ndarray,
    docs: list[dict[str, Any]],
    *,
    total_limit: int,
    global_keep: int,
    per_source_supplement: int,
) -> list[int]:
    """Preserve the strongest global matches while preventing one huge corpus family
    from consuming every retrieval slot. This changes retrieval scheduling only;
    strict same-problem/evidence thresholds remain untouched.
    """
    ranked = [int(x) for x in np.argsort(-scores)]
    limit = max(0, min(int(total_limit), len(ranked)))
    if limit <= 0:
        return []
    global_keep = max(0, min(int(global_keep), limit))
    selected = ranked[:global_keep]
    selected_set = set(selected)
    source_counts: Counter[str] = Counter(
        str((docs[idx] or {}).get("source_type") or "unknown") for idx in selected
    )

    for idx in ranked[global_keep:]:
        if len(selected) >= limit:
            break
        source = str((docs[idx] or {}).get("source_type") or "unknown")
        if source_counts[source] >= max(1, int(per_source_supplement)):
            continue
        selected.append(idx)
        selected_set.add(idx)
        source_counts[source] += 1

    # If the corpus genuinely has only one useful source type, do not throw
    # away recall merely to manufacture diversity. Fill remaining slots by the
    # original ranking.
    if len(selected) < limit:
        for idx in ranked:
            if idx in selected_set:
                continue
            selected.append(idx)
            if len(selected) >= limit:
                break
    return selected


async def _recompute_case(
    session,
    case: RadarCase,
    claim: RadarClaim,
    unknown: RadarUnknown | None,
):
    pairs = list((await session.execute(
        select(RadarClaimEvidence, RadarEvidence)
        .join(RadarEvidence, RadarEvidence.id == RadarClaimEvidence.evidence_id)
        .where(RadarClaimEvidence.claim_id == claim.id)
    )).all())

    state, es = _claim_state_local(
        claim.claim_code,
        claim.required_support_groups,
        pairs,
    )

    claim.state = state
    claim.support_groups = es["support_groups"]
    claim.direct_support_groups = es["direct_support_groups"]
    claim.refute_groups = es["refute_groups"]
    claim.insufficient_count = es["insufficient_or_related"]
    claim.evidence_summary = es
    claim.last_evaluated_at = datetime.now()

    if unknown is not None:
        unknown.state = "RESOLVED" if state in {"SUPPORTED", "REFUTED"} else "OPEN"

    if state == "SUPPORTED":
        verdict = "INVESTIGATE"
        reason = "problem_reality_passed"
    elif state == "REFUTED":
        verdict = "IGNORE"
        reason = "problem_recurrence_refuted"
    else:
        verdict = "WATCH"
        reason = "problem_recurrence_unproven"

    previous = case.system_verdict
    case.system_verdict = verdict
    case.current_gate = (
        "MARKET_REALITY" if verdict == "INVESTIGATE" else "PROBLEM_REALITY"
    )
    case.verdict_reason_code = reason
    case.last_evaluated_at = datetime.now()

    latest = await _one_or_none(
        session,
        select(RadarDecisionEvent)
        .where(RadarDecisionEvent.case_id == case.id)
        .order_by(RadarDecisionEvent.id.desc())
        .limit(1),
    )
    if latest is None or latest.new_verdict != verdict or latest.reason_code != reason:
        session.add(RadarDecisionEvent(
            case_id=case.id,
            previous_verdict=previous,
            new_verdict=verdict,
            reason_code=reason,
            reason_text=(
                "Production same-problem pipeline updated C02 from validated direct-problem evidence."
            ),
            triggering_claim_code="C02",
            engine_version=ENGINE_VERSION,
            decision_snapshot={
                "C02": state,
                **es,
            },
        ))

    return state, verdict, es



# ---------------------------------------------------------------------------
# Production semantic + structural verifier
# ---------------------------------------------------------------------------

SEMANTIC_RETRIEVAL_VERSION = "lsa-field-v1"
STRUCTURAL_VERIFIER_VERSION = "strict-field-v2"
AI_ADJUDICATOR_VERSION = "same-problem-v1"
MAX_AI_CALLS_PER_RUN = 4
ESTIMATED_AI_CALL_TWD = 0.02
USD_TWD_RATE = float(os.getenv("USD_TWD_RATE", "31.83"))

ANCHOR_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_+.#:/-]{1,}")

# Broad words are useful for language understanding but too weak to establish
# same-problem identity.
ANCHOR_GENERIC = {
    "about","after","again","also","and","application","applications",
    "because","before","being","between","both","build","building",
    "business","businesses","cannot","code","communication","company",
    "consumer","content","could","data","development","different","does",
    "doing","effective","error","failure","for","from","good","have","having",
    "help","improve","into","issue","issues","just","lack","like","manage",
    "model","models","more","most","need","only","other","output","over",
    "people","poor","problem","problems","process","product","products",
    "project","quality","really","results","same","service","services",
    "software","some","still","support","system","systems","task","than",
    "that","their","them","then","there","these","they","thing","things",
    "this","those","through","tool","tools","under","user","users","using",
    "very","want","what","when","where","which","while","with","without",
    "work","workflow","works","working","would",
    # topic words that are too broad to prove object identity
    "gpu","gpus","api","sdk","llm","ai","agent","server","setup","install",
    "installation","performance","memory","context",
}

STRICT_FAILURE_PATTERNS = {
    "physical_constraint": [
        r"\bspace constraint", r"\bdoesn.?t fit\b", r"\bwon.?t fit\b",
        r"\binstallation space", r"\bform factor\b", r"\bclearance\b",
        r"\bslot spacing\b",
    ],
    "resource_capacity": [
        r"\bvram\b", r"\bout of memory\b", r"\boom\b",
        r"\bmemory limit", r"\bparameter load", r"\bresource limit",
        r"\bmemory issue",
    ],
    "rate_limit": [
        r"\brate limit", r"\b429\b", r"\bquota\b", r"\bthrottl",
    ],
    "memory_context": [
        r"\bforget", r"\bloses? context\b", r"\bcontext loss\b",
        r"\bprevious instructions?\b", r"\bretain(?:ing)? context\b",
        r"\bmemory loss\b",
    ],
    "privacy_control": [
        r"\bpersonal data\b", r"\bthird[- ]party analytics\b",
        r"\btracking\b", r"\bprivacy\b", r"\bdata control\b",
    ],
    "consumer_lockin": [
        r"\block[- ]?in\b", r"\banti[- ]consumer\b", r"\bdark pattern",
        r"\bsubscription trap", r"\bforced subscription",
    ],
    "permission_security": [
        r"\bpermission", r"\bauthoriz", r"\bauthenticat",
        r"\baccess denied", r"\bsandbox\b", r"\bcredential",
    ],
    "multimodal": [
        r"\bmultimodal", r"\bmulti-modal", r"\bvision\b",
        r"\bimage input", r"\baudio input",
    ],
    "reliability": [
        r"\bunreliab", r"\binconsisten", r"\bflaky\b", r"\bunstable\b",
        r"\bintermittent", r"\brandom(?:ly)?\b",
    ],
    "quality": [
        r"\bwrong\b", r"\bincorrect\b", r"\binaccurate\b", r"\bhallucinat",
        r"\bincoherent\b", r"\bpoor quality\b", r"\bquality degrad",
        r"\bregression\b",
    ],
    "performance": [
        r"\bslow\b", r"\blatency\b", r"\bthroughput\b", r"\btokens?/s\b",
        r"\bt/s\b", r"\bperformance degrad", r"\boverload",
    ],
    "deployment_setup": [
        r"\bsetup\b", r"\binstall", r"\bconfigur", r"\bdeploy",
        r"\benvironment\b", r"\bserver instance\b", r"\bconnection\b",
        r"\bintegration\b",
    ],
    "runtime_error": [
        r"\bruntime error", r"\bexception\b", r"\bcrash", r"\btimeout\b",
        r"\bdisconnect", r"\bfails? at runtime\b",
    ],
    "workflow_integration": [
        r"\bworkflow\b.*\bintegrat", r"\bintegrat.*\bworkflow\b",
        r"\bmanual workaround", r"\bdoesn.?t fit.*workflow",
    ],
    "usability": [
        r"\bunusable\b", r"\brough edges?\b", r"\bhard to use\b",
        r"\bdifficult to use\b",
    ],
    "communication": [
        r"\bcommunication channel", r"\bcoordination\b",
        r"\bmisunderstand", r"\bmissed information\b", r"\bcollaboration\b",
    ],
}

SPECIFIC_FAILURES = {
    "physical_constraint",
    "resource_capacity",
    "rate_limit",
    "memory_context",
    "privacy_control",
    "consumer_lockin",
    "permission_security",
    "multimodal",
}

NOISE_PATTERNS = [
    r"\bperformance marketing company\b",
    r"\bdigital marketing company\b",
    r"\bhelps businesses make smarter\b",
    r"\bbest .* company in\b",
    r"\bcontact us\b",
    r"\bseo services\b",
    r"@article\s*\{",
    r"\bbibliography\b",
    r"\bcitation[s]?\b.*\bdoi\b",
]


def _structured_fields(candidate: ProblemCandidate) -> dict[str, str]:
    return {
        "actor": str(candidate.actor or ""),
        "task": str(candidate.task or ""),
        "object": str(candidate.object or ""),
        "failure": str(candidate.failure_mode or ""),
        "consequence": str(candidate.consequence or ""),
        "buyer": str(candidate.buyer_context or ""),
    }


def _anchor_tokens(text: str) -> set[str]:
    out = set()
    for raw in ANCHOR_TOKEN_RE.findall(text or ""):
        token = raw.lower().strip("._-/:")
        if len(token) < 3 or token in ANCHOR_GENERIC:
            continue
        out.add(token)
    return out


def _raw_anchor_tokens(text: str) -> list[str]:
    return ANCHOR_TOKEN_RE.findall(text or "")


def _failure_signature(text: str) -> set[str]:
    low = str(text or "").lower()
    labels = {
        label
        for label, patterns in STRICT_FAILURE_PATTERNS.items()
        if any(re.search(pattern, low, re.I) for pattern in patterns)
    }
    specific = labels & SPECIFIC_FAILURES
    if specific:
        # Specific mechanisms dominate generic deployment/reliability language.
        return specific
    return labels


def _is_noise_payload(text: str) -> bool:
    return any(re.search(p, text or "", re.I) for p in NOISE_PATTERNS)


def _field_query(candidate: ProblemCandidate) -> str:
    f = _structured_fields(candidate)
    chunks: list[str] = []
    for key, weight in (
        ("object", 5),
        ("failure", 5),
        ("task", 3),
        ("consequence", 2),
        ("actor", 1),
        ("buyer", 1),
    ):
        if f[key].strip():
            chunks.extend([f[key]] * weight)
    # Title/problem statement help semantic recall but never become structural
    # anchors by themselves.
    chunks.extend([
        str(candidate.title or ""),
        str(candidate.problem_statement or ""),
    ])
    return " ".join(chunks)[:6000]


def _named_anchor(raw: str, corpus_df: Counter, total_docs: int) -> bool:
    token = raw.strip(".,;:()[]{}")
    low = token.lower().strip("._-/:")
    if len(low) < 3 or low in ANCHOR_GENERIC:
        return False
    if any(ch.isdigit() for ch in token):
        return True
    if any(ch in token for ch in ".+/#_-"):
        return True
    if re.search(r"[a-z][A-Z]|[A-Z][a-z]+[A-Z]", token):
        return True
    if token.isupper() and len(token) >= 4:
        return True
    # Rare structured-field tokens are allowed only when genuinely uncommon.
    return len(low) >= 6 and corpus_df.get(low, 0) <= max(2, int(total_docs * 0.004))


def _semantic_structural_detail(
    *,
    candidate: ProblemCandidate,
    abstract: str,
    exemplar: str,
    doc: dict[str, Any],
    semantic_score: float,
    corpus_df: Counter,
    total_docs: int,
) -> tuple[str, dict[str, Any]]:
    if _is_noise_payload(doc["text"]):
        return "REJECT", {
            "semantic_score": round(float(semantic_score), 4),
            "reason": "noise_or_payload",
        }

    fields = _structured_fields(candidate)
    structured_raw = " ".join(fields.values())
    doc_tokens = _anchor_tokens(doc["text"])

    object_terms = _anchor_tokens(fields["object"])
    task_terms = _anchor_tokens(fields["task"])
    structured_terms = _anchor_tokens(structured_raw)

    named_candidates = {
        raw.lower().strip("._-/:")
        for raw in _raw_anchor_tokens(structured_raw)
        if _named_anchor(raw, corpus_df, total_docs)
    }

    rare_structured = {
        t
        for t in structured_terms
        if (
            math.log((1 + total_docs) / (1 + corpus_df.get(t, 0))) + 1.0
        ) >= 4.2
    }

    candidate_failure_text = " ".join([
        fields["failure"],
        str(candidate.title or ""),
        str(candidate.problem_statement or ""),
        exemplar,
    ])
    cand_failure = _failure_signature(candidate_failure_text)
    doc_failure = _failure_signature(doc["text"])

    named_shared = sorted(named_candidates & doc_tokens)
    object_shared = sorted(object_terms & doc_tokens)
    task_shared = sorted(task_terms & doc_tokens)
    rare_shared = sorted(rare_structured & doc_tokens)
    failure_shared = sorted(cand_failure & doc_failure)

    named_ok = bool(named_shared)
    object_ok = bool(object_shared)
    task_ok = bool(task_shared)
    rare_ok = bool(rare_shared)
    failure_ok = bool(failure_shared)

    dimensions = sum([named_ok, object_ok, task_ok, rare_ok, failure_ok])
    identity_ok = named_ok or object_ok or len(rare_shared) >= 2

    # Semantic similarity only generates a candidate. It never passes alone.
    if (
        semantic_score >= 0.40
        and failure_ok
        and identity_ok
        and dimensions >= 3
    ):
        tier = "STRICT_LOCAL_CANDIDATE"
    elif (
        semantic_score >= 0.38
        and dimensions >= 3
        and (failure_ok or (named_ok and rare_ok))
    ):
        tier = "STRICT_REVIEW_CANDIDATE"
    else:
        tier = "REJECT"

    return tier, {
        "semantic_score": round(float(semantic_score), 4),
        "dimensions": dimensions,
        "named_shared": named_shared[:15],
        "object_shared": object_shared[:15],
        "task_shared": task_shared[:15],
        "rare_structured_shared": rare_shared[:15],
        "candidate_failure_labels": sorted(cand_failure),
        "document_failure_labels": sorted(doc_failure),
        "failure_shared": failure_shared,
        "semantic_retrieval_version": SEMANTIC_RETRIEVAL_VERSION,
        "structural_verifier_version": STRUCTURAL_VERIFIER_VERSION,
    }


def _pair_cache_key(
    case: RadarCase,
    candidate: ProblemCandidate,
    doc: dict[str, Any],
) -> str:
    candidate_blob = json.dumps(
        {
            "title": candidate.title,
            "problem_statement": candidate.problem_statement,
            **_structured_fields(candidate),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    payload = "|".join([
        AI_ADJUDICATOR_VERSION,
        str(case.id),
        str(doc["family"]),
        str(doc["source_ref"]),
        content_hash(candidate_blob),
        content_hash(doc["text"]),
    ])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def _canonical_family_key(value: str) -> str:
    raw = str(value or "")
    if len(raw) <= 240:
        return raw
    return f"family:{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:48]}"


AI_SYSTEM_MESSAGE = """You are a skeptical evidence adjudicator.

Your ONLY task is to decide whether CASE A and EVIDENCE B describe the SAME
concrete recurring user problem.

False positives are much more costly than false negatives.

SAME_PROBLEM requires all four:
1. substantially the same user goal/task;
2. the same concrete failure or obstacle mechanism;
3. compatible object/system scope;
4. compatible practical consequence.

Shared topic, technology, product category, or vocabulary is not enough.
Examples that must be DIFFERENT_PROBLEM:
- physical GPU clearance vs VRAM/software configuration;
- two unrelated failures involving the same model;
- communication research vs a broken communication workflow;
- generic marketing text vs anti-consumer product behavior.

Use only supplied text. Do not use outside facts. Do not fill missing evidence.
When either side is too thin, choose INSUFFICIENT.

Return valid JSON only."""


def _ai_pair_prompt(candidate: ProblemCandidate, pair: dict[str, Any]) -> str:
    case_payload = {
        "title": candidate.title,
        "problem_statement": candidate.problem_statement,
        "fingerprint": _structured_fields(candidate),
    }
    evidence_payload = {
        "source_type": pair["doc"]["source_type"],
        "title": pair["doc"]["title"],
        "excerpt": pair["doc"]["text"][:1600],
        "semantic_score": pair["detail"]["semantic_score"],
        "structural_tier": pair["tier"],
        "named_shared": pair["detail"].get("named_shared", []),
        "object_shared": pair["detail"].get("object_shared", []),
        "task_shared": pair["detail"].get("task_shared", []),
        "failure_shared": pair["detail"].get("failure_shared", []),
    }
    return f"""Compare CASE A with EVIDENCE B.

CASE A:
{json.dumps(case_payload, ensure_ascii=False, indent=2)}

EVIDENCE B:
{json.dumps(evidence_payload, ensure_ascii=False, indent=2)}

Return exactly:
{{
  "verdict": "SAME_PROBLEM | DIFFERENT_PROBLEM | INSUFFICIENT",
  "task_match": "YES | NO | UNCLEAR",
  "failure_match": "YES | NO | UNCLEAR",
  "object_scope_match": "YES | NO | UNCLEAR",
  "consequence_match": "YES | NO | UNCLEAR",
  "critical_difference": "short concrete difference, or empty string",
  "reason": "1-3 skeptical sentences using only supplied evidence"
}}

SAME_PROBLEM is valid only when task_match, failure_match,
object_scope_match, and consequence_match are all YES.
"""


def _validate_ai_result(obj: Any) -> tuple[bool, str]:
    if not isinstance(obj, dict):
        return False, "not_object"
    if obj.get("verdict") not in {
        "SAME_PROBLEM", "DIFFERENT_PROBLEM", "INSUFFICIENT"
    }:
        return False, "bad_verdict"
    for key in (
        "task_match", "failure_match", "object_scope_match",
        "consequence_match",
    ):
        if obj.get(key) not in {"YES", "NO", "UNCLEAR"}:
            return False, f"bad_{key}"
    if obj.get("verdict") == "SAME_PROBLEM":
        for key in (
            "task_match", "failure_match", "object_scope_match",
            "consequence_match",
        ):
            if obj.get(key) != "YES":
                return False, "same_problem_missing_required_yes"
    return True, "OK"


def _seed_evidence(ev: RadarEvidence) -> bool:
    key = str(ev.evidence_key or "")
    return not key.startswith((
        "recurrence:",
        "recurrence_multi:",
        "recurrence_prod:",
    ))


async def _ensure_support_evidence(
    session,
    *,
    case: RadarCase,
    claim: RadarClaim,
    doc: dict[str, Any],
    method: str,
    detail: dict[str, Any],
    now: datetime,
    ai_result: dict[str, Any] | None = None,
) -> tuple[bool, bool]:
    """Create/reuse original-source evidence and a validated SUPPORT link."""
    ev_key = (
        f"recurrence_prod:{case.id}:"
        f"{content_hash(doc['family'], doc['source_ref'])[:28]}"
    )
    ev = await _one_or_none(
        session,
        select(RadarEvidence).where(RadarEvidence.evidence_key == ev_key),
    )
    created_evidence = False
    if ev is None:
        published = doc.get("published_at")
        ev = RadarEvidence(
            case_id=case.id,
            candidate_evidence_id=None,
            evidence_key=ev_key,
            source_type=doc["source_type"],
            source_table=doc["source_table"],
            source_ref=str(doc["source_ref"]),
            source_url=normalize_url(doc.get("url")) or None,
            source_title=doc.get("title") or None,
            excerpt=str(doc.get("text") or "")[:1200],
            source_family_key=doc["family"],
            directness="DIRECT",
            authority_class=doc.get("authority_class", "UNKNOWN"),
            published_at=published,
            observed_at=now,
            freshness_class="UNASSESSED",
            content_hash=content_hash(doc.get("text")),
            raw_metadata={
                "engine_version": ENGINE_VERSION,
                "verification_method": method,
                "retrieval_detail": detail,
                "ai_adjudication": ai_result,
            },
        )
        session.add(ev)
        await session.flush()
        created_evidence = True

    link = await _one_or_none(
        session,
        select(RadarClaimEvidence).where(
            RadarClaimEvidence.claim_id == claim.id,
            RadarClaimEvidence.evidence_id == ev.id,
        ),
    )
    created_link = False
    if link is None:
        link = RadarClaimEvidence(
            claim_id=claim.id,
            evidence_id=ev.id,
            stance="SUPPORT",
            interpretation_method=method,
            method_version=ENGINE_VERSION,
            interpretation_confidence=(
                float(detail.get("hybrid_combined"))
                if method == "DETERMINISTIC_STRICT_LEXICAL"
                and detail.get("hybrid_combined") is not None
                else None
            ),
            rationale=(
                "Independent source passed unchanged strict deterministic "
                "lexical recurrence gates."
                if method == "DETERMINISTIC_STRICT_LEXICAL"
                else
                "Independent source was retrieved semantically, survived "
                "strict structural pruning, then SAME_PROBLEM was accepted "
                "only after deterministic validation of the narrow AI schema."
            ),
            validated=True,
        )
        session.add(link)
        created_link = True
    return created_evidence, created_link


async def run_problem_recurrence_multi(
    *,
    ai_call_allowance: int | None = None,
    case_ids: list[int] | None = None,
) -> dict[str, Any]:
    now = datetime.now()
    summary = Counter()
    total_usage = TokenUsage()
    ai_cap = (
        MAX_AI_CALLS_PER_RUN
        if ai_call_allowance is None
        else max(0, min(MAX_AI_CALLS_PER_RUN, int(ai_call_allowance)))
    )

    async with async_session() as session:
        hn_reddit_docs, raw_post_rows = await _build_hn_reddit(session)
        so_docs, so_rows = await _build_stackoverflow(session)
        github_issue_docs, github_issue_rows = await _build_github_issues(session)
        external_docs, external_rows = await _build_external_problem_items(session)

        docs = hn_reddit_docs + so_docs + github_issue_docs + external_docs
        for doc in docs:
            doc["family"] = _canonical_family_key(doc["family"])

        # Reuse the exact direct-problem corpus later in this same process for
        # C03 materiality mining instead of rebuilding four source families.
        global LAST_DIRECT_DOCS, LAST_DIRECT_CORPUS_COUNTS
        LAST_DIRECT_DOCS = docs
        LAST_DIRECT_CORPUS_COUNTS = {
            "hn_reddit": len(hn_reddit_docs),
            "stackoverflow": len(so_docs),
            "github_issues": len(github_issue_docs),
            "external": len(external_docs),
        }

        runtime_progress.heartbeat(
            detail="c02 direct-problem corpus loaded",
            progress={
                "documents": len(docs),
                "source_counts": dict(LAST_DIRECT_CORPUS_COUNTS),
            },
        )

        case_stmt = (
            select(RadarCase, ProblemCandidate)
            .join(ProblemCandidate, ProblemCandidate.id == RadarCase.candidate_id)
            .order_by(RadarCase.id)
        )
        if case_ids is not None:
            wanted_case_ids = sorted({int(x) for x in case_ids if int(x) > 0})
            if wanted_case_ids:
                case_stmt = case_stmt.where(RadarCase.id.in_(wanted_case_ids))
            else:
                case_stmt = case_stmt.where(RadarCase.id == -1)
        cases = list((await session.execute(case_stmt)).all())

        runtime_progress.heartbeat(
            detail="c02 bounded case set loaded",
            progress={"cases": len(cases), "documents": len(docs)},
        )

        if not cases or not docs:
            print("No cases or direct-problem documents available.")
            return {
                "engine_version": ENGINE_VERSION,
                "cases": len(cases),
                "documents": len(docs),
                "llm_calls": 0,
                "llm_cost_twd": 0.0,
            }

        coverage = await coverage_snapshot(cases)
        coverage_by_case = {
            row["case_id"]: row for row in coverage["cases"]
        }

        # Seed exemplars must not absorb recurrence evidence from prior runs.
        all_direct_evidence = list((await session.execute(
            select(RadarEvidence)
            .where(RadarEvidence.directness == "DIRECT")
            .order_by(RadarEvidence.id)
        )).scalars().all())

        seed_by_case: dict[int, list[RadarEvidence]] = defaultdict(list)
        excluded_families_by_case: dict[int, set[str]] = defaultdict(set)
        for ev in all_direct_evidence:
            excluded_families_by_case[ev.case_id].add(ev.source_family_key)
            if (
                ev.authority_class == "USER_DISCUSSION"
                and _seed_evidence(ev)
            ):
                seed_by_case[ev.case_id].append(ev)

        abstracts: list[str] = []
        exemplars: list[str] = []
        field_queries: list[str] = []
        for case, candidate in cases:
            a, e = _representations(
                case,
                candidate,
                seed_by_case.get(case.id, []),
            )
            abstracts.append(a)
            exemplars.append(e or a)
            field_queries.append(_field_query(candidate))

        n = len(cases)
        doc_texts = [d["text"] for d in docs]

        # ------------------------------------------------------------------
        # Stage 1/2: exact retrieval cache. The cache key covers every query
        # representation and every document text, so a hit reuses the exact
        # matrices produced by the unchanged R2 truth/retrieval algorithm.
        # Cache misses execute the original vectorizers/SVD verbatim.
        # ------------------------------------------------------------------
        retrieval_cache_key = _c02_retrieval_cache_key(
            abstracts=abstracts,
            exemplars=exemplars,
            field_queries=field_queries,
            doc_texts=doc_texts,
        )
        cached_matrices = _load_c02_retrieval_cache(retrieval_cache_key, n=n, docs=len(docs))
        retrieval_cache_hit = cached_matrices is not None

        if cached_matrices is not None:
            a_word = cached_matrices["a_word"]
            e_word = cached_matrices["e_word"]
            a_char = cached_matrices["a_char"]
            e_char = cached_matrices["e_char"]
            semantic = cached_matrices["semantic"]
            runtime_progress.heartbeat(
                detail="c02 exact retrieval cache hit",
                progress={
                    "cases": n,
                    "documents": len(docs),
                    "stage": "retrieval_cache_hit",
                    "cache_key": retrieval_cache_key,
                },
            )
        else:
            lexical_corpus = abstracts + exemplars + doc_texts
            lexical_doc_start = 2 * n

            word_vec = TfidfVectorizer(
                stop_words="english",
                ngram_range=(1, 2),
                min_df=1,
                max_df=0.92,
                sublinear_tf=True,
                max_features=26000,
                token_pattern=r"(?u)\b[a-zA-Z][a-zA-Z0-9_+#.-]{1,}\b",
            )
            Xw = word_vec.fit_transform(lexical_corpus)

            char_vec = TfidfVectorizer(
                analyzer="char_wb",
                ngram_range=(3, 5),
                min_df=2,
                max_features=32000,
                sublinear_tf=True,
            )
            Xc = char_vec.fit_transform(lexical_corpus)

            a_word = cosine_similarity(Xw[:n], Xw[lexical_doc_start:])
            e_word = cosine_similarity(Xw[n:2*n], Xw[lexical_doc_start:])
            a_char = cosine_similarity(Xc[:n], Xc[lexical_doc_start:])
            e_char = cosine_similarity(Xc[n:2*n], Xc[lexical_doc_start:])
            runtime_progress.heartbeat(
                detail="c02 lexical retrieval matrix ready",
                progress={"cases": n, "documents": len(docs), "stage": "lexical_ready"},
            )

            semantic_corpus = abstracts + exemplars + field_queries + doc_texts
            semantic_vec = TfidfVectorizer(
                stop_words="english",
                ngram_range=(1, 2),
                min_df=1,
                max_df=0.96,
                sublinear_tf=True,
                max_features=50000,
                token_pattern=r"(?u)\b[a-zA-Z][a-zA-Z0-9_+#./:-]{1,}\b",
            )
            Xs = semantic_vec.fit_transform(semantic_corpus)

            semantic_components = min(
                180,
                max(2, Xs.shape[0] - 1),
                max(2, Xs.shape[1] - 1),
            )
            svd = TruncatedSVD(
                n_components=semantic_components,
                algorithm="randomized",
                n_iter=8,
                random_state=42,
            )
            Z = normalize(svd.fit_transform(Xs))

            semantic_doc_start = 3 * n
            sem_a = cosine_similarity(Z[:n], Z[semantic_doc_start:])
            sem_e = cosine_similarity(Z[n:2*n], Z[semantic_doc_start:])
            sem_f = cosine_similarity(Z[2*n:3*n], Z[semantic_doc_start:])
            semantic = np.maximum.reduce([sem_a, sem_e, sem_f])
            runtime_progress.heartbeat(
                detail="c02 semantic recall matrix ready",
                progress={"cases": n, "documents": len(docs), "stage": "semantic_ready"},
            )
            _save_c02_retrieval_cache(
                retrieval_cache_key,
                {
                    "a_word": a_word,
                    "e_word": e_word,
                    "a_char": a_char,
                    "e_char": e_char,
                    "semantic": semantic,
                },
            )

        a_comb = 0.68 * a_word + 0.32 * a_char
        e_comb = 0.68 * e_word + 0.32 * e_char
        hybrid = np.maximum(a_comb, e_comb)

        corpus_df = Counter()
        for text in doc_texts:
            corpus_df.update(_anchor_tokens(text))

        state_by_case: dict[int, dict[str, Any]] = {}
        ai_queue: list[dict[str, Any]] = []

        # First pass writes only unchanged deterministic STRONG matches.
        for i, (case, candidate) in enumerate(cases):
            if i == 0 or (i + 1) % 4 == 0 or (i + 1) == len(cases):
                runtime_progress.heartbeat(
                    detail="c02 deterministic verification",
                    progress={
                        "cases_completed": i,
                        "cases_total": len(cases),
                        "documents": len(docs),
                    },
                )
            c02 = await _one_or_none(
                session,
                select(RadarClaim).where(
                    RadarClaim.case_id == case.id,
                    RadarClaim.claim_code == "C02",
                ),
            )
            unknown = await _one_or_none(
                session,
                select(RadarUnknown).where(
                    RadarUnknown.case_id == case.id,
                    RadarUnknown.unknown_code == "U_C02",
                ),
            )
            if c02 is None or unknown is None:
                summary["missing_c02_or_unknown"] += 1
                continue

            action_key = (
                f"{case.case_key}:U_C02:production_same_problem:v1"
            )
            action = await _one_or_none(
                session,
                select(RadarResearchAction).where(
                    RadarResearchAction.action_key == action_key
                ),
            )
            if action is None:
                action = RadarResearchAction(
                    case_id=case.id,
                    unknown_id=unknown.id,
                    action_key=action_key,
                    claim_code="C02",
                    action_type="RESEARCH",
                    method="production_same_problem_verification",
                    status="PLANNED",
                    priority_score=float(unknown.priority_score or 0.81),
                    decision_impact=float(unknown.decision_impact or 1.0),
                    reducibility=float(unknown.reducibility or 0.9),
                    answerability=float(unknown.answerability or 0.9),
                    urgency=float(unknown.urgency or 1.0),
                    coverage_gap=float(unknown.coverage_gap or 1.0),
                    estimated_cost_twd=0.0,
                    estimated_llm_cost_twd=0.0,
                    ai_allowed=False,
                    ai_task_name="same_problem_verify",
                    ai_gate_reason="DENY_UNTIL_LOCAL_PIPELINE_RUNS",
                    attempt_count=0,
                    max_attempts=999,
                    plan_metadata={
                        "engine_version": ENGINE_VERSION,
                        "pipeline": [
                            "strict_lexical",
                            "semantic_retrieval",
                            "strict_structural_verifier",
                            "narrow_ai_adjudication",
                        ],
                        "max_ai_calls_per_run": MAX_AI_CALLS_PER_RUN,
                    },
                )
                session.add(action)
                await session.flush()
                summary["actions_created"] += 1
            else:
                summary["actions_reused"] += 1

            old_result = (
                dict(action.result_metadata)
                if isinstance(action.result_metadata, dict)
                else {}
            )
            pair_cache = (
                dict(old_result.get("ai_pair_cache", {}))
                if isinstance(old_result.get("ai_pair_cache"), dict)
                else {}
            )

            excluded = excluded_families_by_case.get(case.id, set())

            strong_hits: list[dict[str, Any]] = []
            legacy_ambiguous_hits: list[dict[str, Any]] = []
            for j in _balanced_ranked_indices(
                hybrid[i], docs, total_limit=50, global_keep=24, per_source_supplement=10
            ):
                doc = docs[int(j)]
                if doc["family"] in excluded:
                    continue
                verdict, detail = _match_detail(
                    abstracts[i],
                    exemplars[i],
                    doc["text"],
                    float(a_word[i, j]),
                    float(e_word[i, j]),
                    float(a_char[i, j]),
                    float(e_char[i, j]),
                )
                if verdict == "REJECT":
                    continue

                hit = {
                    "doc": doc,
                    "detail": detail,
                }
                if verdict == "STRONG":
                    strong_hits.append(hit)
                else:
                    legacy_ambiguous_hits.append(hit)

                if len(strong_hits) >= 2 and len(legacy_ambiguous_hits) >= 5:
                    break

            for hit in strong_hits[:2]:
                created_ev, created_link = await _ensure_support_evidence(
                    session,
                    case=case,
                    claim=c02,
                    doc=hit["doc"],
                    method="DETERMINISTIC_STRICT_LEXICAL",
                    detail=hit["detail"],
                    now=now,
                )
                summary["lexical_support_evidence_created"] += int(created_ev)
                summary["lexical_support_links_created"] += int(created_link)
                if created_ev:
                    summary[
                        f"lexical_source_{hit['doc']['source_type']}"
                    ] += 1

            await session.flush()
            c02_state, verdict, evidence_summary = await _recompute_case(
                session,
                case,
                c02,
                unknown,
            )

            semantic_candidates: list[dict[str, Any]] = []
            if c02_state != "SUPPORTED":
                for j in _balanced_ranked_indices(
                    semantic[i], docs, total_limit=35, global_keep=16, per_source_supplement=7
                ):
                    doc = docs[int(j)]
                    if doc["family"] in excluded:
                        continue
                    sem_score = float(semantic[i, j])
                    if sem_score < 0.32:
                        break

                    tier, detail = _semantic_structural_detail(
                        candidate=candidate,
                        abstract=abstracts[i],
                        exemplar=exemplars[i],
                        doc=doc,
                        semantic_score=sem_score,
                        corpus_df=corpus_df,
                        total_docs=len(docs),
                    )
                    if tier == "REJECT":
                        if sem_score >= 0.40:
                            summary["semantic_high_rejected"] += 1
                        continue

                    pair = {
                        "case": case,
                        "candidate": candidate,
                        "c02": c02,
                        "unknown": unknown,
                        "action": action,
                        "tier": tier,
                        "doc": doc,
                        "detail": detail,
                        "pair_key": _pair_cache_key(case, candidate, doc),
                    }
                    semantic_candidates.append(pair)
                    summary[
                        "semantic_strict_candidates"
                        if tier == "STRICT_LOCAL_CANDIDATE"
                        else "semantic_review_candidates"
                    ] += 1

                    if len(semantic_candidates) >= 3:
                        break

                semantic_candidates.sort(
                    key=lambda p: (
                        1 if p["tier"] == "STRICT_LOCAL_CANDIDATE" else 0,
                        p["detail"]["semantic_score"],
                    ),
                    reverse=True,
                )

            state_by_case[case.id] = {
                "case": case,
                "candidate": candidate,
                "c02": c02,
                "unknown": unknown,
                "action": action,
                "pair_cache": pair_cache,
                "strong_hits": strong_hits[:5],
                "legacy_ambiguous_hits": legacy_ambiguous_hits[:5],
                "semantic_candidates": semantic_candidates[:5],
                "coverage": coverage_by_case.get(case.id, {
                    "level": "GAP",
                    "coverage_ratio": 0.0,
                    "successful_families": [],
                    "missing_families": [],
                    "error_or_rate_limited_families": [],
                }),
                "pre_ai_state": c02_state,
                "pre_ai_verdict": verdict,
                "pre_ai_evidence_summary": evidence_summary,
                "ai_results": [],
            }

        # Reuse valid cached adjudications first. For each unresolved case,
        # only the highest-priority *uncached* pair may request a new AI call
        # this run. This lets later pairs advance on future runs without
        # repeatedly paying for the first one.
        for case_id, state in state_by_case.items():
            if state["pre_ai_state"] == "SUPPORTED":
                continue

            cached_same = False
            for pair in state["semantic_candidates"]:
                cached = state["pair_cache"].get(pair["pair_key"])
                if not isinstance(cached, dict) or cached.get("validation") != "OK":
                    continue
                result = cached.get("result")
                valid, validation = _validate_ai_result(result)
                if not valid:
                    continue

                summary["ai_cache_hits"] += 1
                state["ai_results"].append({
                    "pair_key": pair["pair_key"],
                    "source_type": pair["doc"]["source_type"],
                    "source_ref": pair["doc"]["source_ref"],
                    "tier": pair["tier"],
                    "semantic_score": pair["detail"]["semantic_score"],
                    "status": "CACHE_HIT",
                    "result": result,
                })

                if result.get("verdict") == "SAME_PROBLEM":
                    created_ev, created_link = await _ensure_support_evidence(
                        session,
                        case=state["case"],
                        claim=state["c02"],
                        doc=pair["doc"],
                        method="AI_ADJUDICATED_SAME_PROBLEM",
                        detail=pair["detail"],
                        now=now,
                        ai_result=result,
                    )
                    summary["ai_support_evidence_created"] += int(created_ev)
                    summary["ai_support_links_created"] += int(created_link)
                    cached_same = True
                    break

            if cached_same:
                continue

            for pair in state["semantic_candidates"]:
                if pair["pair_key"] not in state["pair_cache"]:
                    ai_queue.append(pair)
                    break

        # ------------------------------------------------------------------
        runtime_progress.heartbeat(
            detail="c02 deterministic pruning complete",
            progress={
                "cases_total": len(cases),
                "ai_queue": len(ai_queue),
                "semantic_strict": int(summary["semantic_strict_candidates"]),
                "semantic_review": int(summary["semantic_review_candidates"]),
            },
        )

        # Stage 3: narrow AI adjudication, globally capped.
        # Cached pair results are reused at zero cost.
        # ------------------------------------------------------------------
        ai_queue.sort(
            key=lambda p: (
                1 if p["tier"] == "STRICT_LOCAL_CANDIDATE" else 0,
                p["detail"]["semantic_score"],
            ),
            reverse=True,
        )

        ai_invocations = 0
        for pair in ai_queue:
            case = pair["case"]
            candidate = pair["candidate"]
            state = state_by_case[case.id]
            cache = state["pair_cache"]
            pair_key = pair["pair_key"]

            if ai_invocations >= ai_cap:
                summary["ai_deferred_global_cap"] += 1
                state["ai_results"].append({
                    "pair_key": pair_key,
                    "source_type": pair["doc"]["source_type"],
                    "source_ref": pair["doc"]["source_ref"],
                    "tier": pair["tier"],
                    "semantic_score": pair["detail"]["semantic_score"],
                    "status": "DEFERRED_GLOBAL_CAP",
                })
                continue

            budget = await _one_or_none(
                session,
                select(RadarAIBudgetLedger)
                .where(RadarAIBudgetLedger.case_id == case.id)
                .order_by(RadarAIBudgetLedger.id.desc())
                .limit(1),
            )
            remaining = 0.0
            if budget is not None:
                remaining = max(
                    0.0,
                    float(budget.budget_cap_twd or 0)
                    - float(budget.spent_twd or 0)
                    - float(budget.reserved_twd or 0),
                )

            gate = evaluate_ai_gate(
                task_name="same_problem_verify",
                local_attempted=True,
                local_result="AMBIGUOUS",
                estimated_call_cost_twd=ESTIMATED_AI_CALL_TWD,
                remaining_case_budget_twd=remaining,
                decision_impact=float(pair["action"].decision_impact or 1.0),
            )

            if not gate.allowed:
                summary["ai_gate_denied"] += 1
                state["ai_results"].append({
                    "pair_key": pair_key,
                    "source_type": pair["doc"]["source_type"],
                    "source_ref": pair["doc"]["source_ref"],
                    "tier": pair["tier"],
                    "semantic_score": pair["detail"]["semantic_score"],
                    "status": "GATE_DENIED",
                    "gate_reason": gate.reason,
                })
                continue

            call_usage = TokenUsage()
            ai_invocations += 1
            try:
                result = await call_llm(
                    prompt=_ai_pair_prompt(candidate, pair),
                    system_message=AI_SYSTEM_MESSAGE,
                    model="mini",
                    temperature=0.0,
                    max_tokens=450,
                    parse_json=True,
                    usage_tracker=call_usage,
                )
                total_usage.prompt_tokens += call_usage.prompt_tokens
                total_usage.completion_tokens += call_usage.completion_tokens
                total_usage.total_tokens += call_usage.total_tokens
                total_usage.calls += call_usage.calls

                valid, validation = _validate_ai_result(result)
                if not valid:
                    summary["ai_invalid_output"] += 1
                    state["ai_results"].append({
                        "pair_key": pair_key,
                        "source_type": pair["doc"]["source_type"],
                        "source_ref": pair["doc"]["source_ref"],
                        "tier": pair["tier"],
                        "semantic_score": pair["detail"]["semantic_score"],
                        "status": "INVALID_OUTPUT",
                        "validation": validation,
                        "result": result,
                    })
                    continue

                cost_twd = call_usage.estimated_cost_usd * USD_TWD_RATE
                if budget is not None:
                    budget.spent_twd = float(budget.spent_twd or 0) + cost_twd

                cache[pair_key] = {
                    "validation": "OK",
                    "adjudicator_version": AI_ADJUDICATOR_VERSION,
                    "source_family": pair["doc"]["family"],
                    "source_ref": str(pair["doc"]["source_ref"]),
                    "semantic_score": pair["detail"]["semantic_score"],
                    "result": result,
                    "cost_twd": round(cost_twd, 6),
                    "adjudicated_at": now.isoformat(),
                }
                state["pair_cache"] = cache
                state["ai_results"].append({
                    "pair_key": pair_key,
                    "source_type": pair["doc"]["source_type"],
                    "source_ref": pair["doc"]["source_ref"],
                    "tier": pair["tier"],
                    "semantic_score": pair["detail"]["semantic_score"],
                    "status": "ADJUDICATED",
                    "gate_reason": gate.reason,
                    "result": result,
                    "cost_twd": round(cost_twd, 6),
                })

                summary[f"ai_verdict_{result['verdict'].lower()}"] += 1

                if result["verdict"] == "SAME_PROBLEM":
                    created_ev, created_link = await _ensure_support_evidence(
                        session,
                        case=case,
                        claim=pair["c02"],
                        doc=pair["doc"],
                        method="AI_ADJUDICATED_SAME_PROBLEM",
                        detail=pair["detail"],
                        now=now,
                        ai_result=result,
                    )
                    summary["ai_support_evidence_created"] += int(created_ev)
                    summary["ai_support_links_created"] += int(created_link)

            except Exception as exc:
                # call_llm may have received a billable response before JSON
                # validation/parsing failed. Preserve that cost in both the
                # run total and the per-case Radar budget ledger.
                if call_usage.calls:
                    total_usage.prompt_tokens += call_usage.prompt_tokens
                    total_usage.completion_tokens += call_usage.completion_tokens
                    total_usage.total_tokens += call_usage.total_tokens
                    total_usage.calls += call_usage.calls
                    failed_cost_twd = (
                        call_usage.estimated_cost_usd * USD_TWD_RATE
                    )
                    if budget is not None:
                        budget.spent_twd = (
                            float(budget.spent_twd or 0) + failed_cost_twd
                        )
                summary["ai_errors"] += 1
                state["ai_results"].append({
                    "pair_key": pair_key,
                    "source_type": pair["doc"]["source_type"],
                    "source_ref": pair["doc"]["source_ref"],
                    "tier": pair["tier"],
                    "semantic_score": pair["detail"]["semantic_score"],
                    "status": "AI_ERROR",
                    "error": f"{type(exc).__name__}: {exc}",
                })

        # ------------------------------------------------------------------
        # Final deterministic C02 recomputation + coverage-aware research state
        # ------------------------------------------------------------------
        for case_id, state in state_by_case.items():
            case = state["case"]
            candidate = state["candidate"]
            c02 = state["c02"]
            unknown = state["unknown"]
            action = state["action"]
            cov = state["coverage"]

            await session.flush()
            c02_state, verdict, evidence_summary = await _recompute_case(
                session,
                case,
                c02,
                unknown,
            )

            summary[f"c02_{c02_state.lower()}"] += 1
            summary[f"verdict_{verdict.lower()}"] += 1

            action.attempt_count = int(action.attempt_count or 0) + 1
            action.last_attempt_at = now
            action.coverage_gap = 1.0 - float(cov.get("coverage_ratio", 0.0))
            action.estimated_cost_twd = 0.0
            action.estimated_llm_cost_twd = 0.0
            action.ai_task_name = "same_problem_verify"

            unreviewed_pair_keys = [
                p["pair_key"]
                for p in state["semantic_candidates"]
                if p["pair_key"] not in state["pair_cache"]
            ]
            unresolved_ai = bool(unreviewed_pair_keys)

            if c02_state == "SUPPORTED":
                action.status = "COMPLETED"
                action.ai_allowed = False
                action.ai_gate_reason = "DENY_C02_RESOLVED"
                summary["actions_completed"] += 1
            elif unresolved_ai:
                action.status = "AMBIGUOUS"
                last_unresolved = next(
                    (
                        row for row in reversed(state["ai_results"])
                        if row.get("status") in {
                            "DEFERRED_GLOBAL_CAP",
                            "GATE_DENIED",
                            "AI_ERROR",
                            "INVALID_OUTPUT",
                        }
                    ),
                    None,
                )
                if last_unresolved and last_unresolved.get("status") == "GATE_DENIED":
                    action.ai_allowed = False
                    action.ai_gate_reason = str(
                        last_unresolved.get("gate_reason") or "DENY_BUDGET_OR_POLICY"
                    )
                else:
                    action.ai_allowed = True
                    action.ai_gate_reason = "NARROW_AI_PAIR_REMAINS_UNRESOLVED"
                summary["actions_ambiguous"] += 1
            elif cov.get("level") == "SATURATED":
                action.status = "SEARCH_EXHAUSTED"
                action.ai_allowed = False
                action.ai_gate_reason = (
                    "DENY_NO_REMAINING_AMBIGUOUS_PAIR_AFTER_SATURATED_SEARCH"
                )
                summary["actions_search_exhausted"] += 1
            else:
                action.status = "INSUFFICIENT"
                action.ai_allowed = False
                action.ai_gate_reason = (
                    "DENY_COVERAGE_GAP: AI cannot substitute for missing evidence"
                )
                summary["actions_coverage_gap"] += 1

            def compact_hit(hit: dict[str, Any]) -> dict[str, Any]:
                doc = hit["doc"]
                detail = hit["detail"]
                return {
                    "source_type": doc["source_type"],
                    "source_ref": str(doc["source_ref"]),
                    "source_family": doc["family"],
                    "title": str(doc.get("title") or "")[:240],
                    "detail": detail,
                }

            action.result_metadata = {
                "engine_version": ENGINE_VERSION,
                "coverage": cov,
                "strict_lexical_hits": [
                    compact_hit(x) for x in state["strong_hits"]
                ],
                "legacy_lexical_ambiguous": [
                    compact_hit(x) for x in state["legacy_ambiguous_hits"]
                ],
                "semantic_structural_candidates": [
                    {
                        "source_type": p["doc"]["source_type"],
                        "source_ref": str(p["doc"]["source_ref"]),
                        "source_family": p["doc"]["family"],
                        "title": str(p["doc"].get("title") or "")[:240],
                        "tier": p["tier"],
                        "detail": p["detail"],
                        "pair_key": p["pair_key"],
                    }
                    for p in state["semantic_candidates"]
                ],
                "ai_results_this_run": state["ai_results"],
                "ai_pair_cache": state["pair_cache"],
                "unreviewed_semantic_pair_keys": unreviewed_pair_keys,
                "c02_state_after": c02_state,
                "direct_support_groups_after": evidence_summary[
                    "direct_support_groups"
                ],
                "system_verdict_after": verdict,
            }

        await session.commit()

    total_cost_twd = total_usage.estimated_cost_usd * USD_TWD_RATE

    print()
    print("=" * 116)
    print("RADAR PRODUCTION — SAME-PROBLEM VERIFICATION")
    print("=" * 116)
    print(f"Engine:                              {ENGINE_VERSION}")
    print(f"Cases evaluated (bounded workload):  {len(cases)}")
    print(f"Total direct-problem documents:      {len(docs)}")
    print(f"  HN/Reddit discussions:             {len(hn_reddit_docs)}")
    print(f"  Stack Overflow questions:          {len(so_docs)}")
    print(f"  GitHub Issues:                     {len(github_issue_docs)}")
    print(f"  Source Network external:           {len(external_docs)}")
    print()
    print("Coverage truth:")
    for level in ("SATURATED", "PARTIAL", "LEGACY_ONLY", "GAP"):
        print(
            f"  {level:14s}: "
            f"{coverage['levels'].get(level, 0):2d}/{len(cases)}"
        )
    print()
    print("Stage 1 — unchanged strict lexical gate:")
    print(
        "  New SUPPORT evidence:              "
        f"{summary['lexical_support_evidence_created']}"
    )
    print(
        "  New SUPPORT links:                 "
        f"{summary['lexical_support_links_created']}"
    )
    print("  Acceptance thresholds changed:     NO")
    print()
    print("Stage 2 — semantic retrieval + deterministic pruning:")
    print(
        "  STRICT_LOCAL candidates:           "
        f"{summary['semantic_strict_candidates']}"
    )
    print(
        "  STRICT_REVIEW candidates:          "
        f"{summary['semantic_review_candidates']}"
    )
    print(
        "  High-semantic rejected by structure:"
        f" {summary['semantic_high_rejected']}"
    )
    print()
    print("Stage 3 — narrow AI adjudication:")
    print(f"  Max calls allowed this run:         {ai_cap}")
    print(f"  AI invocations executed:            {ai_invocations}")
    print(f"  Pair-cache hits:                    {summary['ai_cache_hits']}")
    print(
        "  SAME_PROBLEM:                      "
        f"{summary['ai_verdict_same_problem']}"
    )
    print(
        "  DIFFERENT_PROBLEM:                 "
        f"{summary['ai_verdict_different_problem']}"
    )
    print(
        "  INSUFFICIENT:                      "
        f"{summary['ai_verdict_insufficient']}"
    )
    print(
        "  Gate denied / deferred / errors:   "
        f"{summary['ai_gate_denied']} / "
        f"{summary['ai_deferred_global_cap']} / "
        f"{summary['ai_errors']}"
    )
    print(
        "  AI-validated SUPPORT evidence:     "
        f"{summary['ai_support_evidence_created']}"
    )
    print(f"  Tracked tokens:                     {total_usage.total_tokens}")
    print(f"  Billable responses tracked:         {total_usage.calls}")
    print(f"  Estimated AI cost:                  NT${total_cost_twd:.4f}")
    print()
    print("C02 after production verification:")
    for st in ("supported", "insufficient", "unknown", "refuted", "conflicted"):
        print(f"  {st:14s}: {summary[f'c02_{st}']}")
    print()
    print("System verdicts:")
    for verdict in ("investigate", "watch", "ignore"):
        print(f"  {verdict:14s}: {summary[f'verdict_{verdict}']}")
    print()
    print("Research state:")
    print(f"  COMPLETED:                          {summary['actions_completed']}")
    print(f"  SEARCH_EXHAUSTED:                   {summary['actions_search_exhausted']}")
    print(f"  COVERAGE_GAP / INSUFFICIENT:        {summary['actions_coverage_gap']}")
    print(f"  AMBIGUOUS / AI pending:             {summary['actions_ambiguous']}")
    print()
    print("Semantic similarity alone creates evidence: NO")
    print("AI can create/source missing evidence:       NO")
    print("Thresholds changed:                          NO")
    print("=" * 116)

    return {
        "engine_version": ENGINE_VERSION,
        "direct_problem_documents": len(docs),
        "direct_problem_source_counts": dict(LAST_DIRECT_CORPUS_COUNTS),
        "retrieval_portfolio_policy": "GLOBAL_TOP_PLUS_SOURCE_DIVERSITY_SUPPLEMENT_NO_THRESHOLD_CHANGE",
        "retrieval_cache": {
            "schema": C02_RETRIEVAL_CACHE_SCHEMA,
            "hit": bool(retrieval_cache_hit),
            "key": retrieval_cache_key,
            "truth_boundary": "EXACT_DERIVED_MATRIX_REUSE_ONLY_NO_THRESHOLD_OR_EVIDENCE_AUTHORITY",
        },
        "cases_evaluated": len(cases),
        "coverage_saturated": coverage["levels"].get("SATURATED", 0),
        "coverage_partial": coverage["levels"].get("PARTIAL", 0),
        "coverage_gap": coverage["levels"].get("GAP", 0),
        "lexical_support_evidence_created": summary[
            "lexical_support_evidence_created"
        ],
        "semantic_strict_candidates": summary["semantic_strict_candidates"],
        "semantic_review_candidates": summary["semantic_review_candidates"],
        "ai_cache_hits": summary["ai_cache_hits"],
        "llm_calls": ai_invocations,
        "llm_tokens": int(total_usage.total_tokens or 0),
        "llm_cost_twd": round(total_cost_twd, 6),
        "c02_supported": summary["c02_supported"],
        "c02_insufficient": summary["c02_insufficient"],
        "verdict_investigate": summary["verdict_investigate"],
        "verdict_watch": summary["verdict_watch"],
        "search_exhausted": summary["actions_search_exhausted"],
        "coverage_gap_actions": summary["actions_coverage_gap"],
    }

