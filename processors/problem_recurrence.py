
"""Radar V4.2 — Local Problem Recurrence Executor.

Goal
----
Resolve C02 (problem_recurs) as far as possible with LOCAL / DETERMINISTIC
methods before any AI call is authorized.

This processor:
1. backfills the original community occurrence as one C02 support family;
2. builds independent HN/Reddit discussions using the existing repository's
   thread/root semantics;
3. retrieves recurrence candidates with hybrid word + character TF-IDF;
4. applies strict deterministic guards for high-confidence same-problem matches;
5. writes only strong matches to the Evidence Ledger as SUPPORT;
6. stores ambiguous matches for a later narrow same_problem_verify AI fallback;
7. never calls an LLM itself.

Important:
- Related-topic similarity is NOT enough.
- One thread never counts as recurrence.
- Original and corroborating evidence must be different source families.
- No ambiguous pair is promoted automatically.
"""

from __future__ import annotations

import hashlib
import html
import math
import re
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import numpy as np
import structlog
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sqlalchemy import select

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
)
from processors.ai_budget_gate import evaluate_ai_gate

log = structlog.get_logger().bind(processor="problem_recurrence")
ENGINE_VERSION = "radar-v4.2-recurrence"

URL_RE = re.compile(r"https?://\S+|www\.\S+", re.I)
TAG_RE = re.compile(r"<[^>]+>")
CODE_RE = re.compile(r"```.*?```", re.S)
REDDIT_THREAD_RE = re.compile(r"/comments/([a-z0-9]+)/", re.I)

FRICTION_RE = re.compile(
    r"""(?ix)\b(
        frustrat\w*|broken|unusable|unreliable|inconsistent|
        regress(?:ion|ed|ing)?|struggl\w*|painful|impossible|
        can['’]?t|cannot|fails?|failing|failure|
        doesn['’]?t\s+work|does\s+not\s+work|
        won['’]?t\s+work|will\s+not\s+work|
        keeps?\s+(?:breaking|failing|ignoring|forgetting|crashing|resetting)|
        no\s+good\s+way|wish\s+there\s+was|someone\s+needs\s+to\s+build|
        why\s+is\b.{0,50}\bso\s+hard|why\s+can['’]?t|
        gave\s+up|workaround|work\s*around|
        hard\s+to\s+(?:use|debug|deploy|integrate|manage|control|configure)|
        difficult\s+to\s+(?:use|debug|deploy|integrate|manage|control|configure)
    )\b"""
)

PRODUCT_CONTEXT_RE = re.compile(
    r"""(?ix)\b(
        api|sdk|app|software|tool|product|service|platform|system|
        workflow|integration|deploy|deployment|hosting|server|database|
        model|llm|ai|agent|prompt|context|memory|rag|retrieval|embedding|
        gpu|cuda|inference|compute|developer|engineering|enterprise|
        salesforce|github|openai|claude|chatgpt|google|microsoft|
        auth|permission|security|billing|pricing|cost|latency|performance
    )\b"""
)

GENERIC_TERMS = {
    "problem","problems","issue","issues","thing","things","stuff","work","working",
    "works","using","used","user","users","need","needs","really","system","tool",
    "tools","product","products","service","services","software","app","apps",
    "make","makes","getting","get","would","could","should","also","like","much",
    "many","still","even","good","better","bad","new","way","ways","use",
    "model","models","ai","data","company","companies",
}

FAILURE_BUCKETS = {
    "reliability": re.compile(r"\b(unreliable|inconsistent|fail|fails|failing|failure|broken|crash|crashes)\w*\b", re.I),
    "memory_context": re.compile(r"\b(memory|context|forget|forgets|forgetting|retain|retention|instruction)\w*\b", re.I),
    "deployment": re.compile(r"\b(deploy|deployment|integrat|integration|configure|configuration|setup)\w*\b", re.I),
    "performance": re.compile(r"\b(latency|slow|performance|load|timeout|throughput)\w*\b", re.I),
    "cost": re.compile(r"\b(cost|costs|pricing|price|expensive|billing|compute)\w*\b", re.I),
    "quality": re.compile(r"\b(incorrect|wrong|quality|hallucin|assumption|output)\w*\b", re.I),
    "permission": re.compile(r"\b(auth|permission|access|security|role|roles)\w*\b", re.I),
    "multimodal": re.compile(r"\b(multimodal|multi-modal|vision|image|audio)\w*\b", re.I),
}


