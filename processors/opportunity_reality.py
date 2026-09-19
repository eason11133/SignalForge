"""Opportunity Reality Engine V1.

Turns existing local Radar data into conservative evidence for the weakest
commercial-reality claims without web/API/LLM calls.

Target claims:
- C03 consequence_material
- C05 buyer_exists
- C06 current_solution_unsatisfactory
- C07 unresolved_gap_exists
- C09 company_can_execute (explicitly left unresolved without capability input)
- C12 window_outlasts_execution (timing evidence only; execution estimate required)

Also produces a deterministic Founder attention ranking. The ranking is NOT
an opportunity score and never changes BUILD/VALIDATE verdicts.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.preprocessing import normalize
from sqlalchemy import select

from processors.signalforge_atomic_io import atomic_write_json

from database.connection import (
    async_session,
    ProblemCandidate,
    RadarCase,
    RadarClaim,
    RadarEvidence,
    RadarClaimEvidence,
    RadarResearchAction,
    CandidateEvidence,
    JobListing,
    GithubRepo,
    GithubIssue,
    PackageDownload,
    YCCompany,
    NewsEvent,
)

try:
    from scrapers.coverage_controller import coverage_snapshot
except Exception:
    coverage_snapshot = None

ENGINE_VERSION = "opportunity-reality-v8-r7-exact-retrieval-cache"
RETRIEVAL_CACHE_DIR = Path(".radar_runtime/retrieval_cache")
RETRIEVAL_CACHE_SCHEMA = "match-rows-exact-r7-v1"
_RETRIEVAL_CACHE_STATS = {"hits": 0, "misses": 0, "writes": 0, "errors": 0}
TARGET_CLAIMS = {"C03", "C05", "C06", "C07", "C09", "C12"}

GENERIC = {
    "about", "after", "again", "also", "and", "application", "applications",
    "because", "before", "being", "between", "both", "build", "building",
    "business", "businesses", "cannot", "code", "company", "content", "could",
    "data", "development", "different", "does", "doing", "effective", "error",
    "failure", "for", "from", "good", "have", "having", "help", "into", "issue",
    "issues", "just", "lack", "like", "manage", "model", "models", "more", "most",
    "need", "only", "other", "output", "over", "people", "poor", "problem",
    "problems", "process", "product", "products", "project", "quality", "really",
    "results", "same", "service", "services", "software", "some", "still", "support",
    "system", "systems", "task", "than", "that", "their", "them", "then", "there",
    "these", "they", "thing", "things", "this", "those", "through", "tool", "tools",
    "under", "user", "users", "using", "very", "want", "what", "when", "where",
    "which", "while", "with", "without", "work", "workflow", "works", "working", "would",
}
TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_+.#:/-]{1,}")

SEVERE_PATTERNS = [
    r"\bcannot\b", r"\bcan't\b", r"\bunable\b", r"\bunusable\b", r"\bblocked\b",
    r"\bbreaks?\b", r"\bfails?\b", r"\bcrash", r"\bstops?\b", r"\bdowntime\b",
    r"\bdata loss\b", r"\blost data\b", r"\bsecurity\b", r"\bprivacy\b",
    r"\bwaste(?:s|d)?\b", r"\bhours?\b", r"\bdays?\b", r"\bmanual workaround\b",
    r"\bexpensive\b", r"\bcost(?:s|ly)?\b", r"\brevenue\b", r"\brefund\b",
]

# C03 is material consequence, not generic failure severity. A direct quote
# must contain a concrete operational/economic consequence signal.
MATERIAL_CONSEQUENCE_PATTERNS = [
    r"\b(?:production|workflow|deployment|release|customer)\s+(?:is\s+)?blocked\b",
    r"\b(?:cannot|can't|unable to)\s+(?:ship|deploy|use|operate|complete|finish|serve)\b",
    r"\b(?:downtime|outage|data loss|lost data|security incident|privacy breach)\b",
    r"(?:[$€£]\s?\d|\b\d+(?:\.\d+)?\s*(?:usd|eur|gbp|dollars?|euros?|pounds?)\b)",
    r"\b(?:revenue|refund|churn|lost customer|lost sale|support cost)\b",
    r"\b\d+(?:\.\d+)?\s*(?:minutes?|hours?|days?|weeks?)\b",
    r"\b(?:hours?|days?)\s+(?:of\s+)?(?:manual|rework|debugging|workaround|delay)\b",
    r"\bmanual workaround\b",
]

def _material_consequence_support(candidate_consequence: str, text: str) -> bool:
    if not _has_any(text, MATERIAL_CONSEQUENCE_PATTERNS):
        return False
    # _tokens() already removes GENERIC terms; do not depend on a second
    # undeclared stopword set here.
    consequence_terms = {
        t for t in _tokens(candidate_consequence or "")
        if len(t) >= 4
    }
    if not consequence_terms:
        return True
    evidence_terms = _tokens(text)
    # One generic shared token is no longer enough. Prefer two specific
    # consequence anchors, while explicit material-impact language remains
    # mandatory above.
    return len(consequence_terms & evidence_terms) >= min(2, len(consequence_terms))
UNSAT_PATTERNS = [
    r"\bunusable\b", r"\bunreliable\b", r"\binconsistent\b", r"\bbroken\b",
    r"\bfails?\b", r"\bcrash", r"\bregression\b", r"\bworkaround\b",
    r"\bdoesn.?t work\b", r"\bnot work(?:ing)?\b", r"\bfrustrat", r"\bbug\b",
]
TIMING_PATTERNS = [
    r"\blaunch", r"\brelease", r"\bnew\b", r"\bannounc", r"\bgrowth\b",
    r"\badoption\b", r"\bdemand\b", r"\btrend", r"\bfunding\b", r"\bhiring\b",
]


DOMAIN_PATTERNS = {
    "AI_LLM": [
        r"\bai\b", r"\bllm", r"\bgpt", r"\bclaude\b", r"\bgemini\b",
        r"\bdeepseek\b", r"\bopenai\b", r"\banthropic\b", r"\bllama(?:\.cpp)?\b",
        r"\binference\b", r"\bmodel output\b", r"\bagent(?:ic)?\b",
    ],
    "GPU_COMPUTE": [
        r"\bgpu\b", r"\bvram\b", r"\bcuda\b", r"\bnvidia\b", r"\bamd\b",
        r"\bdgx\b", r"\baccelerator\b",
    ],
    "DEVTOOLS": [
        r"\bdeveloper\b", r"\bdebug", r"\bcompiler\b", r"\bgyp\b", r"\bgithub\b",
        r"\bgitlab\b", r"\bci/cd\b", r"\bci\b", r"\bsdk\b", r"\bide\b",
        r"\bcodebase\b", r"\btesting\b", r"\bregression test",
    ],
    "API_ACCESS": [
        r"\bapi\b", r"\bonboard", r"\bsign[\s-]?up\b", r"\bauth", r"\baccess\b",
        r"\brate limit", r"\b429\b", r"\bquota\b", r"\btoken\b",
    ],
    "CLOUD_DEVOPS": [
        r"\bdeploy", r"\bserver\b", r"\bcontainer\b", r"\bdocker\b", r"\bkubernetes\b",
        r"\bcloud\b", r"\baws\b", r"\bgcp\b", r"\bazure\b", r"\bruntime\b",
    ],
    "DATA_ML": [
        r"\bmachine learning\b", r"\bml\b", r"\btraining\b", r"\bevaluation\b",
        r"\bbenchmark\b", r"\bdataset\b", r"\bmodeling\b", r"\bprediction\b",
    ],
    "SECURITY_PRIVACY": [
        r"\bsecurity\b", r"\bprivacy\b", r"\btracking\b", r"\bpersonal data\b",
        r"\bvulnerab", r"\bauthentication\b", r"\bpermission\b",
    ],
    "NETWORKING": [
        r"\bnetwork\b", r"\btailscale\b", r"\bheadscale\b", r"\bvpn\b",
        r"\bconnection\b", r"\bproxy\b",
    ],
    "CRM_ENTERPRISE": [
        r"\bsalesforce\b", r"\bcrm\b", r"\benterprise\b", r"\bintegration\b",
    ],
    "CREATIVE": [
        r"\bsong", r"\bmusic\b", r"\bcreative\b", r"\bwriting\b", r"\bediting\b",
        r"\btext editing\b",
    ],
    "STARTUP_BUSINESS": [
        r"\bstartup\b", r"\bfounder\b", r"\bmarketing\b", r"\bsales\b",
        r"\bbuyer\b", r"\bcustomer\b", r"\bhiring\b",
    ],
    "CONSUMER_PRODUCT": [
        r"\bconsumer\b", r"\bsubscription\b", r"\bpricing\b", r"\brefund\b",
        r"\bcheckout\b", r"\bproduct design\b",
    ],
}

BUYER_PATTERNS = [
    r"\bhiring\b", r"\bengineer\b", r"\bdeveloper\b", r"\barchitect\b",
    r"\bmanager\b", r"\blead\b", r"\bspecialist\b", r"\bplatform\b",
    r"\binfrastructure\b", r"\boperations\b",
]


def _domains(text: str) -> set[str]:
    low = (text or "").lower()
    out = set()
    for label, patterns in DOMAIN_PATTERNS.items():
        if any(re.search(p, low, re.I) for p in patterns):
            out.add(label)
    return out


def _rare_shared(query_terms: set[str], doc_terms: set[str], df: Counter, n_docs: int) -> list[str]:
    vals = []
    for term in query_terms & doc_terms:
        # terms appearing in <= 3% of the local corpus are useful identity anchors
        if df.get(term, 0) <= max(2, int(n_docs * 0.03)):
            vals.append(term)
    return sorted(vals)


def _semantic_matrix(corpus: list[str]) -> np.ndarray | None:
    """Cheap local LSA. Failure gracefully falls back to lexical-only retrieval."""
    if len(corpus) < 4:
        return None
    try:
        vec = TfidfVectorizer(
            stop_words="english",
            ngram_range=(1, 2),
            min_df=1,
            max_df=0.98,
            sublinear_tf=True,
            max_features=42000,
            token_pattern=r"(?u)\b[a-zA-Z][a-zA-Z0-9_+#./:-]{1,}\b",
        )
        X = vec.fit_transform(corpus)
        dims = min(120, X.shape[0] - 1, X.shape[1] - 1)
        if dims < 2:
            return None
        svd = TruncatedSVD(
            n_components=dims,
            algorithm="randomized",
            n_iter=6,
            random_state=42,
        )
        return normalize(svd.fit_transform(X))
    except Exception:
        return None


def _tokens(text: str) -> set[str]:
    out = set()
    for raw in TOKEN_RE.findall(text or ""):
        t = raw.lower().strip("._-/:#")
        if len(t) < 3 or t in GENERIC:
            continue
        out.add(t)
    return out


def _candidate_text(c: ProblemCandidate) -> str:
    values = [
        c.title, c.problem_statement, c.actor, c.task, c.object,
        c.failure_mode, c.consequence, c.buyer_context, c.workaround,
    ]
    weighted = [
        c.object, c.object, c.object,
        c.failure_mode, c.failure_mode, c.failure_mode,
        c.task, c.task,
        c.title, c.problem_statement, c.consequence, c.buyer_context,
    ]
    return " ".join(str(x or "") for x in weighted + values)[:8000]


def _named_anchor_terms(c: ProblemCandidate) -> set[str]:
    text = " ".join(str(x or "") for x in [c.object, c.task, c.failure_mode, c.title])
    anchors = set()
    for raw in TOKEN_RE.findall(text):
        low = raw.lower().strip("._-/:#")
        if low in GENERIC or len(low) < 3:
            continue
        if any(ch.isdigit() for ch in raw) or any(ch in raw for ch in ".+/#_-"):
            anchors.add(low)
        elif raw.isupper() and len(raw) >= 3:
            anchors.add(low)
        elif len(low) >= 6:
            anchors.add(low)
    return anchors



def _retrieval_cache_key(
    candidates: list[ProblemCandidate],
    docs: list[dict[str, Any]],
    *,
    threshold: float,
    top_k: int,
    role: str,
) -> str:
    h = hashlib.sha256()
    h.update(RETRIEVAL_CACHE_SCHEMA.encode("ascii"))
    h.update(str(role).encode("utf-8"))
    h.update(repr(float(threshold)).encode("ascii"))
    h.update(str(int(top_k)).encode("ascii"))
    for c in candidates:
        for part in (str(c.id), _candidate_text(c), " ".join(sorted(_named_anchor_terms(c)))):
            raw = part.encode("utf-8", errors="ignore")
            h.update(len(raw).to_bytes(8, "little"))
            h.update(raw)
    for idx, d in enumerate(docs):
        for part in (str(idx), str(d.get("id") or ""), str(d.get("text") or "")):
            raw = part.encode("utf-8", errors="ignore")
            h.update(len(raw).to_bytes(8, "little"))
            h.update(raw)
    return h.hexdigest()[:32]


def _retrieval_cache_load(key: str, candidates: list[ProblemCandidate], docs: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]] | None:
    path = RETRIEVAL_CACHE_DIR / f"match_{key}.json"
    try:
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("schema") != RETRIEVAL_CACHE_SCHEMA or data.get("key") != key:
            return None
        cached = data.get("rows") or {}
        out: dict[int, list[dict[str, Any]]] = {}
        for c in candidates:
            rows = []
            for item in cached.get(str(c.id), []) or []:
                j = int(item.get("doc_index", -1))
                if j < 0 or j >= len(docs):
                    return None
                row = dict(docs[j])
                for field in (
                    "retrieval_score", "lexical_score", "semantic_score",
                    "shared_terms", "named_shared", "rare_shared", "domain_shared",
                ):
                    row[field] = item.get(field)
                rows.append(row)
            out[int(c.id)] = rows
        _RETRIEVAL_CACHE_STATS["hits"] += 1
        return out
    except Exception:
        _RETRIEVAL_CACHE_STATS["errors"] += 1
        return None


def _retrieval_cache_save(key: str, out: dict[int, list[dict[str, Any]]], docs: list[dict[str, Any]]) -> None:
    try:
        index_by_identity = {}
        for idx, d in enumerate(docs):
            ident = (str(d.get("id") or ""), str(d.get("text") or ""))
            index_by_identity.setdefault(ident, []).append(idx)
        payload_rows: dict[str, list[dict[str, Any]]] = {}
        for cid, rows in out.items():
            packed = []
            for row in rows:
                ident = (str(row.get("id") or ""), str(row.get("text") or ""))
                choices = index_by_identity.get(ident) or []
                if not choices:
                    return
                j = choices[0]
                packed.append({
                    "doc_index": j,
                    "retrieval_score": row.get("retrieval_score"),
                    "lexical_score": row.get("lexical_score"),
                    "semantic_score": row.get("semantic_score"),
                    "shared_terms": row.get("shared_terms") or [],
                    "named_shared": row.get("named_shared") or [],
                    "rare_shared": row.get("rare_shared") or [],
                    "domain_shared": row.get("domain_shared") or [],
                })
            payload_rows[str(cid)] = packed
        RETRIEVAL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path = RETRIEVAL_CACHE_DIR / f"match_{key}.json"
        atomic_write_json(path, {
            "schema": RETRIEVAL_CACHE_SCHEMA,
            "key": key,
            "rows": payload_rows,
            "truth_boundary": "EXACT_DERIVED_RETRIEVAL_REUSE_ONLY_NO_EVIDENCE_OR_THRESHOLD_AUTHORITY",
        })
        _RETRIEVAL_CACHE_STATS["writes"] += 1
        files = sorted(RETRIEVAL_CACHE_DIR.glob("match_*.json"), key=lambda x: x.stat().st_mtime, reverse=True)
        for old in files[18:]:
            try:
                old.unlink()
            except OSError:
                pass
    except Exception:
        _RETRIEVAL_CACHE_STATS["errors"] += 1


def retrieval_cache_diagnostics() -> dict[str, Any]:
    return {
        "schema": RETRIEVAL_CACHE_SCHEMA,
        **dict(_RETRIEVAL_CACHE_STATS),
        "truth_boundary": "DERIVED_RETRIEVAL_CACHE_ONLY_NO_MARKET_TRUTH_AUTHORITY",
    }


def _match_rows(
    candidates: list[ProblemCandidate],
    docs: list[dict[str, Any]],
    *,
    threshold: float,
    top_k: int = 8,
    role: str = "context",
) -> dict[int, list[dict[str, Any]]]:
    """Hybrid lexical + local-semantic retrieval with deterministic domain gating.

    Important: this only finds context candidates. Claim SUPPORT is still decided
    later by role-specific evidence rules.
    """
    if not docs:
        return {c.id: [] for c in candidates}

    cache_key = _retrieval_cache_key(
        candidates, docs, threshold=threshold, top_k=top_k, role=role
    )
    cached = _retrieval_cache_load(cache_key, candidates, docs)
    if cached is not None:
        return cached
    _RETRIEVAL_CACHE_STATS["misses"] += 1

    queries = [_candidate_text(c) for c in candidates]
    texts = [d["text"] for d in docs]
    corpus = queries + texts
    n = len(candidates)

    word = TfidfVectorizer(
        stop_words="english", ngram_range=(1, 2), min_df=1, max_df=0.98,
        sublinear_tf=True, max_features=45000,
        token_pattern=r"(?u)\b[a-zA-Z][a-zA-Z0-9_+#./:-]{1,}\b",
    )
    char = TfidfVectorizer(
        analyzer="char_wb", ngram_range=(3, 5), min_df=2,
        sublinear_tf=True, max_features=35000,
    )
    Xw = word.fit_transform(corpus)
    Xc = char.fit_transform(corpus)
    sw = cosine_similarity(Xw[:n], Xw[n:])
    sc = cosine_similarity(Xc[:n], Xc[n:])
    lexical = 0.72 * sw + 0.28 * sc

    Z = _semantic_matrix(corpus)
    semantic = cosine_similarity(Z[:n], Z[n:]) if Z is not None else np.zeros_like(lexical)

    doc_token_sets = [_tokens(x) for x in texts]
    df = Counter()
    for ts in doc_token_sets:
        df.update(ts)

    semantic_floor = {
        "buyer": 0.27,
        "solution": 0.29,
        "competition": 0.27,
        "timing": 0.25,
        "package": 0.32,
        "context": 0.30,
    }.get(role, 0.30)

    out: dict[int, list[dict[str, Any]]] = {}
    for i, c in enumerate(candidates):
        qtext = queries[i]
        qterms = _tokens(qtext)
        qdomains = _domains(qtext)
        named = _named_anchor_terms(c)

        # retrieve broadly from either lexical or semantic score
        combined = np.maximum(lexical[i], semantic[i] * 0.78)
        rows = []
        for j in np.argsort(-combined)[: max(top_k * 10, 40)]:
            lex = float(lexical[i, j])
            sem = float(semantic[i, j])
            if lex < threshold and sem < semantic_floor:
                continue

            d = docs[int(j)]
            dterms = doc_token_sets[int(j)]
            shared = sorted(qterms & dterms)
            named_shared = sorted(named & dterms)
            rare_shared = _rare_shared(qterms, dterms, df, len(texts))
            ddomains = _domains(d["text"])
            domain_shared = sorted(qdomains & ddomains)

            # A market-context match may be broader than same-problem matching,
            # but it still needs an identity/domain basis. Semantic score alone
            # never gets accepted.
            structural = bool(
                named_shared
                or len(rare_shared) >= 2
                or (domain_shared and len(shared) >= 1)
                or (len(domain_shared) >= 2)
            )
            if not structural:
                continue

            # Package names are extremely short: require an explicit anchor.
            if role == "package" and not (named_shared or len(rare_shared) >= 1):
                continue

            row = dict(d)
            row["retrieval_score"] = round(max(lex, sem * 0.78), 4)
            row["lexical_score"] = round(lex, 4)
            row["semantic_score"] = round(sem, 4)
            row["shared_terms"] = shared[:20]
            row["named_shared"] = named_shared[:10]
            row["rare_shared"] = rare_shared[:10]
            row["domain_shared"] = domain_shared[:10]
            rows.append(row)
            if len(rows) >= top_k:
                break
        out[c.id] = rows
    _retrieval_cache_save(cache_key, out, docs)
    return out


def _hash_key(*parts: Any) -> str:
    raw = "|".join(str(x or "") for x in parts)
    return hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()[:32]


def _family_slug(value: str) -> str:
    s = re.sub(r"[^a-z0-9._-]+", "-", (value or "unknown").lower()).strip("-")
    return s[:120] or "unknown"


def _has_any(text: str, patterns: list[str]) -> bool:
    return any(re.search(p, text or "", re.I) for p in patterns)


def _session_cache_info(session) -> dict[str, Any]:
    info = getattr(session, "info", None)
    if isinstance(info, dict):
        return info
    sync_session = getattr(session, "sync_session", None)
    info = getattr(sync_session, "info", None)
    return info if isinstance(info, dict) else {}


async def _prime_reality_session_caches(
    session,
    *,
    claim_ids: list[int] | None = None,
) -> dict[str, int]:
    """Prime idempotent evidence/link lookups once per write session.

    M15 repeatedly issued one SELECT per evidence/link while rebuilding Reality.
    With ~1.6k evidence rows / ~3k links this dominated wall-clock despite the
    writes being idempotent. M16 keeps the exact same truth rules but turns
    those repeated point lookups into in-memory session maps.
    """
    evidence_rows = list((await session.execute(
        select(RadarEvidence)
    )).scalars().all())
    evidence_cache = {
        str(ev.evidence_key): ev
        for ev in evidence_rows
        if getattr(ev, "evidence_key", None)
    }
    evidence_by_id = {
        int(ev.id): ev
        for ev in evidence_rows
        if getattr(ev, "id", None) is not None
    }

    stmt = select(RadarClaimEvidence)
    if claim_ids:
        stmt = stmt.where(RadarClaimEvidence.claim_id.in_(claim_ids))
    link_rows = list((await session.execute(stmt)).scalars().all())

    link_cache = {}
    rows_by_claim: dict[int, list[tuple[RadarClaimEvidence, RadarEvidence]]] = defaultdict(list)
    for link in link_rows:
        ev = evidence_by_id.get(int(link.evidence_id))
        if ev is None:
            continue
        key = (int(link.claim_id), int(link.evidence_id))
        link_cache[key] = link
        rows_by_claim[int(link.claim_id)].append((link, ev))

    info = _session_cache_info(session)
    info["signalforge_evidence_cache"] = evidence_cache
    info["signalforge_link_cache"] = link_cache
    info["signalforge_rows_by_claim"] = rows_by_claim
    return {
        "evidence": len(evidence_cache),
        "links": len(link_cache),
        "claims": len(rows_by_claim),
    }


async def _ensure_evidence(
    session,
    case_id: int,
    *,
    source_type: str,
    source_table: str,
    source_ref: str,
    source_title: str,
    excerpt: str,
    source_url: str | None,
    source_family_key: str,
    authority_class: str,
    directness: str = "RELATED",
    published_at: datetime | None = None,
    metadata: dict[str, Any] | None = None,
) -> RadarEvidence:
    key = f"reality:{_hash_key(case_id, source_type, source_table, source_ref)}"
    info = _session_cache_info(session)
    evidence_cache = info.get("signalforge_evidence_cache")
    existing = (
        evidence_cache.get(key)
        if isinstance(evidence_cache, dict)
        else None
    )
    if existing is None and not isinstance(evidence_cache, dict):
        existing = (await session.execute(
            select(RadarEvidence).where(RadarEvidence.evidence_key == key)
        )).scalar_one_or_none()
    if existing:
        return existing

    ev = RadarEvidence(
        case_id=case_id,
        evidence_key=key,
        source_type=source_type,
        source_table=source_table,
        source_ref=str(source_ref),
        source_url=source_url,
        source_title=(source_title or "")[:4000],
        excerpt=(excerpt or "")[:8000],
        source_family_key=source_family_key[:255],
        directness=directness,
        authority_class=authority_class,
        published_at=published_at,
        observed_at=datetime.utcnow(),
        freshness_class="RECENT" if published_at and published_at >= datetime.utcnow() - timedelta(days=90) else "UNASSESSED",
        raw_metadata=metadata or {},
    )
    session.add(ev)
    await session.flush()
    if isinstance(evidence_cache, dict):
        evidence_cache[key] = ev
    return ev


async def _link_claim(
    session,
    claim: RadarClaim,
    evidence: RadarEvidence,
    *,
    stance: str,
    rationale: str,
    confidence: float,
) -> bool:
    info = _session_cache_info(session)
    link_cache = info.get("signalforge_link_cache")
    rows_by_claim = info.get("signalforge_rows_by_claim")
    pair = (int(claim.id), int(evidence.id))
    existing = (
        link_cache.get(pair)
        if isinstance(link_cache, dict)
        else None
    )
    if existing is None and not isinstance(link_cache, dict):
        existing = (await session.execute(
            select(RadarClaimEvidence).where(
                RadarClaimEvidence.claim_id == claim.id,
                RadarClaimEvidence.evidence_id == evidence.id,
            )
        )).scalar_one_or_none()
    if existing:
        existing.stance = stance
        existing.interpretation_method = "deterministic_reality_v2"
        existing.method_version = ENGINE_VERSION
        existing.interpretation_confidence = confidence
        existing.rationale = rationale
        existing.validated = True
        return False

    link = RadarClaimEvidence(
        claim_id=claim.id,
        evidence_id=evidence.id,
        stance=stance,
        interpretation_method="deterministic_reality_v2",
        method_version=ENGINE_VERSION,
        interpretation_confidence=confidence,
        rationale=rationale,
        validated=True,
    )
    session.add(link)
    if isinstance(link_cache, dict):
        link_cache[pair] = link
    if isinstance(rows_by_claim, dict):
        rows_by_claim.setdefault(int(claim.id), []).append((link, evidence))
    return True


async def _refresh_claim_state(session, claim: RadarClaim) -> None:
    info = _session_cache_info(session)
    rows_by_claim = info.get("signalforge_rows_by_claim")
    if isinstance(rows_by_claim, dict):
        rows = list(rows_by_claim.get(int(claim.id), []))
    else:
        rows = list((await session.execute(
            select(RadarClaimEvidence, RadarEvidence)
            .join(RadarEvidence, RadarEvidence.id == RadarClaimEvidence.evidence_id)
            .where(RadarClaimEvidence.claim_id == claim.id)
        )).all())

    # Only validated interpretations are allowed to affect claim truth.
    support = {
        ev.source_family_key
        for link, ev in rows
        if link.validated and link.stance == "SUPPORT"
    }
    refute = {
        ev.source_family_key
        for link, ev in rows
        if link.validated and link.stance == "REFUTE"
    }
    insufficient = sum(
        1
        for link, _ in rows
        if link.validated and link.stance in {"INSUFFICIENT", "RELATED"}
    )
    direct_support = {
        ev.source_family_key
        for link, ev in rows
        if (
            link.validated
            and link.stance == "SUPPORT"
            and ev.directness == "DIRECT"
        )
    }

    claim.support_groups = len(support)
    claim.direct_support_groups = len(direct_support)
    claim.refute_groups = len(refute)
    claim.insufficient_count = insufficient

    needed = max(1, int(claim.required_support_groups or 2))

    # C05 follows the same configured independent-evidence threshold as
    # every other strict ledger claim. A named hiring/budget signal is useful
    # evidence, but it must not silently override required_support_groups.
    #
    # This closes a historical inconsistency where opportunity_reality could
    # re-promote C05 to SUPPORTED with one family immediately after the
    # Quality Guard correctly downgraded it.
    if refute and len(support) >= needed:
        state = "CONFLICTED"
    elif refute and not support:
        state = "REFUTED"
    elif len(support) >= needed:
        state = "SUPPORTED"
    elif any(link.validated for link, _ in rows):
        state = "INSUFFICIENT"
    else:
        state = "UNKNOWN"

    claim.state = state
    claim.last_evaluated_at = datetime.utcnow()


async def run_opportunity_reality(case_ids: list[int] | None = None) -> dict[str, Any]:
    """Materialize market-context evidence for a bounded case scope.

    ``None`` preserves the historical full refresh. An explicit list is a
    strict execution scope; ``[]`` is a legal no-op. This is scheduling /
    freshness control only and does not weaken any evidence threshold.
    """
    now = datetime.utcnow()
    scope_explicit = case_ids is not None
    normalized_case_ids = sorted({int(x) for x in (case_ids or []) if int(x) > 0})
    if scope_explicit and not normalized_case_ids:
        return {
            "engine_version": ENGINE_VERSION,
            "cases": 0,
            "evidence_created": 0,
            "claim_links_created": 0,
            "cases_with_market_signal": 0,
            "cases_with_buyer_signal": 0,
            "cases_with_solution_signal": 0,
            "cases_with_timing_signal": 0,
            "market_corpus": {},
            "attention": [],
            "materialization_scope": {
                "mode": "EXPLICIT_ZERO",
                "case_ids": [],
                "case_count": 0,
                "truth_boundary": "SCOPE_CONTROLS_REFRESH_WORK_ONLY_NO_TRUTH_AUTHORITY",
            },
            "llm_calls": 0,
            "api_calls": 0,
            "llm_cost_twd": 0.0,
        }
    async with async_session() as session:
        stmt = (
            select(RadarCase, ProblemCandidate)
            .join(ProblemCandidate, ProblemCandidate.id == RadarCase.candidate_id)
            .order_by(RadarCase.id)
        )
        if scope_explicit:
            stmt = stmt.where(RadarCase.id.in_(normalized_case_ids))
        case_pairs = list((await session.execute(stmt)).all())
        cases = [x[0] for x in case_pairs]
        candidates = [x[1] for x in case_pairs]

        claims = list((await session.execute(
            select(RadarClaim).where(RadarClaim.case_id.in_([c.id for c in cases]))
        )).scalars().all())
        claim_map = {(c.case_id, c.claim_code): c for c in claims}

        jobs = list((await session.execute(select(JobListing))).scalars().all())
        repos = list((await session.execute(select(GithubRepo))).scalars().all())
        issues = list((await session.execute(select(GithubIssue))).scalars().all())
        news = list((await session.execute(select(NewsEvent))).scalars().all())
        yc = list((await session.execute(select(YCCompany))).scalars().all())
        packages = list((await session.execute(select(PackageDownload))).scalars().all())

        direct_evidence = list((await session.execute(
            select(RadarEvidence).where(RadarEvidence.case_id.in_([c.id for c in cases]))
        )).scalars().all())
        candidate_evidence_rows = list((await session.execute(
            select(CandidateEvidence).where(CandidateEvidence.candidate_id.in_([c.id for c in candidates]))
        )).scalars().all())

    case_by_candidate = {cand.id: case for case, cand in case_pairs}
    evidence_by_case = defaultdict(list)
    for ev in direct_evidence:
        evidence_by_case[ev.case_id].append(ev)
    prelinked_by_candidate = defaultdict(list)
    for ev in candidate_evidence_rows:
        prelinked_by_candidate[ev.candidate_id].append(ev)

    def safe_json(x):
        if isinstance(x, (list, dict)):
            return json.dumps(x, ensure_ascii=False)
        return str(x or "")

    job_docs = [{
        "id": r.id, "text": " ".join([r.title or "", r.company or "", r.description or "", safe_json(r.tags)]),
        "title": r.title or "", "url": r.url, "published_at": r.published_at,
        "company": r.company or "unknown", "row": r,
    } for r in jobs]

    repo_docs = [{
        "id": r.id, "text": " ".join([r.repo_full_name or "", r.description or "", safe_json(r.topics)]),
        "title": r.repo_full_name or r.name or "", "url": r.homepage_url,
        "published_at": r.pushed_at or r.updated_at, "row": r,
    } for r in repos]

    issue_docs = [{
        "id": r.id, "text": " ".join([r.repo_full_name or "", r.title or "", r.body or "", safe_json(r.labels)]),
        "title": r.title or "", "url": r.html_url, "published_at": r.updated_at or r.created_at,
        "repo": r.repo_full_name or "unknown", "state": (r.state or "").lower(), "row": r,
    } for r in issues]

    news_docs = [{
        "id": r.id, "text": " ".join([r.title or "", r.body or "", safe_json(r.categories)]),
        "title": r.title or "", "url": r.url, "published_at": r.published_at,
        "source_name": r.source_name or r.source_type or "unknown", "row": r,
    } for r in news]

    yc_docs = [{
        "id": r.id, "text": " ".join([r.name or "", r.description or "", r.long_description or "", safe_json(r.industries)]),
        "title": r.name or "", "url": r.website, "published_at": r.updated_at,
        "row": r,
    } for r in yc]

    # Package trend summaries, not individual daily rows.
    pkg_by_name = defaultdict(list)
    for p in packages:
        pkg_by_name[(p.registry or "unknown", p.package_name or "unknown")].append(p)
    package_docs = []
    for (registry, name), rows in pkg_by_name.items():
        rows = sorted(rows, key=lambda x: x.date or datetime.min.date())
        recent = sum(int(x.downloads or 0) for x in rows[-30:])
        previous = sum(int(x.downloads or 0) for x in rows[-60:-30]) if len(rows) > 30 else 0
        growth = None
        if previous > 0:
            growth = (recent - previous) / previous
        package_docs.append({
            "id": f"{registry}:{name}", "text": f"{registry} {name}", "title": f"{registry}:{name}",
            "url": None, "published_at": None, "registry": registry, "name": name,
            "recent_downloads": recent, "previous_downloads": previous, "growth": growth,
        })

    matches = {
        "jobs": _match_rows(candidates, job_docs, threshold=0.12, top_k=5, role="buyer"),
        "repos": _match_rows(candidates, repo_docs, threshold=0.13, top_k=5, role="competition"),
        "issues": _match_rows(candidates, issue_docs, threshold=0.14, top_k=6, role="solution"),
        "news": _match_rows(candidates, news_docs, threshold=0.11, top_k=5, role="timing"),
        "yc": _match_rows(candidates, yc_docs, threshold=0.13, top_k=4, role="competition"),
        "packages": _match_rows(candidates, package_docs, threshold=0.16, top_k=4, role="package"),
    }

    coverage = None
    if coverage_snapshot is not None:
        try:
            coverage = await coverage_snapshot(case_pairs)
        except Exception:
            coverage = None
    coverage_by_case = {}
    if coverage:
        coverage_by_case = {r["case_id"]: r for r in coverage.get("cases", [])}

    created_links = 0
    created_evidence = 0
    signal_summary: dict[int, dict[str, Any]] = {}

    async with async_session() as session:
        # Re-fetch ORM rows in this session.
        session_stmt = (
            select(RadarCase, ProblemCandidate)
            .join(ProblemCandidate, ProblemCandidate.id == RadarCase.candidate_id)
            .order_by(RadarCase.id)
        )
        if scope_explicit:
            session_stmt = session_stmt.where(RadarCase.id.in_(normalized_case_ids))
        session_pairs = list((await session.execute(session_stmt)).all())
        session_claims = list((await session.execute(
            select(RadarClaim).where(RadarClaim.case_id.in_([c.id for c, _ in session_pairs]))
        )).scalars().all())
        claim_map = {(c.case_id, c.claim_code): c for c in session_claims}
        await _prime_reality_session_caches(
            session,
            claim_ids=[int(c.id) for c in session_claims],
        )
        cache_info = _session_cache_info(session)
        evidence_cache = cache_info.get("signalforge_evidence_cache") or {}
        existing_evidence_keys = set(evidence_cache)

        for case, cand in session_pairs:
            cid = cand.id
            summary = {
                "buyer_companies": set(), "buyer_signals": 0,
                "solution_repos": set(), "solution_issues": 0,
                "open_solution_issues": 0, "solution_supply": 0,
                "timing_signals": 0, "package_growth_signals": 0,
                "severity_signals": 0, "latest_evidence": None,
            }

            # High-precision evidence already linked to this candidate by earlier
            # cross-source processors. Re-use it before fuzzy market retrieval.
            for pev in prelinked_by_candidate.get(cid, []):
                relation = str(pev.relation or "").lower()
                if relation not in {"buyer_demand", "why_now", "research_enabler"}:
                    continue
                ev_key = f"reality:{_hash_key(case.id, pev.source_type or 'candidate_evidence', pev.source_table or 'candidate_evidence', str(pev.source_ref or pev.id))}"
                was_new = ev_key not in existing_evidence_keys
                authority = (
                    "BUYER_DEMAND_SIGNAL" if relation == "buyer_demand"
                    else "TIMING_CONTEXT"
                )
                rev = await _ensure_evidence(
                    session,
                    case.id,
                    source_type=pev.source_type or "candidate_evidence",
                    source_table=pev.source_table or "candidate_evidence",
                    source_ref=str(pev.source_ref or pev.id),
                    source_title=pev.title,
                    excerpt=pev.excerpt,
                    source_url=pev.url,
                    source_family_key=f"prelinked:{relation}:{_family_slug(pev.source_type or '')}:{pev.id}",
                    authority_class=authority,
                    directness="RELATED",
                    published_at=None,
                    metadata={
                        "candidate_evidence_id": pev.id,
                        "relation": relation,
                        "retrieval_score": pev.retrieval_score,
                        "verified": bool(pev.verified),
                    },
                )
                if was_new:
                    created_evidence += 1
                    existing_evidence_keys.add(ev_key)

                if relation == "buyer_demand":
                    summary["buyer_signals"] += 1
                    summary["buyer_companies"].add(pev.source_type or "prelinked buyer signal")
                    c05_pre = claim_map.get((case.id, "C05"))
                    if c05_pre:
                        new = await _link_claim(
                            session,
                            c05_pre,
                            rev,
                            stance="INSUFFICIENT",
                            rationale="Pre-linked buyer-demand evidence exists, but it is not by itself direct willingness-to-pay proof.",
                            confidence=0.62,
                        )
                        created_links += int(new)
                else:
                    summary["timing_signals"] += 1
                    c12_pre = claim_map.get((case.id, "C12"))
                    if c12_pre:
                        new = await _link_claim(
                            session,
                            c12_pre,
                            rev,
                            stance="INSUFFICIENT",
                            rationale="Pre-linked why-now/research-enabler evidence supports timing context; execution duration is still unknown.",
                            confidence=0.60,
                        )
                        created_links += int(new)

            # C03 — consequence material: use only direct/first-hand case evidence.
            c03 = claim_map.get((case.id, "C03"))
            if c03:
                for ev in evidence_by_case.get(case.id, []):
                    text = " ".join([ev.source_title or "", ev.excerpt or ""])
                    if ev.directness == "DIRECT":
                        is_material = _material_consequence_support(
                            cand.consequence or "", text
                        )
                        new = await _link_claim(
                            session,
                            c03,
                            ev,
                            stance="SUPPORT" if is_material else "INSUFFICIENT",
                            rationale=(
                                "Direct first-hand evidence contains a concrete material "
                                "operational/economic consequence aligned to the candidate."
                                if is_material
                                else "Direct problem evidence exists, but it lacks a concrete "
                                "material consequence; generic failure/annoyance cannot prove C03."
                            ),
                            confidence=0.88 if is_material else 0.70,
                        )
                        created_links += int(new)
                        summary["severity_signals"] += int(is_material)

            # C05 — buyer exists: strong job matches from independent companies.
            c05 = claim_map.get((case.id, "C05"))
            for m in matches["jobs"].get(cid, []):
                company = m.get("company") or "unknown"
                ev_key = f"reality:{_hash_key(case.id, 'job', m['id'])}"
                was_new = ev_key not in existing_evidence_keys
                ev = await _ensure_evidence(
                    session, case.id, source_type="jobs", source_table="job_listings",
                    source_ref=str(m["id"]), source_title=m["title"], excerpt=m["text"], source_url=m.get("url"),
                    source_family_key=f"jobs:{_family_slug(company)}", authority_class="BUYER_BUDGET_SIGNAL",
                    directness="RELATED", published_at=m.get("published_at"),
                    metadata={"retrieval_score": m["retrieval_score"], "lexical_score": m.get("lexical_score"), "semantic_score": m.get("semantic_score"), "shared_terms": m["shared_terms"], "rare_shared": m.get("rare_shared", []), "domain_shared": m.get("domain_shared", []), "company": company},
                )
                if was_new:
                    created_evidence += 1; existing_evidence_keys.add(ev_key)
                summary["buyer_companies"].add(company)
                summary["buyer_signals"] += 1
                if c05:
                    # Hiring is budget allocation, but not willingness-to-pay proof.
                    buyer_language = _has_any(m["text"], BUYER_PATTERNS)
                    strong_buyer_match = bool(m.get("named_shared")) or len(m.get("rare_shared", [])) >= 2 or (m.get("domain_shared") and m.get("semantic_score", 0) >= 0.34)
                    # Generic market retrieval is candidate/context generation only.
                    # C05 SUPPORT is owned by focused buyer adjudication because broad
                    # job matching produced unacceptable false positives.
                    stance = "INSUFFICIENT"
                    new = await _link_claim(
                        session, c05, ev, stance=stance,
                        rationale=(
                            "Related hiring/budget context exists, but generic market "
                            "retrieval is not allowed to prove C05. Focused named-buyer "
                            "adjudication is required."
                        ),
                        confidence=0.55,
                    )
                    created_links += int(new)

            # C06/C07 — current solution unsatisfactory + unresolved gap.
            c06 = claim_map.get((case.id, "C06"))
            c07 = claim_map.get((case.id, "C07"))
            for m in matches["issues"].get(cid, []):
                text = m["text"]
                repo = m.get("repo") or "unknown"
                is_unsat = _has_any(text, UNSAT_PATTERNS)
                open_issue = m.get("state") == "open"
                strong_identity = bool(m.get("named_shared")) or len(m.get("rare_shared", [])) >= 2 or (m.get("domain_shared") and m.get("semantic_score", 0) >= 0.36)
                ev_key = f"reality:{_hash_key(case.id, 'github_issue', m['id'])}"
                was_new = ev_key not in existing_evidence_keys
                ev = await _ensure_evidence(
                    session, case.id, source_type="github_issue", source_table="github_issues",
                    source_ref=str(m["id"]), source_title=m["title"], excerpt=text, source_url=m.get("url"),
                    source_family_key=f"github_solution:{_family_slug(repo)}", authority_class="SOLUTION_USER_ISSUE",
                    directness="DIRECT" if is_unsat and strong_identity else "RELATED", published_at=m.get("published_at"),
                    metadata={"retrieval_score": m["retrieval_score"], "lexical_score": m.get("lexical_score"), "semantic_score": m.get("semantic_score"), "shared_terms": m["shared_terms"], "rare_shared": m.get("rare_shared", []), "domain_shared": m.get("domain_shared", []), "repo": repo, "state": m.get("state")},
                )
                if was_new:
                    created_evidence += 1; existing_evidence_keys.add(ev_key)
                summary["solution_repos"].add(repo)
                summary["solution_issues"] += 1
                summary["open_solution_issues"] += int(open_issue)

                if c06:
                    new = await _link_claim(
                        session,
                        c06,
                        ev,
                        stance="INSUFFICIENT",
                        rationale=(
                            "Generic solution retrieval found failure context, but it "
                            "cannot prove C06. Focused solution-evidence adjudication "
                            "with independent evidence families is required."
                        ),
                        confidence=0.52,
                    )
                    created_links += int(new)

                if c07:
                    new = await _link_claim(
                        session,
                        c07,
                        ev,
                        stance="INSUFFICIENT",
                        rationale=(
                            "Generic open-issue context cannot prove persistence of "
                            "the same unresolved gap. Focused C07 adjudication is required."
                        ),
                        confidence=0.50,
                    )
                    created_links += int(new)

            # Existing solution / competition context (does not prove C06).
            for m in matches["repos"].get(cid, []):
                r = m["row"]
                summary["solution_supply"] += 1
                summary["solution_repos"].add(r.repo_full_name or "unknown")
                ev_key = f"reality:{_hash_key(case.id, 'github_repo', m['id'])}"
                was_new = ev_key not in existing_evidence_keys
                await _ensure_evidence(
                    session, case.id, source_type="github_repo", source_table="github_repos",
                    source_ref=str(m["id"]), source_title=m["title"], excerpt=m["text"], source_url=m.get("url"),
                    source_family_key=f"solution_repo:{_family_slug(r.repo_full_name or '')}", authority_class="SOLUTION_SUPPLY",
                    directness="RELATED", published_at=m.get("published_at"),
                    metadata={"retrieval_score": m["retrieval_score"], "semantic_score": m.get("semantic_score"), "domain_shared": m.get("domain_shared", []), "stars": r.stars, "open_issues": r.open_issues},
                )
                if was_new:
                    created_evidence += 1; existing_evidence_keys.add(ev_key)

            for m in matches["yc"].get(cid, []):
                summary["solution_supply"] += 1
                r = m["row"]
                ev_key = f"reality:{_hash_key(case.id, 'yc', m['id'])}"
                was_new = ev_key not in existing_evidence_keys
                await _ensure_evidence(
                    session, case.id, source_type="yc_company", source_table="yc_companies",
                    source_ref=str(m["id"]), source_title=m["title"], excerpt=m["text"], source_url=m.get("url"),
                    source_family_key=f"yc:{_family_slug(r.name or '')}", authority_class="MARKET_SUPPLY",
                    directness="RELATED", published_at=m.get("published_at"),
                    metadata={"retrieval_score": m["retrieval_score"], "semantic_score": m.get("semantic_score"), "domain_shared": m.get("domain_shared", []), "batch": r.batch, "status": r.status},
                )
                if was_new:
                    created_evidence += 1; existing_evidence_keys.add(ev_key)

            # C12 — timing context only. It cannot be SUPPORTED without execution-time evidence.
            c12 = claim_map.get((case.id, "C12"))
            for m in matches["news"].get(cid, []):
                pub = m.get("published_at")
                recent = isinstance(pub, datetime) and pub >= now - timedelta(days=90)
                if not recent and not _has_any(m["text"], TIMING_PATTERNS):
                    continue
                summary["timing_signals"] += 1
                ev_key = f"reality:{_hash_key(case.id, 'news', m['id'])}"
                was_new = ev_key not in existing_evidence_keys
                ev = await _ensure_evidence(
                    session, case.id, source_type="news", source_table="news_events",
                    source_ref=str(m["id"]), source_title=m["title"], excerpt=m["text"], source_url=m.get("url"),
                    source_family_key=f"timing_news:{_family_slug(m.get('source_name') or '')}", authority_class="TIMING_CONTEXT",
                    directness="RELATED", published_at=pub,
                    metadata={"retrieval_score": m["retrieval_score"], "semantic_score": m.get("semantic_score"), "domain_shared": m.get("domain_shared", []), "shared_terms": m["shared_terms"]},
                )
                if was_new:
                    created_evidence += 1; existing_evidence_keys.add(ev_key)
                if c12:
                    new = await _link_claim(
                        session, c12, ev, stance="INSUFFICIENT",
                        rationale="Recent market/timing activity is relevant, but window-outlasts-execution cannot be established without an execution-time estimate.",
                        confidence=0.60,
                    )
                    created_links += int(new)

            for m in matches["packages"].get(cid, []):
                growth = m.get("growth")
                if growth is None or growth < 0.25 or m.get("recent_downloads", 0) < 100:
                    continue
                summary["package_growth_signals"] += 1
                summary["timing_signals"] += 1
                ev_key = f"reality:{_hash_key(case.id, 'package', m['id'])}"
                was_new = ev_key not in existing_evidence_keys
                ev = await _ensure_evidence(
                    session, case.id, source_type="package_growth", source_table="package_downloads",
                    source_ref=str(m["id"]), source_title=m["title"], excerpt=f"recent={m['recent_downloads']} previous={m['previous_downloads']} growth={growth:.2%}", source_url=None,
                    source_family_key=f"package:{_family_slug(m['id'])}", authority_class="ADOPTION_TIMING_SIGNAL",
                    directness="RELATED", published_at=None,
                    metadata={"growth": growth, "recent_downloads": m["recent_downloads"], "previous_downloads": m["previous_downloads"]},
                )
                if was_new:
                    created_evidence += 1; existing_evidence_keys.add(ev_key)
                if c12:
                    new = await _link_claim(
                        session, c12, ev, stance="INSUFFICIENT",
                        rationale="Matched package adoption is accelerating, which is a timing signal; execution duration is still unknown.",
                        confidence=0.64,
                    )
                    created_links += int(new)

            # C09 — do not infer company capability from market evidence.
            c09 = claim_map.get((case.id, "C09"))
            if c09:
                es = dict(c09.evidence_summary or {})
                es.update({
                    "reality_v1": {
                        "status": "MISSING_COMPANY_CAPABILITY_INPUT",
                        "reason": "Radar market data cannot prove the founder/company can execute this opportunity.",
                    }
                })
                c09.evidence_summary = es
                if c09.state == "UNKNOWN":
                    c09.state = "INSUFFICIENT"
                c09.insufficient_count = max(1, int(c09.insufficient_count or 0))
                c09.last_evaluated_at = now

            signal_summary[case.id] = summary

        # Refresh only target claims, preserving recurrence and other gates.
        for claim in session_claims:
            if claim.claim_code in {"C03", "C05", "C06", "C07", "C12"}:
                await _refresh_claim_state(session, claim)

        # Attach compact machine-readable summary to each target claim.
        for case, _ in session_pairs:
            s = signal_summary.get(case.id, {})
            for code in {"C03", "C05", "C06", "C07", "C12"}:
                claim = claim_map.get((case.id, code))
                if not claim:
                    continue
                es = dict(claim.evidence_summary or {})
                es["reality_v1"] = {
                    "buyer_companies": sorted(s.get("buyer_companies", set()))[:12],
                    "buyer_signals": s.get("buyer_signals", 0),
                    "solution_repos": sorted(s.get("solution_repos", set()))[:12],
                    "solution_issues": s.get("solution_issues", 0),
                    "open_solution_issues": s.get("open_solution_issues", 0),
                    "solution_supply": s.get("solution_supply", 0),
                    "timing_signals": s.get("timing_signals", 0),
                    "package_growth_signals": s.get("package_growth_signals", 0),
                    "severity_signals": s.get("severity_signals", 0),
                }
                claim.evidence_summary = es

        await session.commit()

    # Build final attention view using refreshed claims.
    async with async_session() as session:
        final_stmt = (
            select(RadarCase, ProblemCandidate)
            .join(ProblemCandidate, ProblemCandidate.id == RadarCase.candidate_id)
            .order_by(RadarCase.id)
        )
        if scope_explicit:
            final_stmt = final_stmt.where(RadarCase.id.in_(normalized_case_ids))
        pairs = list((await session.execute(final_stmt)).all())
        claims2 = list((await session.execute(
            select(RadarClaim).where(RadarClaim.case_id.in_([c.id for c, _ in pairs]))
        )).scalars().all())
    claim_state = {(x.case_id, x.claim_code): x.state for x in claims2}
    claim_summary = {(x.case_id, x.claim_code): (x.evidence_summary or {}) for x in claims2}

    # Focused research may produce validated C05 support that was not inside
    # the generic top-k job matcher. Surface those concrete organizations in
    # Founder Radar instead of losing them on the next reality refresh.
    c05_claim_ids = {
        x.id: x.case_id for x in claims2 if x.claim_code == "C05"
    }
    researched_buyers = defaultdict(set)
    if c05_claim_ids:
        async with async_session() as session:
            buyer_rows = list((await session.execute(
                select(RadarClaimEvidence, RadarEvidence)
                .join(
                    RadarEvidence,
                    RadarEvidence.id == RadarClaimEvidence.evidence_id,
                )
                .where(
                    RadarClaimEvidence.claim_id.in_(list(c05_claim_ids)),
                    RadarClaimEvidence.stance == "SUPPORT",
                    RadarClaimEvidence.validated == True,  # noqa: E712
                    RadarEvidence.authority_class == "BUYER_BUDGET_SIGNAL",
                )
            )).all())
        for link, ev in buyer_rows:
            company = str((ev.raw_metadata or {}).get("company") or "").strip()
            if company and company.lower() not in {"unknown", "none"}:
                researched_buyers[c05_claim_ids[link.claim_id]].add(company)

    attention = []
    for case, cand in pairs:
        s = signal_summary.get(case.id, {})
        cov = coverage_by_case.get(case.id, {})
        cov_level = cov.get("level", "UNKNOWN")
        c03 = claim_state.get((case.id, "C03"), "UNKNOWN")
        c05 = claim_state.get((case.id, "C05"), "UNKNOWN")
        c06 = claim_state.get((case.id, "C06"), "UNKNOWN")
        c07 = claim_state.get((case.id, "C07"), "UNKNOWN")
        c12 = claim_state.get((case.id, "C12"), "UNKNOWN")

        score = 0
        last_seen = cand.last_seen_at or cand.updated_at or cand.created_at
        if isinstance(last_seen, datetime):
            age = max(0, (now - last_seen).days)
            score += 25 if age <= 7 else 18 if age <= 30 else 8 if age <= 90 else 2
        score += 20 if c03 == "SUPPORTED" else min(10, s.get("severity_signals", 0) * 4)
        score += 18 if c05 == "SUPPORTED" else min(9, len(s.get("buyer_companies", set())) * 3)
        score += 14 if c06 == "SUPPORTED" else min(7, s.get("solution_issues", 0) * 2)
        score += 13 if c07 == "SUPPORTED" else min(6, s.get("open_solution_issues", 0) * 2)
        score += min(10, s.get("timing_signals", 0) * 2)
        score += {"SATURATED": 8, "PARTIAL": 5, "GAP": 2}.get(cov_level, 1)
        score = min(100, int(score))

        next_action = "continue automated evidence search"
        if c05 in {"UNKNOWN", "INSUFFICIENT"}:
            next_action = "find direct buyer / budget / willingness-to-pay evidence"
        elif c06 in {"UNKNOWN", "INSUFFICIENT"}:
            next_action = "search current-solution complaints and workaround evidence"
        elif c07 in {"UNKNOWN", "INSUFFICIENT"}:
            next_action = "verify whether the solution gap remains unresolved"
        elif c12 in {"UNKNOWN", "INSUFFICIENT"}:
            next_action = "estimate opportunity window and execution time"

        all_buyer_companies = (
            set(s.get("buyer_companies", set()))
            | set(researched_buyers.get(case.id, set()))
        )

        attention.append({
            "case_id": case.id,
            "title": cand.title,
            "problem_statement": cand.problem_statement,
            "system_verdict": case.system_verdict,
            "attention_score": score,
            "coverage": cov_level,
            "claims": {"C03": c03, "C05": c05, "C06": c06, "C07": c07, "C09": claim_state.get((case.id, "C09"), "UNKNOWN"), "C12": c12},
            "buyer_companies": sorted(all_buyer_companies)[:5],
            "solution_issues": s.get("solution_issues", 0),
            "open_solution_issues": s.get("open_solution_issues", 0),
            "solution_supply": s.get("solution_supply", 0),
            "timing_signals": s.get("timing_signals", 0),
            "next_machine_action": next_action,
        })

    attention.sort(key=lambda x: (-x["attention_score"], x["title"] or ""))

    cases_with_market_signal = sum(1 for s in signal_summary.values() if (s.get("buyer_signals", 0) + s.get("solution_issues", 0) + s.get("solution_supply", 0) + s.get("timing_signals", 0)) > 0)
    cases_with_buyer_signal = sum(
        1
        for case, _ in pairs
        if (
            signal_summary.get(case.id, {}).get("buyer_signals", 0) > 0
            or claim_state.get((case.id, "C05"), "UNKNOWN") == "SUPPORTED"
        )
    )
    cases_with_solution_signal = sum(1 for s in signal_summary.values() if (s.get("solution_issues", 0) + s.get("solution_supply", 0)) > 0)
    cases_with_timing_signal = sum(1 for s in signal_summary.values() if s.get("timing_signals", 0) > 0)
    result = {
        "engine_version": ENGINE_VERSION,
        "cases": len(candidates),
        "evidence_created": created_evidence,
        "claim_links_created": created_links,
        "cases_with_market_signal": cases_with_market_signal,
        "cases_with_buyer_signal": cases_with_buyer_signal,
        "cases_with_solution_signal": cases_with_solution_signal,
        "cases_with_timing_signal": cases_with_timing_signal,
        "market_corpus": {"jobs": len(job_docs), "repos": len(repo_docs), "issues": len(issue_docs), "news": len(news_docs), "yc": len(yc_docs), "packages": len(package_docs), "prelinked": len(candidate_evidence_rows)},
        "materialization_scope": {
            "mode": "SCOPED" if scope_explicit else "FULL",
            "case_ids": normalized_case_ids if scope_explicit else [int(case.id) for case, _ in pairs],
            "case_count": len(pairs),
            "truth_boundary": "SCOPE_CONTROLS_REFRESH_WORK_ONLY_NO_TRUTH_AUTHORITY",
        },
        "attention": attention,
        "llm_calls": 0,
        "api_calls": 0,
        "llm_cost_twd": 0.0,
    }
    return result


async def read_persisted_opportunity_reality() -> dict[str, Any]:
    """Build the Decision attention surface from already-published evidence.

    This is the normal final-decision path after a research round when no raw
    source/candidate corpus changed. The expensive fuzzy market retriever is a
    *materializer*, not a prerequisite for every deterministic decision.

    Truth rules are unchanged: current RadarClaim state remains authoritative;
    this function only reconstructs the market/attention context from durable
    RadarEvidence + the last reality summaries. If raw sources or discovery
    changed in the current cycle, the orchestrator still calls the full
    run_opportunity_reality() materializer once.
    """
    now = datetime.utcnow()
    async with async_session() as session:
        pairs = list((await session.execute(
            select(RadarCase, ProblemCandidate)
            .join(ProblemCandidate, ProblemCandidate.id == RadarCase.candidate_id)
            .order_by(RadarCase.id)
        )).all())
        case_ids = [int(case.id) for case, _ in pairs]
        claims = list((await session.execute(
            select(RadarClaim).where(RadarClaim.case_id.in_(case_ids))
        )).scalars().all()) if case_ids else []
        evidence = list((await session.execute(
            select(RadarEvidence).where(RadarEvidence.case_id.in_(case_ids))
        )).scalars().all()) if case_ids else []
        actions = list((await session.execute(
            select(RadarResearchAction).where(
                RadarResearchAction.case_id.in_(case_ids),
                RadarResearchAction.claim_code == "C02",
            )
        )).scalars().all()) if case_ids else []

    claim_map = {(int(c.case_id), str(c.claim_code)): c for c in claims}
    evidence_by_case: dict[int, list[RadarEvidence]] = defaultdict(list)
    for ev in evidence:
        evidence_by_case[int(ev.case_id)].append(ev)

    coverage_by_case: dict[int, str] = {}
    # One C02 action per case is expected; if historical duplicates exist, the
    # most recently attempted record wins.
    actions.sort(
        key=lambda a: (
            getattr(a, "last_attempt_at", None) or datetime.min,
            int(getattr(a, "id", 0) or 0),
        )
    )
    for action in actions:
        md = dict(getattr(action, "result_metadata", None) or {})
        cov = dict(md.get("coverage") or {})
        level = str(cov.get("level") or "").upper()
        if level in {"SATURATED", "PARTIAL", "GAP", "LEGACY_ONLY"}:
            coverage_by_case[int(action.case_id)] = level

    attention: list[dict[str, Any]] = []
    signal_summary: dict[int, dict[str, Any]] = {}

    for case, cand in pairs:
        cid = int(case.id)
        claims_by_code = {
            code: claim_map.get((cid, code))
            for code in TARGET_CLAIMS
        }
        # M17 wrote the same compact reality_v1 block to target claims. Use the
        # freshest available block as a floor, then merge newly focused evidence
        # written after that materialization.
        summary: dict[str, Any] = {}
        latest_eval = datetime.min
        for claim in claims_by_code.values():
            if claim is None:
                continue
            block = dict((claim.evidence_summary or {}).get("reality_v1") or {})
            evaluated = getattr(claim, "last_evaluated_at", None) or datetime.min
            if block and evaluated >= latest_eval:
                summary = {
                    "buyer_companies": set(block.get("buyer_companies") or []),
                    "buyer_signals": int(block.get("buyer_signals", 0) or 0),
                    "solution_repos": set(block.get("solution_repos") or []),
                    "solution_issues": int(block.get("solution_issues", 0) or 0),
                    "open_solution_issues": int(block.get("open_solution_issues", 0) or 0),
                    "solution_supply": int(block.get("solution_supply", 0) or 0),
                    "timing_signals": int(block.get("timing_signals", 0) or 0),
                    "package_growth_signals": int(block.get("package_growth_signals", 0) or 0),
                    "severity_signals": int(block.get("severity_signals", 0) or 0),
                }
                latest_eval = evaluated
        if not summary:
            summary = {
                "buyer_companies": set(), "buyer_signals": 0,
                "solution_repos": set(), "solution_issues": 0,
                "open_solution_issues": 0, "solution_supply": 0,
                "timing_signals": 0, "package_growth_signals": 0,
                "severity_signals": 0,
            }

        seen_buyer = set(str(x).lower() for x in summary["buyer_companies"])
        seen_solution_failure = set()
        seen_solution_supply = set()
        seen_timing = set()
        for ev in evidence_by_case.get(cid, []):
            authority = str(ev.authority_class or "").upper()
            source_type = str(ev.source_type or "").lower()
            family = str(ev.source_family_key or ev.evidence_key or ev.id)
            md = dict(ev.raw_metadata or {})
            if authority == "BUYER_BUDGET_SIGNAL":
                company = str(md.get("company") or "").strip()
                if company and company.lower() not in {"unknown", "none"}:
                    summary["buyer_companies"].add(company)
                    seen_buyer.add(company.lower())
                summary["buyer_signals"] = max(summary["buyer_signals"], len(seen_buyer))
            if authority == "CURRENT_SOLUTION_FAILURE":
                seen_solution_failure.add(family)
                solution = str(md.get("solution_identity") or md.get("repo") or "").strip()
                if solution:
                    summary["solution_repos"].add(solution)
                if str(md.get("state") or "").lower() == "open":
                    summary["open_solution_issues"] = max(
                        summary["open_solution_issues"], len(seen_solution_failure)
                    )
            if authority in {"SOLUTION_SUPPLY", "MARKET_SUPPLY"}:
                seen_solution_supply.add(family)
            if authority in {"TIMING_CONTEXT", "ADOPTION_TIMING_SIGNAL"}:
                seen_timing.add(family)
                if authority == "ADOPTION_TIMING_SIGNAL":
                    summary["package_growth_signals"] = max(
                        summary["package_growth_signals"], len(seen_timing)
                    )

        summary["solution_issues"] = max(
            summary["solution_issues"], len(seen_solution_failure)
        )
        summary["solution_supply"] = max(
            summary["solution_supply"], len(seen_solution_supply)
        )
        summary["timing_signals"] = max(
            summary["timing_signals"], len(seen_timing)
        )
        signal_summary[cid] = summary

        def cstate(code: str) -> str:
            claim = claim_map.get((cid, code))
            return str(claim.state if claim else "UNKNOWN").upper()

        cov_level = coverage_by_case.get(cid, "UNKNOWN")
        c03, c05, c06, c07, c12 = (
            cstate("C03"), cstate("C05"), cstate("C06"),
            cstate("C07"), cstate("C12"),
        )
        score = 0
        last_seen = cand.last_seen_at or cand.updated_at or cand.created_at
        if isinstance(last_seen, datetime):
            # DB timestamps in this project are normally naive UTC. Preserve the
            # original scoring behavior while tolerating aware values.
            try:
                ref_now = datetime.now(last_seen.tzinfo) if last_seen.tzinfo else now
                age = max(0, (ref_now - last_seen).days)
                score += 25 if age <= 7 else 18 if age <= 30 else 8 if age <= 90 else 2
            except Exception:
                score += 2
        score += 20 if c03 == "SUPPORTED" else min(10, summary["severity_signals"] * 4)
        score += 18 if c05 == "SUPPORTED" else min(9, len(summary["buyer_companies"]) * 3)
        score += 14 if c06 == "SUPPORTED" else min(7, summary["solution_issues"] * 2)
        score += 13 if c07 == "SUPPORTED" else min(6, summary["open_solution_issues"] * 2)
        score += min(10, summary["timing_signals"] * 2)
        score += {"SATURATED": 8, "PARTIAL": 5, "GAP": 2}.get(cov_level, 1)
        score = min(100, int(score))

        next_action = "continue automated evidence search"
        if c05 in {"UNKNOWN", "INSUFFICIENT"}:
            next_action = "find direct buyer / budget / willingness-to-pay evidence"
        elif c06 in {"UNKNOWN", "INSUFFICIENT"}:
            next_action = "search current-solution complaints and workaround evidence"
        elif c07 in {"UNKNOWN", "INSUFFICIENT"}:
            next_action = "verify whether the solution gap remains unresolved"
        elif c12 in {"UNKNOWN", "INSUFFICIENT"}:
            next_action = "estimate opportunity window and execution time"

        attention.append({
            "case_id": cid,
            "title": cand.title,
            "problem_statement": cand.problem_statement,
            "system_verdict": case.system_verdict,
            "attention_score": score,
            "coverage": cov_level,
            "claims": {
                "C03": c03, "C05": c05, "C06": c06, "C07": c07,
                "C09": cstate("C09"), "C12": c12,
            },
            "buyer_companies": sorted(summary["buyer_companies"])[:5],
            "solution_issues": summary["solution_issues"],
            "open_solution_issues": summary["open_solution_issues"],
            "solution_supply": summary["solution_supply"],
            "timing_signals": summary["timing_signals"],
            "next_machine_action": next_action,
        })

    attention.sort(key=lambda x: (-x["attention_score"], x["title"] or ""))
    cases_with_market_signal = sum(
        1 for s in signal_summary.values()
        if s["buyer_signals"] + s["solution_issues"] + s["solution_supply"] + s["timing_signals"] > 0
    )
    return {
        "engine_version": ENGINE_VERSION,
        "mode": "PERSISTED_EVIDENCE_SNAPSHOT",
        "cases": len(pairs),
        "evidence_created": 0,
        "claim_links_created": 0,
        "cases_with_market_signal": cases_with_market_signal,
        "cases_with_buyer_signal": sum(
            1 for case, _ in pairs
            if signal_summary[int(case.id)]["buyer_signals"] > 0
            or str(getattr(claim_map.get((int(case.id), "C05")), "state", "UNKNOWN") or "UNKNOWN").upper() == "SUPPORTED"
        ),
        "cases_with_solution_signal": sum(
            1 for s in signal_summary.values()
            if s["solution_issues"] + s["solution_supply"] > 0
        ),
        "cases_with_timing_signal": sum(
            1 for s in signal_summary.values() if s["timing_signals"] > 0
        ),
        "market_corpus": {"mode": "persisted_evidence", "evidence_rows": len(evidence)},
        "attention": attention,
        "llm_calls": 0,
        "api_calls": 0,
        "llm_cost_twd": 0.0,
    }


async def print_founder_daily(limit: int = 10) -> dict[str, Any]:
    result = await run_opportunity_reality()
    attention = result["attention"][:limit]

    print("\n" + "=" * 112)
    print("FOUNDER DAILY RADAR — EARLY SIGNAL / REALITY V2")
    print("=" * 112)
    print("This is an ATTENTION ranking, not an opportunity-value score and not a BUILD recommendation.")
    print(f"Cases evaluated:       {result['cases']}")
    print(f"Evidence created:      {result['evidence_created']}")
    print(f"Claim links created:   {result['claim_links_created']}")
    corpus = result["market_corpus"]
    print(f"Market corpus:           jobs={corpus['jobs']} repos={corpus['repos']} issues={corpus['issues']} news={corpus['news']} yc={corpus['yc']} packages={corpus['packages']} prelinked={corpus['prelinked']}")
    print(f"Cases with market signal:   {result['cases_with_market_signal']}/{result['cases']}")
    print(f"  buyer / solution / timing: {result['cases_with_buyer_signal']} / {result['cases_with_solution_signal']} / {result['cases_with_timing_signal']}")
    print("LLM/API calls:         0 / 0")
    print("AI cost:               NT$0.00")

    for i, row in enumerate(attention, 1):
        claims = row["claims"]
        print("\n" + "-" * 112)
        print(f"#{i:02d} [{row['system_verdict']}] attention={row['attention_score']:3d} coverage={row['coverage']}")
        print(row["title"])
        if row.get("problem_statement"):
            print("Problem:", str(row["problem_statement"])[:340])
        print(
            "Reality: "
            f"pain={claims['C03']} | buyer={claims['C05']} | solution_unsat={claims['C06']} | "
            f"gap={claims['C07']} | company={claims['C09']} | window={claims['C12']}"
        )
        signal_count = len(row["buyer_companies"]) + row["solution_issues"] + row["solution_supply"] + row["timing_signals"]
        print("Signal richness:", "MARKET-LINKED" if signal_count > 0 else "PROBLEM-ONLY")
        if row["buyer_companies"]:
            print("Buyer signals:", ", ".join(row["buyer_companies"]))
        print(
            "Local market signals: "
            f"solution_issues={row['solution_issues']} open={row['open_solution_issues']} "
            f"solution_supply={row['solution_supply']} timing={row['timing_signals']}"
        )
        print("Next machine action:", row["next_machine_action"])

    print("\n" + "=" * 112)
    print("Safety: no WATCH was promoted merely because of attention score; C02/claim gates remain authoritative.")
    print("=" * 112)
    return result


if __name__ == "__main__":
    import asyncio
    asyncio.run(print_founder_daily())