def clean_text(title: str | None, body: str | None) -> str:
    text = f"{title or ''} {body or ''}"
    text = html.unescape(text)
    text = CODE_RE.sub(" ", text)
    text = TAG_RE.sub(" ", text)
    text = URL_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def norm_text(text: str | None) -> str:
    x = clean_text("", text).lower()
    x = re.sub(r"[^a-z0-9+#._ -]+", " ", x)
    return re.sub(r"\s+", " ", x).strip()


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


def content_hash(*parts: Any) -> str:
    blob = "\n".join(str(x or "") for x in parts)
    return hashlib.sha256(blob.encode("utf-8", errors="ignore")).hexdigest()


def word_set(text: str) -> set[str]:
    toks = re.findall(r"[a-zA-Z][a-zA-Z0-9_+#.-]{2,}", text.lower())
    return {
        t for t in toks
        if len(t) >= 4 and t not in GENERIC_TERMS and not t.isdigit()
    }


def failure_buckets(text: str) -> set[str]:
    return {name for name, rx in FAILURE_BUCKETS.items() if rx.search(text or "")}


def query_text(c: ProblemCandidate) -> str:
    parts = [
        c.title,
        c.problem_statement,
        c.actor,
        c.task,
        c.object,
        c.failure_mode,
        c.consequence,
    ]
    return " ".join(str(x or "") for x in parts if x)


def discussion_key_for_reddit(
    post_id: int,
    platform_post_id: str | None,
    url: str | None,
    meta: dict,
) -> str:
    root = str(meta.get("parent_post_id") or "").strip()
    if not root and url:
        m = REDDIT_THREAD_RE.search(url)
        if m:
            root = m.group(1)
    pp = str(platform_post_id or "")
    if not root and pp.startswith("reddit_") and not pp.startswith("reddit_comment_"):
        root = pp[len("reddit_"):]
    return f"reddit:{root or pp or post_id}"


def build_hn_parent(rows) -> dict[str, str]:
    parent: dict[str, str] = {}
    for row in rows:
        if row.platform != "hackernews":
            continue
        meta = row.raw_metadata if isinstance(row.raw_metadata, dict) else {}
        hn_id = str(meta.get("hn_id") or "").strip()
        if not hn_id:
            pp = str(row.platform_post_id or "")
            if pp.startswith("hn_"):
                hn_id = pp[3:]
        p = str(meta.get("parent_hn_id") or "").strip()
        if hn_id and p:
            parent[hn_id] = p
    return parent


def hn_root(hn_id: str, parent: dict[str, str]) -> str:
    cur = hn_id
    seen = set()
    for _ in range(20):
        if not cur or cur in seen:
            break
        seen.add(cur)
        nxt = parent.get(cur)
        if not nxt:
            break
        cur = nxt
    return cur or hn_id


def discussion_key_for_hn(
    post_id: int,
    platform_post_id: str | None,
    meta: dict,
    parent: dict[str, str],
) -> str:
    hn_id = str(meta.get("hn_id") or "").strip()
    if not hn_id:
        pp = str(platform_post_id or "")
        if pp.startswith("hn_"):
            hn_id = pp[3:]
    root = hn_root(hn_id, parent) if hn_id else ""
    return f"hackernews:{root or post_id}"


def source_ref_for_discussion(d: dict) -> str:
    return d["discussion_key"]


def strict_match(
    query: str,
    discussion: str,
    word_sim: float,
    char_sim: float,
) -> tuple[str, dict[str, Any]]:
    q_terms = word_set(query)
    d_terms = word_set(discussion)
    shared = q_terms & d_terms

    q_fail = failure_buckets(query)
    d_fail = failure_buckets(discussion)
    shared_failure = q_fail & d_fail

    combined = 0.68 * float(word_sim) + 0.32 * float(char_sim)

    # "specific overlap" prevents broad AI/model/software topic matches.
    specific_overlap = len(shared)
    failure_ok = bool(shared_failure)

    # Strong is intentionally difficult to reach.
    strong = (
        combined >= 0.50
        and word_sim >= 0.43
        and char_sim >= 0.46
        and specific_overlap >= 3
        and failure_ok
    )

    # Ambiguous means "worth a narrow semantic verifier", not SUPPORT.
    ambiguous = (
        not strong
        and combined >= 0.32
        and specific_overlap >= 2
        and (failure_ok or char_sim >= 0.52)
    )

    verdict = "STRONG" if strong else "AMBIGUOUS" if ambiguous else "REJECT"
    return verdict, {
        "word_sim": round(float(word_sim), 4),
        "char_sim": round(float(char_sim), 4),
        "combined": round(float(combined), 4),
        "shared_specific_terms": sorted(shared)[:18],
        "shared_failure_buckets": sorted(shared_failure),
    }


async def _one_or_none(session, stmt):
    result = await session.execute(stmt)
    return result.scalar_one_or_none()



def _claim_state_local(
    claim_code: str,
    required_support_groups: int,
    links: list[tuple[RadarClaimEvidence, RadarEvidence]],
) -> tuple[str, dict[str, Any]]:
    # Evaluate one atomic claim strictly from validated ledger evidence.
    # Kept local to V4.2 so execution does not depend on private helpers
    # exported by an older migration processor.
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

    summary = {
        "support_groups": len(support_families),
        "direct_support_groups": len(direct_support_families),
        "refute_groups": len(refute_families),
        "insufficient_or_related": insufficient_count,
        "required_support_groups": required,
    }
    return state, summary

async def _recompute_c02(session, case: RadarCase, claim: RadarClaim, unknown: RadarUnknown | None):
    pairs = list((await session.execute(
        select(RadarClaimEvidence, RadarEvidence)
        .join(RadarEvidence, RadarEvidence.id == RadarClaimEvidence.evidence_id)
        .where(RadarClaimEvidence.claim_id == claim.id)
    )).all())

    state, evidence_summary = _claim_state_local(
        claim.claim_code,
        claim.required_support_groups,
        pairs,
    )
    claim.state = state
    claim.support_groups = evidence_summary["support_groups"]
    claim.direct_support_groups = evidence_summary["direct_support_groups"]
    claim.refute_groups = evidence_summary["refute_groups"]
    claim.insufficient_count = evidence_summary["insufficient_or_related"]
    claim.evidence_summary = evidence_summary
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
    case.current_gate = "MARKET_REALITY" if verdict == "INVESTIGATE" else "PROBLEM_REALITY"
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
            reason_text="V4.2 recurrence executor updated C02 using local deterministic evidence only.",
            triggering_claim_code="C02",
            engine_version=ENGINE_VERSION,
            decision_snapshot={
                "C02": state,
                "support_groups": evidence_summary["support_groups"],
                "direct_support_groups": evidence_summary["direct_support_groups"],
                "refute_groups": evidence_summary["refute_groups"],
            },
        ))
    return state, verdict


async def run_problem_recurrence() -> dict[str, Any]:
    now = datetime.now()
    summary = Counter()

    async with async_session() as session:
        # Pull HN + Reddit raw corpus. This mirrors the established repo fields.
        raw_rows = list((await session.execute(
            select(
                Post.id.label("id"),
                Post.user_id.label("user_id"),
                Post.platform_post_id.label("platform_post_id"),
                Post.post_type.label("post_type"),
                Post.title.label("title"),
                Post.body.label("body"),
                Post.url.label("url"),
                Post.subreddit.label("subreddit"),
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

        # Build precision-first direct-problem discussions.
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
                "platform_post_id": row.platform_post_id,
                "post_type": row.post_type,
                "title": row.title or "",
                "text": text,
                "url": row.url,
                "subreddit": row.subreddit,
                "score": int(row.score or 0),
                "num_comments": int(row.num_comments or 0),
                "posted_at": row.posted_at,
                "platform": row.platform,
                "discussion_key": dkey,
            })

        discussions: list[dict[str, Any]] = []
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
                snippets.append(p["text"][:520])
                if len(snippets) >= 6:
                    break
            text = " ".join(snippets)[:2600]
            if len(text) < 45:
                continue

            discussions.append({
                "discussion_key": dkey,
                "platform": posts[0]["platform"],
                "text": text,
                "posts": posts,
                "user_ids": {p["user_id"] for p in posts if p["user_id"]},
                "observed_at": max(
                    [p["posted_at"] for p in posts if p["posted_at"]],
                    default=None,
                ),
            })

        cases = list((await session.execute(
            select(RadarCase, ProblemCandidate)
            .join(ProblemCandidate, ProblemCandidate.id == RadarCase.candidate_id)
            .order_by(RadarCase.id)
        )).all())

        if not cases or not discussions:
            print("No cases or direct-problem discussions available.")
            return {
                "engine_version": ENGINE_VERSION,
                "cases": len(cases),
                "discussions": len(discussions),
                "llm_calls": 0,
                "llm_cost_twd": 0.0,
            }

        queries = [query_text(candidate) for _, candidate in cases]
        corpus = queries + [d["text"] for d in discussions]

        word_vec = TfidfVectorizer(
            stop_words="english",
            ngram_range=(1, 2),
            min_df=1,
            max_df=0.90,
            sublinear_tf=True,
            max_features=14000,
            token_pattern=r"(?u)\b[a-zA-Z][a-zA-Z0-9_+#.-]{1,}\b",
        )
        Xw = word_vec.fit_transform(corpus)

        char_vec = TfidfVectorizer(
            analyzer="char_wb",
            ngram_range=(3, 5),
            min_df=2,
            max_features=18000,
            sublinear_tf=True,
        )
        Xc = char_vec.fit_transform(corpus)

        qn = len(queries)
        word_sim = cosine_similarity(Xw[:qn], Xw[qn:])
        char_sim = cosine_similarity(Xc[:qn], Xc[qn:])

        for case_index, (case, candidate) in enumerate(cases):
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
            action = await _one_or_none(
                session,
                select(RadarResearchAction)
                .where(
                    RadarResearchAction.case_id == case.id,
                    RadarResearchAction.claim_code == "C02",
                    RadarResearchAction.method == "local_problem_recurrence_search",
                )
                .order_by(RadarResearchAction.id.desc())
                .limit(1),
            )

            if c02 is None:
                summary["missing_c02"] += 1
                continue

            # Backfill original community evidence as the first occurrence family.
            originals = list((await session.execute(
                select(RadarEvidence)
                .where(
                    RadarEvidence.case_id == case.id,
                    RadarEvidence.directness == "DIRECT",
                )
            )).scalars().all())

            original_families = set()
            for ev in originals:
                original_families.add(ev.source_family_key)
                link = await _one_or_none(
                    session,
                    select(RadarClaimEvidence).where(
                        RadarClaimEvidence.claim_id == c02.id,
                        RadarClaimEvidence.evidence_id == ev.id,
                    ),
                )
                if link is None and ev.authority_class == "USER_DISCUSSION":
                    session.add(RadarClaimEvidence(
                        claim_id=c02.id,
                        evidence_id=ev.id,
                        stance="SUPPORT",
                        interpretation_method="DETERMINISTIC_OCCURRENCE_BACKFILL",
                        method_version=ENGINE_VERSION,
                        interpretation_confidence=1.0,
                        rationale=(
                            "This direct first-hand discussion is one observed occurrence. "
                            "C02 still requires another independent support family."
                        ),
                        validated=True,
                    ))
                    summary["original_occurrences_backfilled"] += 1

            q = queries[case_index]
            ranked = np.argsort(
                -(0.68 * word_sim[case_index] + 0.32 * char_sim[case_index])
            )

            strong_hits = []
            ambiguous_hits = []

            for j in ranked[:30]:
                d = discussions[int(j)]
                family = f"discussion:{d['discussion_key']}"
                if family in original_families:
                    continue

                verdict, detail = strict_match(
                    q,
                    d["text"],
                    float(word_sim[case_index, j]),
                    float(char_sim[case_index, j]),
                )
                if verdict == "REJECT":
                    continue

                item = {
                    "discussion_key": d["discussion_key"],
                    "platform": d["platform"],
                    "title": d["posts"][0]["title"][:220],
                    "excerpt": d["text"][:900],
                    "url": d["posts"][0]["url"],
                    "observed_at": d["observed_at"].isoformat()
                        if d["observed_at"] else None,
                    "user_count": len(d["user_ids"]),
                    **detail,
                }

                if verdict == "STRONG":
                    strong_hits.append(item)
                else:
                    ambiguous_hits.append(item)

                if len(strong_hits) >= 2 and len(ambiguous_hits) >= 5:
                    break

            # Only the single strongest new discussion is necessary to cross
            # recurrence when the original occurrence is already one family.
            for hit in strong_hits[:2]:
                family = f"discussion:{hit['discussion_key']}"
                ev_key = (
                    f"recurrence:{case.id}:"
                    f"{content_hash(hit['discussion_key'])[:24]}"
                )
                ev = await _one_or_none(
                    session,
                    select(RadarEvidence).where(
                        RadarEvidence.evidence_key == ev_key
                    ),
                )
                if ev is None:
                    ev = RadarEvidence(
                        case_id=case.id,
                        candidate_evidence_id=None,
                        evidence_key=ev_key,
                        source_type=hit["platform"],
                        source_table="posts",
                        source_ref=source_ref_for_discussion(hit),
                        source_url=normalize_url(hit["url"]) or None,
                        source_title=hit["title"] or None,
                        excerpt=hit["excerpt"],
                        source_family_key=family,
                        directness="DIRECT",
                        authority_class="USER_DISCUSSION",
                        published_at=(
                            datetime.fromisoformat(hit["observed_at"])
                            if hit["observed_at"] else None
                        ),
                        observed_at=now,
                        freshness_class="UNASSESSED",
                        content_hash=content_hash(hit["excerpt"]),
                        raw_metadata={
                            "engine_version": ENGINE_VERSION,
                            "deterministic_match": {
                                k: v for k, v in hit.items()
                                if k in {
                                    "word_sim",
                                    "char_sim",
                                    "combined",
                                    "shared_specific_terms",
                                    "shared_failure_buckets",
                                }
                            },
                        },
                    )
                    session.add(ev)
                    await session.flush()
                    summary["strong_evidence_created"] += 1

                link = await _one_or_none(
                    session,
                    select(RadarClaimEvidence).where(
                        RadarClaimEvidence.claim_id == c02.id,
                        RadarClaimEvidence.evidence_id == ev.id,
                    ),
                )
                if link is None:
                    session.add(RadarClaimEvidence(
                        claim_id=c02.id,
                        evidence_id=ev.id,
                        stance="SUPPORT",
                        interpretation_method="DETERMINISTIC_RECURRENCE_MATCH",
                        method_version=ENGINE_VERSION,
                        interpretation_confidence=hit["combined"],
                        rationale=(
                            "Strict local hybrid retrieval passed word similarity, "
                            "character similarity, specific-term overlap, failure-mode "
                            "overlap, and independent-discussion guards."
                        ),
                        validated=True,
                    ))
                    summary["strong_claim_links_created"] += 1

            await session.flush()
            c02_state, verdict = await _recompute_c02(
                session, case, c02, unknown
            )
            summary[f"c02_{c02_state.lower()}"] += 1
            summary[f"verdict_{verdict.lower()}"] += 1

            if action is not None:
                action.attempt_count = int(action.attempt_count or 0) + 1
                action.last_attempt_at = now
                action.result_metadata = {
                    "engine_version": ENGINE_VERSION,
                    "strong_hits": strong_hits[:5],
                    "ambiguous_hits": ambiguous_hits[:5],
                    "c02_state_after": c02_state,
                    "original_family_count": len(original_families),
                }

                if c02_state == "SUPPORTED":
                    action.status = "COMPLETED"
                    action.ai_allowed = False
                    action.ai_gate_reason = "DENY_C02_RESOLVED_BY_ALGORITHM"
                    summary["actions_completed_free"] += 1
                elif ambiguous_hits:
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
                        estimated_call_cost_twd=0.01,
                        remaining_case_budget_twd=remaining,
                        decision_impact=float(action.decision_impact or 1.0),
                    )
                    action.status = "AMBIGUOUS"
                    action.ai_allowed = gate.allowed
                    action.ai_task_name = "same_problem_verify"
                    action.ai_gate_reason = gate.reason
                    action.estimated_llm_cost_twd = 0.01 if gate.allowed else 0.0
                    summary["actions_ambiguous"] += 1
                    if gate.allowed:
                        summary["ai_fallbacks_authorized_not_called"] += 1
                else:
                    action.status = "INSUFFICIENT"
                    action.ai_allowed = False
                    action.ai_gate_reason = (
                        "DENY_NO_AMBIGUOUS_LOCAL_PAIR: AI cannot create missing evidence."
                    )
                    summary["actions_insufficient"] += 1

        await session.commit()

    print()
    print("=" * 104)
    print("RADAR V4.2 — LOCAL PROBLEM RECURRENCE")
    print("=" * 104)
    print(f"Raw HN/Reddit rows scanned: {len(raw_rows)}")
    print(f"Direct-problem discussions built: {len(discussions)}")
    print(f"Cases evaluated: {len(cases)}")
    print()
    print(f"Original C02 occurrence links backfilled: {summary['original_occurrences_backfilled']}")
    print(f"Strong new recurrence evidence created: {summary['strong_evidence_created']}")
    print(f"Strong C02 links created: {summary['strong_claim_links_created']}")
    print()
    print("C02 after local algorithm:")
    for st in ("supported", "insufficient", "unknown", "refuted", "conflicted"):
        print(f"  {st:12s}: {summary[f'c02_{st}']}")
    print()
    print("System verdicts after recurrence pass:")
    for v in ("investigate", "watch", "ignore"):
        print(f"  {v:12s}: {summary[f'verdict_{v}']}")
    print()
    print("Research actions:")
    print(f"  completed free : {summary['actions_completed_free']}")
    print(f"  ambiguous      : {summary['actions_ambiguous']}")
    print(f"  insufficient   : {summary['actions_insufficient']}")
    print(f"  AI fallbacks authorized but NOT called: {summary['ai_fallbacks_authorized_not_called']}")
    print()
    print("AI calls executed: 0")
    print("AI cost this run: NT$0.00")
    print("=" * 104)

    return {
        "engine_version": ENGINE_VERSION,
        "raw_rows_scanned": len(raw_rows),
        "direct_problem_discussions": len(discussions),
        "cases_evaluated": len(cases),
        "strong_evidence_created": summary["strong_evidence_created"],
        "c02_supported": summary["c02_supported"],
        "c02_insufficient": summary["c02_insufficient"],
        "c02_unknown": summary["c02_unknown"],
        "verdict_investigate": summary["verdict_investigate"],
        "verdict_watch": summary["verdict_watch"],
        "actions_ambiguous": summary["actions_ambiguous"],
        "actions_insufficient": summary["actions_insufficient"],
        "ai_fallbacks_authorized_not_called": summary["ai_fallbacks_authorized_not_called"],
        "llm_calls": 0,
        "llm_cost_twd": 0.0,
    }
