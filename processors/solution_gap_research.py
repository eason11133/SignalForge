"""Radar Solution + Gap Reality Closure V1.

Closes the next two INVESTIGATE gates:

C06 current_solution_unsatisfactory
C07 unresolved_gap_exists

Evidence sources are already-collected local data:
- GitHub issues (named solution/project identity)
- direct external problem items matched to the candidate
- existing case RadarEvidence

Method:
1. deterministic retrieval + explicit failure/persistence checks
2. narrow AI only for a small already-retrieved shortlist
3. validated evidence links written to the Evidence Ledger
4. explicit source-set exhaustion, never fake REFUTE

No web search is performed by the AI.
No threshold change can promote BUILD.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections import defaultdict
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any

from sqlalchemy import select

from database.connection import (
    async_session,
    ProblemCandidate,
    RadarCase,
    RadarClaim,
    RadarEvidence,
    RadarAIBudgetLedger,
    GithubIssue,
    ExternalProblemItem,
    ProductReview,
    Post,
)
from processors.ai_budget_gate import evaluate_ai_gate
from processors.ai_task_registry import get_ai_task
from processors.llm_client import TokenUsage, call_llm
from processors import signalforge_runtime_progress as runtime_progress
from processors.opportunity_reality import (
    _match_rows,
    _ensure_evidence,
    _link_claim,
    _refresh_claim_state,
)

ENGINE_VERSION = "solution-gap-reality-closure-v8-community-recall"
ALLOCATION_VERSION = "solution-allocation-v2-two-family-completion"

MAX_AI_CALLS_PER_RUN = max(
    0,
    min(4, int(os.getenv("RADAR_MAX_SOLUTION_AI_CALLS", "4") or 4)),
)
ESTIMATED_AI_CALL_TWD = max(
    0.0,
    float(os.getenv("RADAR_SOLUTION_AI_ESTIMATED_TWD", "0.03") or 0.03),
)
USD_TWD_RATE = max(
    1.0,
    float(os.getenv("USD_TWD_RATE", "31.83") or 31.83),
)

UNSAT = (
    r"\bunusable\b",
    r"\bunreliable\b",
    r"\binconsistent\b",
    r"\bbroken\b",
    r"\bfails?\b",
    r"\bfailure\b",
    r"\bcrash",
    r"\bregression\b",
    r"\bbug\b",
    r"\bdoesn.?t work\b",
    r"\bnot work(?:ing)?\b",
    r"\bincorrect\b",
    r"\bwrong\b",
    r"\bfrustrat",
    r"\bslow\b",
    r"\blatency\b",
    r"\btimeout\b",
    r"\bworkaround\b",
)

PERSISTENCE = (
    r"\bstill\b",
    r"\bongoing\b",
    r"\bnot fixed\b",
    r"\bunresolved\b",
    r"\bworkaround\b",
    r"\bregression\b",
    r"\bkeeps?\b",
    r"\bcontinues?\b",
    r"\bmonths?\b",
    r"\bweeks?\b",
)

KNOWN_SOLUTION_PATTERNS = (
    (r"\bchatgpt\b", "ChatGPT"),
    (r"\bclaude(?: code)?\b", "Claude"),
    (r"\bgemini\b", "Gemini"),
    (r"\bdeepseek\b", "DeepSeek"),
    (r"\bqwen(?:\d|[- ]|\b)", "Qwen"),
    (r"\bollama\b", "Ollama"),
    (r"\bllama\.?cpp\b", "llama.cpp"),
    (r"\bvllm\b", "vLLM"),
    (r"\bcerebras\b", "Cerebras"),
    (r"\bcursor\b", "Cursor"),
    (r"\bcopilot\b", "Copilot"),
    (r"\bsalesforce\b", "Salesforce"),
    (r"\blangchain\b", "LangChain"),
    (r"\blanggraph\b", "LangGraph"),
    (r"\bopenai\b", "OpenAI"),
    (r"\banthropic\b", "Anthropic"),
    (r"\bmistral\b", "Mistral"),
    (r"\bperplexity\b", "Perplexity"),
)


def _solution_identity_from_text(text: Any) -> str | None:
    value = str(text or "")
    for pattern, identity in KNOWN_SOLUTION_PATTERNS:
        if re.search(pattern, value, re.I):
            return identity
    return None


GENERIC = {
    "ai", "model", "models", "software", "system", "systems", "tool", "tools",
    "issue", "issues", "problem", "problems", "user", "users", "work", "works",
    "working", "product", "products", "solution", "solutions", "output",
}


def _has(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text or "", re.I) for pattern in patterns)


NEGATIVE_NEAR_PATTERNS = (
    r"\bunreliable\b",
    r"\binconsistent\b",
    r"\bbroken\b",
    r"\bfails?\b",
    r"\bfailure\b",
    r"\bbug\b",
    r"\bregression\b",
    r"\bincorrect\b",
    r"\bwrong\b",
    r"\bgibberish\b",
    r"\bincoherent\b",
    r"\btimeout\b",
    r"\bslow\b",
    r"\blatency\b",
    r"\bnot work",
    r"\bdoesn.?t work",
    r"\bignores?\b",
    r"\bcontradict",
    r"\bforget",
    r"\brepeats?\b",
    r"\bstuck\b",
    r"\binfinite loop\b",
    r"\bcrash",
)

POSITIVE_ONLY_PATTERNS = (
    r"\bultrafast\b",
    r"\bbenchmark\b",
    r"\brelease\b",
    r"\blaunch\b",
    r"\bannounc",
    r"\bimprov(?:e|ed|ement)\b",
    r"\bspeedup\b",
    r"\bfaster\b",
    r"\brecord\b",
)


def _solution_identity(match: dict[str, Any]) -> str | None:
    return (
        match.get("solution_identity")
        or match.get("repo")
        or _solution_identity_from_text(match.get("text"))
    )


def _negative_near_solution(match: dict[str, Any]) -> bool:
    text = str(match.get("text") or "")
    title = str(match.get("title") or "")
    identity = str(_solution_identity(match) or "").strip()

    if str(match.get("source_type") or "") == "github_issue":
        if _has(title, NEGATIVE_NEAR_PATTERNS):
            return True

    if not identity:
        return False

    low = text.lower()
    pos = low.find(identity.lower())
    windows = []
    if pos >= 0:
        windows.append(
            text[max(0, pos - 220): min(len(text), pos + len(identity) + 360)]
        )

    windows.append((title + " " + text[:700]).strip())
    return any(_has(window, NEGATIVE_NEAR_PATTERNS) for window in windows)


def _positive_only_context(match: dict[str, Any]) -> bool:
    title = str(match.get("title") or "")
    early = (title + " " + str(match.get("text") or "")[:500]).strip()
    positive = _has(early, POSITIVE_ONLY_PATTERNS)
    negative = _has(early, NEGATIVE_NEAR_PATTERNS)
    return bool(positive and not negative)


PROBLEM_DIMENSIONS = {
    "load": (
        ("under load", "load", "overload", "concurrent", "concurrency",
         "traffic", "requests", "queue", "capacity"),
        ("under load", "overload", "concurrent", "concurrency", "traffic",
         "requests per second", "rps", "queue", "capacity", "high load"),
    ),
    "latency": (
        ("slow", "latency", "response time", "time-to-first", "ttft"),
        ("slow", "latency", "response time", "ttft", "time to first",
         "time-to-first", "delay", "seconds", "timeout"),
    ),
    "voice": (
        ("voice", "audio", "speech", "tts", "microphone"),
        ("voice", "audio", "speech", "tts", "microphone", "speaker"),
    ),
    "assumption_instruction": (
        ("assumption", "assumptions", "instruction", "prompt"),
        ("assumption", "assumptions", "instruction", "prompt",
         "contradict", "ignores user", "ignores input"),
    ),
    "context_memory": (
        ("context", "memory", "retain", "forget", "previous instructions"),
        ("context", "memory", "retain", "forget", "previous instruction",
         "repeats previous", "idle pause"),
    ),
    "checkpoint": (
        ("checkpoint", "checkpointing", "shared base", "base data"),
        ("checkpoint", "checkpointing", "shared base", "base data",
         "snapshot", "state restore"),
    ),
    "access_auth": (
        ("sign-up", "signup", "sign up", "access", "login", "auth"),
        ("sign-up", "signup", "sign up", "access", "login",
         "authentication", "oauth", "account"),
    ),
    "deployment_setup": (
        ("deployment", "deploy", "setup", "installation", "configuration"),
        ("deployment", "deploy", "setup", "installation", "configuration",
         "install", "runtime"),
    ),
    "cost_transparency": (
        ("cost breakdown", "cost transparency", "compute cost", "billing"),
        ("cost breakdown", "cost transparency", "compute cost", "billing",
         "invoice", "usage cost", "pricing"),
    ),
    "creative_song": (
        ("song", "songwriting", "lyrics", "creative songwriting"),
        ("song", "songwriting", "lyrics", "creative writing"),
    ),
    "text_editing": (
        ("text editing", "editing quality", "rewrite", "editor"),
        ("text editing", "editing quality", "rewrite", "editor", "editing"),
    ),
    "debugging": (
        ("debug", "debugging", "junior engineer"),
        ("debug", "debugging", "developer", "engineer"),
    ),
}


def _case_text(candidate: ProblemCandidate) -> str:
    return " ".join(
        str(x or "")
        for x in (
            candidate.title,
            candidate.problem_statement,
            candidate.task,
            candidate.object,
            candidate.failure_mode,
            candidate.consequence,
            candidate.workaround,
        )
    ).lower()


def _required_dimensions(candidate: ProblemCandidate) -> set[str]:
    text = _case_text(candidate)
    out = set()
    for name, (case_terms, _) in PROBLEM_DIMENSIONS.items():
        if any(term in text for term in case_terms):
            out.add(name)
    return out


def _evidence_dimensions(item: dict[str, Any]) -> set[str]:
    text = " ".join(
        str(x or "")
        for x in (
            item.get("title"),
            item.get("text"),
            item.get("solution_identity"),
            item.get("repo"),
        )
    ).lower()

    out = set()
    for name, (_, evidence_terms) in PROBLEM_DIMENSIONS.items():
        if any(term in text for term in evidence_terms):
            out.add(name)
    return out


DIRECTION_RULES = {
    "latency": {
        "case_negative": (
            "slow", "latency", "response time", "delay", "timeout",
            "takes too long", "high latency",
        ),
        "evidence_negative": (
            "slow", "high latency", "latency regression", "delay", "timeout",
            "takes too long", "stalls", "lag",
        ),
        "evidence_positive": (
            "ultrafast", "low latency", "faster", "speedup",
            "reduced latency", "latency improvement",
        ),
    },
}


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    low = str(text or "").lower()
    return any(term in low for term in terms)


def _direction_contradiction(
    candidate: ProblemCandidate,
    item: dict[str, Any],
) -> tuple[bool, str | None]:
    case_text = _case_text(candidate)
    title = str(item.get("title") or "").lower()
    early = (title + " " + str(item.get("text") or "")[:900]).lower()

    latency = DIRECTION_RULES["latency"]
    if _contains_any(case_text, latency["case_negative"]):
        # The title is the highest-confidence polarity surface. An explicit
        # "ultrafast / low latency / speedup" claim is the opposite of a
        # slow/high-latency problem, even if the body contains unrelated words.
        if (
            _contains_any(title, latency["evidence_positive"])
            and not _contains_any(title, latency["evidence_negative"])
        ):
            return True, "latency_direction_opposite"
        if (
            _contains_any(early, latency["evidence_positive"])
            and not _contains_any(early, latency["evidence_negative"])
        ):
            return True, "latency_direction_opposite"

    return False, None


MECHANISM_RULES = {
    "load": (
        "under load", "overload", "high load", "concurrent", "concurrency",
        "traffic spike", "request volume", "requests per second", "rps",
        "queue buildup", "queueing", "capacity", "parallel requests",
        "many simultaneous", "multiple simultaneous",
    ),
    "latency": (
        "slow", "latency", "response time", "delay", "timeout",
        "time-to-first", "ttft", "takes too long", "high latency",
    ),
    "voice": (
        "voice", "audio", "speech", "tts", "microphone", "speaker",
    ),
    "checkpoint": (
        "checkpoint", "checkpointing", "snapshot", "restore", "state restore",
        "shared base", "base data",
    ),
    "access_auth": (
        "sign-up", "signup", "sign up", "login", "authentication",
        "oauth", "account", "access denied",
    ),
    "context_memory": (
        "context", "memory", "forget", "retain", "previous instruction",
        "repeats previous", "idle pause",
    ),
}


def _passes_mechanism_gate(
    candidate: ProblemCandidate,
    item: dict[str, Any],
) -> tuple[bool, list[str]]:
    required = _required_dimensions(candidate)
    text = (
        str(item.get("title") or "")
        + " "
        + str(item.get("text") or "")[:1400]
    ).lower()

    missing = []
    for dimension in required:
        terms = MECHANISM_RULES.get(dimension)
        if terms and not any(term in text for term in terms):
            missing.append(dimension)

    return not missing, sorted(missing)


def _pre_ai_identity_gate(
    candidate: ProblemCandidate,
    item: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    passed_dim, missing_dim, observed = _passes_dimension_gate(candidate, item)
    if not passed_dim:
        return False, {
            "reason": "missing_dimension",
            "missing_dimensions": missing_dim,
            "observed_dimensions": observed,
        }

    contradiction, reason = _direction_contradiction(candidate, item)
    if contradiction:
        return False, {
            "reason": reason,
            "observed_dimensions": observed,
        }

    passed_mech, missing_mech = _passes_mechanism_gate(candidate, item)
    if not passed_mech:
        return False, {
            "reason": "missing_mechanism",
            "missing_mechanisms": missing_mech,
            "observed_dimensions": observed,
        }

    return True, {
        "reason": "PASS",
        "observed_dimensions": observed,
    }


def _passes_dimension_gate(
    candidate: ProblemCandidate,
    item: dict[str, Any],
) -> tuple[bool, list[str], list[str]]:
    required = _required_dimensions(candidate)
    observed = _evidence_dimensions(item)

    if not required:
        return True, [], sorted(observed)

    missing = sorted(required - observed)
    return not missing, missing, sorted(observed)


def _same_problem_prompt(
    *,
    case: RadarCase,
    candidate: ProblemCandidate,
    item: dict[str, Any],
    evidence_id: str,
) -> str:
    return f"""Judge whether the CASE and EVIDENCE describe the SAME underlying problem.

This is an identity check, not a business-value judgement.

CASE fingerprint:
{json.dumps({
    "evidence_id": f"CASE_{case.id}",
    "title": candidate.title,
    "actor": candidate.actor,
    "task": candidate.task,
    "object": candidate.object,
    "failure_mode": candidate.failure_mode,
    "consequence": candidate.consequence,
    "required_dimensions": sorted(_required_dimensions(candidate)),
}, ensure_ascii=False, indent=2)}

EVIDENCE fingerprint:
{json.dumps({
    "evidence_id": evidence_id,
    "solution_identity": _solution_identity(item),
    "title": item.get("title"),
    "excerpt": str(item.get("text") or "")[:2200],
    "state": item.get("state"),
    "age_days": _published_age_days(item.get("published_at")),
    "observed_dimensions": sorted(_evidence_dimensions(item)),
}, ensure_ascii=False, indent=2)}

SAME_PROBLEM requires the concrete failure dimension, mechanism, AND direction to match.
Evidence describing the opposite outcome (for example ultrafast latency vs slow latency)
is DIFFERENT_PROBLEM even when the metric/domain is the same.
Same broad technology or same "AI problem" is NOT enough.

Examples of DIFFERENT_PROBLEM:
- load/concurrency failure vs generic wrong output
- latency vs correctness
- voice/audio failure vs text/model failure
- context-memory loss vs general model quality
- signup/auth failure vs runtime inference failure
- checkpoint/state failure vs unrelated reliability bug

Return valid JSON only:
{{
  "verdict": "SAME_PROBLEM | DIFFERENT_PROBLEM | INSUFFICIENT",
  "matching_dimensions": ["..."],
  "conflicting_dimensions": ["..."],
  "evidence_ids": ["CASE_{case.id}", "{evidence_id}"]
}}
"""


def _validate_same_problem(
    obj: Any,
    *,
    case_id: int,
    evidence_id: str,
) -> tuple[bool, str]:
    if not isinstance(obj, dict):
        return False, "not_object"

    verdict = str(obj.get("verdict") or "").strip().upper()
    aliases = {
        "SAME": "SAME_PROBLEM",
        "DIFFERENT": "DIFFERENT_PROBLEM",
        "RELATED": "INSUFFICIENT",
        "UNKNOWN": "INSUFFICIENT",
    }
    verdict = aliases.get(verdict, verdict)

    if verdict not in {
        "SAME_PROBLEM",
        "DIFFERENT_PROBLEM",
        "INSUFFICIENT",
    }:
        return False, "bad_verdict"

    ids = obj.get("evidence_ids")
    if isinstance(ids, str):
        ids = [x for x in re.split(r"[,;\s]+", ids) if x]
    if not isinstance(ids, list):
        return False, "bad_evidence_ids"

    normalized = {str(x).strip().upper() for x in ids}
    if evidence_id.upper() not in normalized:
        return False, "missing_evidence_id"

    obj["verdict"] = verdict
    obj["evidence_ids"] = [f"CASE_{case_id}", evidence_id]
    return True, "OK"


def _validate_cached_same_problem(
    obj: Any,
    *,
    case_id: int,
    current_evidence_id: str,
) -> tuple[bool, str]:
    """Revalidate a pair-cache verdict without depending on shortlist position.

    Pair fingerprints identify the concrete source item. M17 additionally tied
    cache reuse to EVIDENCE_N, which is only the item's current rank and can
    change when the corpus grows. A rank change must not erase a previously
    validated SAME_PROBLEM judgment for the identical fingerprint.
    """
    if not isinstance(obj, dict):
        return False, "not_object"
    ids = obj.get("evidence_ids")
    if isinstance(ids, str):
        ids = [x for x in re.split(r"[,;\s]+", ids) if x]
    if not isinstance(ids, list):
        return False, "bad_evidence_ids"
    prior = next(
        (str(x).strip() for x in ids if str(x).strip().upper().startswith("EVIDENCE_")),
        None,
    )
    if not prior:
        return False, "missing_cached_evidence_id"
    valid, reason = _validate_same_problem(
        obj, case_id=case_id, evidence_id=prior
    )
    if valid:
        obj["evidence_ids"] = [f"CASE_{case_id}", current_evidence_id]
    return valid, reason


def _capability_terms(candidate: ProblemCandidate) -> list[str]:
    text = " ".join(
        str(x or "")
        for x in (
            candidate.title,
            candidate.problem_statement,
            candidate.failure_mode,
            candidate.object,
            candidate.task,
            candidate.consequence,
        )
    ).lower()

    terms = {
        "bug", "failure", "limitation", "workaround", "regression",
        "current solution", "existing tool",
    }

    groups = (
        (
            ("reliable", "reliability", "incorrect", "wrong", "assumption", "hallucin"),
            (
                "incorrect output", "unreliable output", "hallucination",
                "evaluation failure", "model quality", "guardrail failure",
            ),
        ),
        (
            ("slow", "latency", "response time", "throughput", "local model"),
            (
                "slow inference", "latency", "throughput", "timeout",
                "model serving", "inference performance",
            ),
        ),
        (
            ("complex", "complexity", "deployment", "configuration", "setup"),
            (
                "deployment failure", "setup issue", "configuration issue",
                "integration failure", "developer experience",
            ),
        ),
        (
            ("context", "memory", "forget", "instruction", "agent"),
            (
                "agent memory", "context loss", "instruction following",
                "tool use failure", "agent reliability",
            ),
        ),
        (
            ("api", "access", "signup", "rate limit", "quota"),
            (
                "api access failure", "rate limit", "authentication issue",
                "signup failure", "quota limitation",
            ),
        ),
    )

    for triggers, additions in groups:
        if any(x in text for x in triggers):
            terms.update(additions)

    return sorted(terms)


def _proxy(candidate: ProblemCandidate) -> Any:
    expansion = " ".join(_capability_terms(candidate))
    return SimpleNamespace(
        id=candidate.id,
        title=candidate.title,
        problem_statement=(
            f"{candidate.problem_statement or ''} "
            f"SOLUTION_FAILURE_TERMS {expansion}"
        ),
        actor=candidate.actor,
        task=candidate.task,
        object=candidate.object,
        failure_mode=candidate.failure_mode,
        consequence=candidate.consequence,
        buyer_context=candidate.buyer_context,
        workaround=candidate.workaround,
    )


def _compact_ref(value: Any) -> str:
    raw = str(value or "")
    if len(raw) <= 180:
        return raw
    return raw[:120] + ":" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _published_age_days(value: Any) -> int | None:
    if not isinstance(value, datetime):
        return None
    try:
        now = datetime.now(value.tzinfo) if value.tzinfo else datetime.utcnow()
        return max(0, (now - value).days)
    except Exception:
        return None


def _issue_docs(rows: list[GithubIssue]) -> list[dict[str, Any]]:
    docs = []
    for row in rows:
        text = " ".join([
            row.repo_full_name or "",
            row.title or "",
            row.body or "",
            json.dumps(row.labels or [], ensure_ascii=False),
        ]).strip()
        if len(text) < 25:
            continue
        docs.append({
            "id": f"github_issue:{row.id}",
            "text": text[:16000],
            "title": row.title or "",
            "url": row.html_url,
            "published_at": row.created_at,
            "updated_at": row.updated_at,
            "repo": row.repo_full_name,
            "state": str(row.state or "").lower(),
            "comments_count": int(row.comments_count or 0),
            "source_type": "github_issue",
            "source_family": f"github_solution:{row.repo_full_name.lower()}",
            "solution_identity": row.repo_full_name,
            "origin_case_id": None,
        })
    return docs


def _external_docs(rows: list[ExternalProblemItem]) -> list[dict[str, Any]]:
    docs = []
    for row in rows:
        text = " ".join([row.title or "", row.body or ""]).strip()
        if len(text) < 25:
            continue
        docs.append({
            "id": f"external_problem:{row.id}",
            "text": text[:16000],
            "title": row.title or "",
            "url": row.url,
            "published_at": row.published_at,
            "updated_at": row.updated_at,
            "repo": None,
            "state": None,
            "comments_count": 0,
            "source_type": str(row.source_type or "external_problem"),
            "source_family": (
                f"external:{str(row.source_type or '').lower()}:"
                f"{str(row.source_key or '').lower()[:160]}"
            ),
            "solution_identity": _solution_identity_from_text(text),
            "origin_candidate_id": row.matched_candidate_id,
            "direct_problem": bool(row.is_direct_problem),
        })
    return docs


def _product_review_docs(
    reviews: list[ProductReview],
    posts_by_id: dict[int, Post],
) -> list[dict[str, Any]]:
    """Turn existing product-review intelligence into named-solution evidence.

    One product remains one independent source family even when several sample
    posts exist, preventing review-volume inflation from satisfying C06/C07.
    """
    docs: list[dict[str, Any]] = []
    for review in reviews:
        product = str(review.product_name or "").strip()
        if not product:
            continue
        family = f"product_review:{re.sub(r'[^a-z0-9._-]+', '-', product.lower()).strip('-')[:120] or 'unknown'}"
        aggregate_parts = [
            product,
            "CONS " + " ; ".join(str(x) for x in (review.cons or []) if x),
            "CHURN " + " ; ".join(str(x) for x in (review.churn_reasons or []) if x),
            "FEATURE_REQUESTS " + " ; ".join(str(x) for x in (review.feature_requests or []) if x),
            "COMPETITORS " + " ; ".join(
                str(x.get("competitor") or x.get("context") or "") if isinstance(x, dict) else str(x)
                for x in (review.competitor_comparisons or [])
            ),
        ]
        aggregate = " ".join(x for x in aggregate_parts if x).strip()
        if len(aggregate) >= 25:
            docs.append({
                "id": f"product_review:{review.id}",
                "text": aggregate[:16000],
                "title": f"{product} product review summary",
                "url": None,
                "published_at": review.calculated_at,
                "updated_at": review.updated_at,
                "repo": None,
                "state": None,
                "comments_count": int(review.post_count or 0),
                "source_type": "product_review",
                "source_family": family,
                "solution_identity": product,
                "origin_candidate_id": None,
                "review_id": review.id,
            })

        for post_id in (review.sample_post_ids or [])[:8]:
            try:
                pid = int(post_id)
            except Exception:
                continue
            post = posts_by_id.get(pid)
            if post is None:
                continue
            text = " ".join([product, post.title or "", post.body or ""]).strip()
            if len(text) < 25:
                continue
            docs.append({
                "id": f"product_review_post:{review.id}:{pid}",
                "text": text[:16000],
                "title": post.title or f"{product} user review evidence",
                "url": post.url,
                "published_at": post.posted_at,
                "updated_at": post.created_at,
                "repo": None,
                "state": None,
                "comments_count": int(post.num_comments or 0),
                "source_type": "product_review_post",
                "source_family": family,
                "solution_identity": product,
                "origin_candidate_id": None,
                "review_id": review.id,
                "post_id": pid,
            })
    return docs


def _community_solution_docs(rows: list[Post]) -> list[dict[str, Any]]:
    """Use already-collected community posts as named-solution complaint recall.

    Precision stays downstream: a post must name a known solution, contain
    nearby negative/failure language, pass the case-specific mechanism and
    direction gates, and then survive pairwise SAME_PROBLEM adjudication.
    One platform+solution pair is one evidence family so volume cannot satisfy
    the two-independent-family contract by itself.
    """
    docs: list[dict[str, Any]] = []
    for row in rows:
        text = " ".join([str(row.title or ""), str(row.body or "")]).strip()
        if len(text) < 30:
            continue
        identity = _solution_identity_from_text(text)
        if not identity:
            continue
        probe = {
            "text": text,
            "title": str(row.title or ""),
            "solution_identity": identity,
            "source_type": "community_post",
        }
        if _positive_only_context(probe) or not _negative_near_solution(probe):
            continue
        platform_id = int(getattr(row, "platform_id", 0) or 0)
        family_slug = re.sub(r"[^a-z0-9._-]+", "-", identity.lower()).strip("-")
        docs.append({
            "id": f"community_post:{row.id}",
            "text": text[:16000],
            "title": str(row.title or ""),
            "url": row.url,
            "published_at": row.posted_at,
            "updated_at": row.created_at,
            "repo": None,
            "state": None,
            "comments_count": int(row.num_comments or 0),
            "source_type": "community_post",
            "source_family": f"community_platform:{platform_id}:{family_slug}",
            "solution_identity": identity,
            "origin_candidate_id": None,
            "post_id": int(row.id),
            "subreddit": str(row.subreddit or ""),
        })
    return docs


def _radar_docs(rows: list[RadarEvidence]) -> list[dict[str, Any]]:
    docs = []
    for row in rows:
        if row.authority_class in {
            "BUYER_BUDGET_SIGNAL", "TIMING_CONTEXT",
            "COMPANY_CAPABILITY_EVIDENCE", "SOLUTION_SUPPLY",
            "MARKET_SUPPLY",
        }:
            continue
        text = " ".join([row.source_title or "", row.excerpt or ""]).strip()
        if len(text) < 25:
            continue
        md = dict(row.raw_metadata or {})
        identity = (
            md.get("repo")
            or md.get("product")
            or md.get("tool")
            or md.get("solution")
            or _solution_identity_from_text(text)
        )
        docs.append({
            "id": f"radar_evidence:{row.id}",
            "text": text[:16000],
            "title": row.source_title or "",
            "url": row.source_url,
            "published_at": row.published_at,
            "updated_at": None,
            "repo": md.get("repo"),
            "state": md.get("state"),
            "comments_count": int(md.get("comments_count") or 0),
            "source_type": str(row.source_type or "radar_evidence"),
            "source_family": str(row.source_family_key or f"evidence:{row.id}"),
            "solution_identity": identity,
            "origin_case_id": row.case_id,
            "directness": row.directness,
        })
    return docs


def _specific_overlap(match: dict[str, Any]) -> bool:
    shared = {
        str(x).lower()
        for x in match.get("shared_terms", [])
        if str(x).lower() not in GENERIC
    }
    rare = {
        str(x).lower()
        for x in match.get("rare_shared", [])
        if str(x).lower() not in GENERIC
    }
    named = {
        str(x).lower()
        for x in match.get("named_shared", [])
        if str(x).lower() not in GENERIC
    }
    domains = set(match.get("domain_shared", []) or [])
    sem = float(match.get("semantic_score", 0) or 0)
    lex = float(match.get("lexical_score", 0) or 0)

    return bool(
        named
        or len(rare) >= 1
        or (domains and len(shared) >= 2 and sem >= 0.30)
        or (len(shared) >= 3 and lex >= 0.05)
    )


def _candidate_for_case(
    match: dict[str, Any],
    *,
    candidate_id: int,
    case_id: int,
) -> bool:
    origin_candidate = match.get("origin_candidate_id")
    origin_case = match.get("origin_case_id")
    if origin_candidate is not None and int(origin_candidate) != candidate_id:
        return False
    if origin_case is not None and int(origin_case) != case_id:
        return False
    return True


def _solution_ai_candidate(match: dict[str, Any]) -> bool:
    sem = float(match.get("semantic_score", 0) or 0)
    lex = float(match.get("lexical_score", 0) or 0)

    identity = _solution_identity(match)
    if not identity:
        return False

    # Positive announcements/benchmarks cannot become dissatisfaction
    # evidence merely because a long body contains a distant negative word.
    if _positive_only_context(match):
        return False
    if not _negative_near_solution(match):
        return False

    if sem >= 0.29:
        return True
    if sem >= 0.22 and _specific_overlap(match):
        return True
    if lex >= 0.04 and _specific_overlap(match):
        return True
    return False


def _persistent(match: dict[str, Any]) -> bool:
    text = str(match.get("text") or "")
    identity = _solution_identity(match)
    if not identity:
        return False
    if _positive_only_context(match):
        return False
    if not _negative_near_solution(match):
        return False

    state = str(match.get("state") or "").lower()
    age = _published_age_days(match.get("published_at"))
    comments = int(match.get("comments_count") or 0)

    if state == "open" and age is not None and age >= 30:
        return True
    if state == "open" and comments >= 3:
        return True
    if _has(text, PERSISTENCE):
        return True
    return False


async def _budget(
    session,
    *,
    case: RadarCase,
) -> RadarAIBudgetLedger:
    cycle_key = "solution-gap-ai:" + datetime.utcnow().strftime("%Y-%m-%d")
    row = (await session.execute(
        select(RadarAIBudgetLedger).where(
            RadarAIBudgetLedger.case_id == case.id,
            RadarAIBudgetLedger.cycle_key == cycle_key,
        )
    )).scalar_one_or_none()

    if row is None:
        cap = 0.30 if str(case.system_verdict or "").upper() in {
            "INVESTIGATE", "VALIDATE"
        } else 0.05
        row = RadarAIBudgetLedger(
            case_id=case.id,
            cycle_key=cycle_key,
            verdict_state=str(case.system_verdict or "WATCH").upper(),
            budget_cap_twd=cap,
            reserved_twd=0.0,
            spent_twd=0.0,
        )
        session.add(row)
        await session.flush()

    return row


SYSTEM = """You are a skeptical evidence adjudicator.

You may only judge already-retrieved evidence against ONE atomic claim.
Do not search the web. Do not use outside knowledge. Do not invent a product,
customer, workaround, persistence fact, or missing context.

False positives are more costly than false negatives.

For C06 current_solution_unsatisfactory:
SUPPORT requires evidence that identifiable existing solution(s), product(s),
project(s), service(s), or tool(s) used for the same task explicitly fail,
regress, frustrate users, require workarounds, are unreliable, or otherwise do
not satisfactorily solve the concrete case problem. Generic discussion of the
underlying problem is insufficient.

For C07 unresolved_gap_exists:
SUPPORT additionally requires evidence that the failure persists despite
existing solutions: e.g. old open issue, repeated current complaints,
workaround dependence, regression, not-fixed language, or similar persistence.
C07 cannot be supported merely because C06 is supported.

Prefer two independent source families. If evidence is too generic or only one
weak family supports the claim, return INSUFFICIENT.

Return valid JSON only."""


def _prompt(
    *,
    case: RadarCase,
    candidate: ProblemCandidate,
    claim_code: str,
    shortlist: list[dict[str, Any]],
) -> str:
    evidence = []
    for idx, item in enumerate(shortlist, 1):
        evidence.append({
            "evidence_id": f"EVIDENCE_{idx}",
            "source_type": item.get("source_type"),
            "source_family": item.get("source_family"),
            "solution_identity": item.get("solution_identity") or item.get("repo"),
            "state": item.get("state"),
            "age_days": _published_age_days(item.get("published_at")),
            "comments_count": item.get("comments_count", 0),
            "title": item.get("title"),
            "excerpt": str(item.get("text") or "")[:1800],
            "semantic_score": item.get("semantic_score"),
            "lexical_score": item.get("lexical_score"),
        })

    atomic = (
        "C06 current_solution_unsatisfactory"
        if claim_code == "C06"
        else "C07 unresolved_gap_exists"
    )

    return f"""Judge {atomic} for the supplied CASE.

CASE:
{json.dumps({
    "case_id": case.id,
    "title": candidate.title,
    "problem_statement": candidate.problem_statement,
    "task": candidate.task,
    "object": candidate.object,
    "failure_mode": candidate.failure_mode,
    "consequence": candidate.consequence,
    "workaround": candidate.workaround,
}, ensure_ascii=False, indent=2)}

ALREADY-RETRIEVED EVIDENCE:
{json.dumps(evidence, ensure_ascii=False, indent=2)}

Return exactly:
{{
  "stance": "SUPPORT | INSUFFICIENT",
  "evidence_ids": ["CASE_{case.id}", "EVIDENCE_N", "EVIDENCE_M"],
  "rationale": "1-3 skeptical sentences"
}}

If SUPPORT, cite the strongest evidence items. Prefer at least two independent
source_family values. Do not infer facts that are not in the supplied text.
"""


def _normalize_stance(value: Any) -> str:
    raw = str(value or "").strip().upper()
    aliases = {
        "SUPPORTED": "SUPPORT",
        "YES": "SUPPORT",
        "TRUE": "SUPPORT",
        "REFUTE": "INSUFFICIENT",
        "REFUTED": "INSUFFICIENT",
        "NO": "INSUFFICIENT",
        "FALSE": "INSUFFICIENT",
        "UNKNOWN": "INSUFFICIENT",
        "UNCERTAIN": "INSUFFICIENT",
    }
    raw = aliases.get(raw, raw)
    return raw if raw in {"SUPPORT", "INSUFFICIENT"} else ""


def _normalize_evidence_ids(value: Any) -> list[str]:
    if isinstance(value, str):
        items = re.split(r"[,;\s]+", value)
    elif isinstance(value, list):
        items = [str(x) for x in value]
    else:
        items = []

    out = []
    for raw in items:
        s = str(raw or "").strip().upper()
        if not s:
            continue

        m = re.search(r"(?:EVIDENCE[_\-\s]*)?(\d+)$", s)
        if m:
            out.append(f"EVIDENCE_{int(m.group(1))}")
            continue

        m = re.search(r"CASE[_\-\s]*(\d+)", s)
        if m:
            out.append(f"CASE_{int(m.group(1))}")

    return out


def _validate(
    result: Any,
    *,
    case_id: int,
    shortlist: list[dict[str, Any]],
) -> tuple[bool, str, list[int]]:
    if not isinstance(result, dict):
        return False, "not_object", []

    stance = _normalize_stance(result.get("stance"))
    if not stance:
        return False, "bad_stance", []

    ids = _normalize_evidence_ids(result.get("evidence_ids"))
    selected = []
    for value in ids:
        m = re.fullmatch(r"EVIDENCE_(\d+)", value)
        if not m:
            continue
        idx = int(m.group(1))
        if 1 <= idx <= len(shortlist) and idx not in selected:
            selected.append(idx)

    # CASE_x is context, not evidence. Do not reject a valid result because
    # the model omitted a fake CASE citation.
    if not selected:
        return False, "missing_valid_evidence_id", []

    rationale = str(
        result.get("rationale")
        or result.get("reason")
        or result.get("explanation")
        or ""
    ).strip()
    if not rationale:
        return False, "missing_rationale", []

    result["stance"] = stance
    result["evidence_ids"] = [
        f"CASE_{case_id}",
        *[f"EVIDENCE_{idx}" for idx in selected],
    ]
    result["rationale"] = rationale

    if stance == "SUPPORT":
        families = {
            str(shortlist[idx - 1].get("source_family") or "")
            for idx in selected
        }
        if len(families) < 2:
            result["stance"] = "INSUFFICIENT"
            return True, "DOWNGRADED_ONE_FAMILY_SUPPORT", selected

    return True, "OK", selected


async def _materialize(
    session,
    *,
    case_id: int,
    item: dict[str, Any],
) -> RadarEvidence:
    source_type = str(item.get("source_type") or "solution_research")
    family = str(item.get("source_family") or f"solution:{item.get('id')}")
    solution = item.get("solution_identity") or item.get("repo")

    return await _ensure_evidence(
        session,
        case_id,
        source_type=source_type,
        source_table=(
            "github_issues"
            if source_type == "github_issue"
            else "product_reviews"
            if source_type == "product_review"
            else "posts"
            if source_type == "product_review_post"
            else "external_problem_items"
            if str(item.get("id") or "").startswith("external_problem:")
            else "radar_evidence"
        ),
        source_ref=_compact_ref(item.get("id")),
        source_title=item.get("title") or "",
        excerpt=str(item.get("text") or "")[:8000],
        source_url=item.get("url"),
        source_family_key=family,
        authority_class="CURRENT_SOLUTION_FAILURE",
        directness="DIRECT" if source_type != "github_issue" else "RELATED",
        published_at=item.get("published_at"),
        metadata={
            "engine_version": ENGINE_VERSION,
            "solution_identity": solution,
            "state": item.get("state"),
            "comments_count": item.get("comments_count", 0),
            "semantic_score": item.get("semantic_score"),
            "lexical_score": item.get("lexical_score"),
            "shared_terms": item.get("shared_terms", []),
            "rare_shared": item.get("rare_shared", []),
            "domain_shared": item.get("domain_shared", []),
            "research_role": "solution_gap",
        },
    )


def _cached_same_families(claim: RadarClaim | None) -> set[str]:
    if claim is None:
        return set()
    summary = dict(claim.evidence_summary or {})
    cache = dict(summary.get("same_problem_pairs_v3") or {})
    out = set()
    for row in cache.values():
        if not isinstance(row, dict) or row.get("validation") != "OK":
            continue
        result = row.get("result") or {}
        if str(result.get("verdict") or "").upper() != "SAME_PROBLEM":
            continue
        family = str(row.get("source_family") or "").strip()
        if family:
            out.add(family)
    return out


def _target_priority_map(target_rows: list[dict[str, Any]]) -> dict[int, int]:
    return {
        int(row.get("case_id") or 0): idx
        for idx, row in enumerate(target_rows)
        if int(row.get("case_id") or 0) > 0
    }


async def run_solution_gap_research(
    target_rows: list[dict[str, Any]],
    *,
    ai_call_allowance: int = MAX_AI_CALLS_PER_RUN,
) -> dict[str, Any]:
    target_by_case = {
        int(row["case_id"]): str(row.get("current_gate") or "")
        for row in target_rows
        if row.get("current_gate") in {
            "CURRENT_SOLUTION", "UNRESOLVED_GAP"
        }
    }
    runtime_progress.heartbeat(
        detail="c06/c07 targets accepted",
        progress={
            "cases_completed": 0,
            "cases_total": len(target_by_case),
            "ai_calls": 0,
            "ai_allowance": int(ai_call_allowance),
        },
    )

    empty = {
        "cases": 0,
        "c06_targets": 0,
        "c07_targets": 0,
        "support_links": 0,
        "ai_calls": 0,
        "ai_cache_hits": 0,
        "ai_support": 0,
        "ai_insufficient": 0,
        "ai_errors": 0,
        "ai_gate_denied": 0,
        "ai_deferred": 0,
        "ai_tokens": 0,
        "ai_cost_twd": 0.0,
        "same_problem": 0,
        "different_problem": 0,
        "same_problem_insufficient": 0,
        "dimension_rejects": 0,
        "details": {},
    }
    if not target_by_case:
        return empty

    target_ids = set(target_by_case)

    async with async_session() as session:
        pairs = list((await session.execute(
            select(RadarCase, ProblemCandidate)
            .join(
                ProblemCandidate,
                ProblemCandidate.id == RadarCase.candidate_id,
            )
            .where(RadarCase.id.in_(target_ids))
        )).all())

        candidate_ids = [candidate.id for _, candidate in pairs]

        github_rows = list((await session.execute(
            select(GithubIssue)
            .order_by(GithubIssue.updated_at.desc())
            .limit(1800)
        )).scalars().all())

        external_rows = list((await session.execute(
            select(ExternalProblemItem).where(
                ExternalProblemItem.is_direct_problem == True,  # noqa: E712
                ExternalProblemItem.matched_candidate_id.in_(candidate_ids),
            )
        )).scalars().all())

        radar_rows = list((await session.execute(
            select(RadarEvidence).where(
                RadarEvidence.case_id.in_(target_ids)
            )
        )).scalars().all())

        review_rows = list((await session.execute(
            select(ProductReview)
            .order_by(ProductReview.updated_at.desc())
            .limit(400)
        )).scalars().all())
        sample_post_ids = sorted({
            int(pid)
            for review in review_rows
            for pid in (review.sample_post_ids or [])
            if str(pid).isdigit()
        })
        review_posts = []
        if sample_post_ids:
            review_posts = list((await session.execute(
                select(Post).where(Post.id.in_(sample_post_ids))
            )).scalars().all())
        posts_by_id = {int(row.id): row for row in review_posts}

        # ProductReview may legitimately be empty. Do not let that make the
        # solution corpus empty: use high-signal, already-collected community
        # posts that explicitly name a known solution and describe a nearby
        # failure. The same strict downstream identity gates still apply.
        community_rows = list((await session.execute(
            select(Post)
            .where(Post.body.isnot(None))
            .order_by(Post.score.desc(), Post.created_at.desc())
            .limit(5000)
        )).scalars().all())

    community_docs = _community_solution_docs(community_rows)
    docs = (
        _issue_docs(github_rows)
        + _external_docs(external_rows)
        + _product_review_docs(review_rows, posts_by_id)
        + community_docs
        + _radar_docs(radar_rows)
    )
    runtime_progress.heartbeat(
        detail="c06/c07 solution corpus loaded",
        progress={
            "cases_completed": 0,
            "cases_total": len(target_by_case),
            "documents": len(docs),
            "ai_calls": 0,
            "ai_allowance": int(ai_call_allowance),
        },
    )

    candidates = [candidate for _, candidate in pairs]
    proxies = [_proxy(candidate) for candidate in candidates]
    matches = _match_rows(
        proxies,
        docs,
        threshold=0.025,
        top_k=18,
        role="solution",
    ) if docs else {}
    runtime_progress.heartbeat(
        detail="c06/c07 retrieval ready",
        progress={
            "cases_completed": 0,
            "cases_total": len(target_by_case),
            "documents": len(docs),
            "matched_cases": len(matches),
            "ai_calls": 0,
            "ai_allowance": int(ai_call_allowance),
        },
    )

    support_links = 0
    ai_calls = 0
    ai_cache_hits = 0
    ai_support = 0
    ai_insufficient = 0
    ai_errors = 0
    ai_gate_denied = 0
    ai_deferred = 0
    ai_tokens = 0
    ai_cost_twd = 0.0
    same_problem = 0
    different_problem = 0
    same_problem_insufficient = 0
    dimension_rejects = 0
    c07_same_cycle_supported = 0
    c07_same_cycle_evaluated = 0
    validation_failures: dict[str, int] = defaultdict(int)
    exception_types: dict[str, int] = defaultdict(int)

    details: dict[int, dict[str, Any]] = {}
    task_spec = get_ai_task("same_problem_verify")

    # C06/C07 both require two independent source families. M17 divided the
    # global allowance by target count, which usually capped every case at one
    # fresh adjudication and made fresh SUPPORT mathematically impossible. M18
    # allocates depth-first: finish the highest-VOI near-closure case first,
    # then move to the next case. The two-family threshold itself is unchanged.
    per_case_fresh_cap = min(5, max(0, int(ai_call_allowance)))
    target_priority = _target_priority_map(target_rows)

    async with async_session() as session:
        session_pairs = list((await session.execute(
            select(RadarCase, ProblemCandidate)
            .join(
                ProblemCandidate,
                ProblemCandidate.id == RadarCase.candidate_id,
            )
            .where(RadarCase.id.in_(target_ids))
        )).all())

        claims = list((await session.execute(
            select(RadarClaim).where(
                RadarClaim.case_id.in_(target_ids),
                RadarClaim.claim_code.in_(["C06", "C07"]),
            )
        )).scalars().all())
        claim_map = {(c.case_id, c.claim_code): c for c in claims}

        def _pair_priority(pair):
            case, _candidate = pair
            gate = target_by_case.get(case.id)
            code = "C06" if gate == "CURRENT_SOLUTION" else "C07"
            claim = claim_map.get((case.id, code))
            cached_same = len(_cached_same_families(claim))
            return (
                -cached_same,
                target_priority.get(int(case.id), 10**9),
                int(case.id),
            )

        session_pairs.sort(key=_pair_priority)

        for case_index, (case, candidate) in enumerate(session_pairs, 1):
            runtime_progress.heartbeat(
                detail="c06/c07 case verification",
                progress={
                    "cases_completed": case_index - 1,
                    "cases_total": len(session_pairs),
                    "case_id": int(case.id),
                    "ai_calls": ai_calls,
                    "ai_allowance": int(ai_call_allowance),
                },
            )
            gate = target_by_case.get(case.id)
            claim_code = "C06" if gate == "CURRENT_SOLUTION" else "C07"
            claim = claim_map.get((case.id, claim_code))
            if claim is None:
                continue

            required_dims = sorted(_required_dimensions(candidate))
            ranked = []
            rejected_dims = []

            seen_family = set()
            for raw in matches.get(candidate.id, []) or []:
                if not _candidate_for_case(
                    raw,
                    candidate_id=candidate.id,
                    case_id=case.id,
                ):
                    continue

                item = dict(raw)
                if not item.get("solution_identity"):
                    item["solution_identity"] = (
                        item.get("repo")
                        or _solution_identity_from_text(item.get("text"))
                    )

                if claim_code == "C06" and not _solution_ai_candidate(item):
                    continue
                if claim_code == "C07" and not _persistent(item):
                    continue

                passed, gate_info = _pre_ai_identity_gate(
                    candidate,
                    item,
                )
                observed = list(gate_info.get("observed_dimensions", []))
                item["required_dimensions"] = required_dims
                item["observed_dimensions"] = observed
                item["identity_gate"] = gate_info

                if not passed:
                    dimension_rejects += 1
                    rejected_dims.append({
                        "title": item.get("title"),
                        "solution": _solution_identity(item),
                        "reason": gate_info.get("reason"),
                        "missing": (
                            gate_info.get("missing_dimensions")
                            or gate_info.get("missing_mechanisms")
                            or []
                        ),
                    })
                    continue

                family = str(item.get("source_family") or "")
                if not family or family in seen_family:
                    continue
                seen_family.add(family)
                ranked.append(item)

                if len(ranked) >= 6:
                    break

            summary = dict(claim.evidence_summary or {})
            cache_key = "same_problem_pairs_v3"
            pair_cache = dict(summary.get(cache_key) or {})

            adjudications = []
            fresh_for_case = 0
            known_same_families = set()

            for idx, item in enumerate(ranked, 1):
                evidence_id = f"EVIDENCE_{idx}"
                pair_fp = hashlib.sha256(
                    (
                        f"{ENGINE_VERSION}|{case.id}|{claim_code}|"
                        f"{item.get('id')}|"
                        + hashlib.sha256(str(item.get("text") or "").encode("utf-8")).hexdigest()[:20]
                        + "|"
                        + "|".join(required_dims)
                        + "|"
                        + json.dumps(
                            item.get("identity_gate") or {},
                            sort_keys=True,
                            ensure_ascii=False,
                        )
                    ).encode("utf-8")
                ).hexdigest()

                cached = pair_cache.get(pair_fp)
                result = None
                validation = None

                if (
                    isinstance(cached, dict)
                    and cached.get("validation") == "OK"
                ):
                    result = dict(cached.get("result") or {})
                    valid, validation = _validate_cached_same_problem(
                        result,
                        case_id=case.id,
                        current_evidence_id=evidence_id,
                    )
                    if valid:
                        ai_cache_hits += 1
                    else:
                        result = None

                if len(known_same_families) >= 2:
                    break

                if result is None:
                    if (
                        ai_calls >= ai_call_allowance
                        or fresh_for_case >= per_case_fresh_cap
                    ):
                        ai_deferred += 1
                        continue

                    budget = await _budget(session, case=case)
                    remaining = max(
                        0.0,
                        float(budget.budget_cap_twd or 0)
                        - float(budget.spent_twd or 0)
                        - float(budget.reserved_twd or 0),
                    )

                    gate_result = evaluate_ai_gate(
                        task_name="same_problem_verify",
                        local_attempted=True,
                        local_result="AMBIGUOUS",
                        estimated_call_cost_twd=ESTIMATED_AI_CALL_TWD,
                        remaining_case_budget_twd=remaining,
                        decision_impact=0.95,
                    )

                    if not gate_result.allowed:
                        ai_gate_denied += 1
                        continue

                    usage = TokenUsage()
                    ai_calls += 1
                    fresh_for_case += 1

                    try:
                        runtime_progress.heartbeat(
                            detail="c06/c07 AI pair adjudication",
                            progress={
                                "cases_completed": case_index - 1,
                                "cases_total": len(session_pairs),
                                "case_id": int(case.id),
                                "pair_index": int(idx),
                                "pairs_ranked": len(ranked),
                                "ai_calls": ai_calls,
                                "ai_allowance": int(ai_call_allowance),
                            },
                        )
                        result = await call_llm(
                            prompt=_same_problem_prompt(
                                case=case,
                                candidate=candidate,
                                item=item,
                                evidence_id=evidence_id,
                            ),
                            system_message=(
                                "You compare two already-retrieved problem "
                                "fingerprints. False SAME_PROBLEM is costly. "
                                "Same domain is insufficient. Use no outside "
                                "knowledge. Return JSON only."
                            ),
                            model=str(task_spec.get("model_tier") or "mini"),
                            temperature=0.0,
                            max_tokens=min(
                                450,
                                int(task_spec.get("max_tokens") or 500),
                            ),
                            parse_json=True,
                            usage_tracker=usage,
                        )

                        valid, validation = _validate_same_problem(
                            result,
                            case_id=case.id,
                            evidence_id=evidence_id,
                        )

                        cost = usage.estimated_cost_usd * USD_TWD_RATE
                        budget.spent_twd = (
                            float(budget.spent_twd or 0) + cost
                        )
                        ai_tokens += int(usage.total_tokens or 0)
                        ai_cost_twd += cost

                        pair_cache[pair_fp] = {
                            "validation": "OK" if valid else validation,
                            "result": result,
                            "item_id": item.get("id"),
                            "source_family": item.get("source_family"),
                            "checked_at": datetime.utcnow().isoformat(),
                            "cost_twd": round(cost, 6),
                        }

                        if not valid:
                            ai_errors += 1
                            validation_failures[validation] += 1
                            result = None

                    except Exception as exc:
                        if usage.calls:
                            cost = usage.estimated_cost_usd * USD_TWD_RATE
                            budget.spent_twd = (
                                float(budget.spent_twd or 0) + cost
                            )
                            ai_tokens += int(usage.total_tokens or 0)
                            ai_cost_twd += cost

                        ai_errors += 1
                        exception_types[type(exc).__name__] += 1
                        pair_cache[pair_fp] = {
                            "validation": "AI_ERROR",
                            "error": f"{type(exc).__name__}: {exc}",
                            "item_id": item.get("id"),
                            "checked_at": datetime.utcnow().isoformat(),
                        }
                        result = None

                if result is None:
                    continue

                verdict = str(result.get("verdict") or "").upper()
                adjudications.append({
                    "item": item,
                    "evidence_id": evidence_id,
                    "verdict": verdict,
                    "matching_dimensions": result.get(
                        "matching_dimensions", []
                    ),
                    "conflicting_dimensions": result.get(
                        "conflicting_dimensions", []
                    ),
                })

                if verdict == "SAME_PROBLEM":
                    same_problem += 1
                    family = str(item.get("source_family") or "").strip()
                    if family:
                        known_same_families.add(family)
                elif verdict == "DIFFERENT_PROBLEM":
                    different_problem += 1
                else:
                    same_problem_insufficient += 1

            summary[cache_key] = pair_cache
            claim.evidence_summary = summary

            same_rows = [
                row
                for row in adjudications
                if row["verdict"] == "SAME_PROBLEM"
            ]
            same_families = {
                str(row["item"].get("source_family") or "")
                for row in same_rows
            }

            case_supported = len(same_families) >= 2

            # Materialize all adjudicated evidence so negative identity checks
            # remain auditable. SUPPORT only after two independent SAME_PROBLEM.
            for row in adjudications:
                item = row["item"]
                ev = await _materialize(
                    session,
                    case_id=case.id,
                    item=item,
                )

                if case_supported and row["verdict"] == "SAME_PROBLEM":
                    stance = "SUPPORT"
                    rationale = (
                        "Same-problem verified by approved AI task "
                        "same_problem_verify after deterministic solution-identity, "
                        "negative-evidence, and failure-dimension gates. "
                        f"Matching dimensions: {row.get('matching_dimensions', [])}."
                    )
                    confidence = 0.86 if claim_code == "C06" else 0.84
                else:
                    stance = "INSUFFICIENT"
                    rationale = (
                        "Pairwise same-problem verification did not provide "
                        "two independent SAME_PROBLEM families. "
                        f"Pair verdict={row['verdict']}; "
                        f"matching={row.get('matching_dimensions', [])}; "
                        f"conflicting={row.get('conflicting_dimensions', [])}."
                    )
                    confidence = 0.72

                created = await _link_claim(
                    session,
                    claim,
                    ev,
                    stance=stance,
                    rationale=rationale,
                    confidence=confidence,
                )
                if stance == "SUPPORT":
                    support_links += int(created)

            await _refresh_claim_state(session, claim)
            state_final = str(claim.state or "UNKNOWN").upper()

            # If C06 just reached real two-family SUPPORT, reuse the exact same
            # pairwise SAME_PROBLEM adjudications for C07 when those documents
            # also contain deterministic persistence evidence. This is not a
            # new epistemic shortcut: identity was already AI-verified and C07
            # still requires two independent persistent families.
            if claim_code == "C06" and state_final == "SUPPORTED":
                c07_claim = claim_map.get((case.id, "C07"))
                if c07_claim is not None and str(c07_claim.state or "").upper() != "SUPPORTED":
                    c07_same_cycle_evaluated += 1
                    persistent_rows = [
                        row for row in same_rows if _persistent(row["item"])
                    ]
                    persistent_families = {
                        str(row["item"].get("source_family") or "")
                        for row in persistent_rows
                        if str(row["item"].get("source_family") or "")
                    }
                    persistent_supported = len(persistent_families) >= 2
                    for row in persistent_rows:
                        ev = await _materialize(
                            session, case_id=case.id, item=row["item"]
                        )
                        stance = "SUPPORT" if persistent_supported else "INSUFFICIENT"
                        created = await _link_claim(
                            session,
                            c07_claim,
                            ev,
                            stance=stance,
                            rationale=(
                                "C06 same-problem identity was already verified; "
                                "the same evidence also passes the deterministic "
                                "persistence contract for C07. Two independent "
                                "persistent families are still required."
                            ),
                            confidence=0.84 if persistent_supported else 0.72,
                        )
                        if stance == "SUPPORT":
                            support_links += int(created)
                    await _refresh_claim_state(session, c07_claim)
                    if str(c07_claim.state or "").upper() == "SUPPORTED":
                        c07_same_cycle_supported += 1

            if case_supported:
                ai_support += 1
            elif adjudications:
                ai_insufficient += 1

            all_ranked_checked = (
                bool(ranked)
                and len(adjudications) >= len(ranked)
            )
            status_key = (
                "solution_research_status_v1"
                if claim_code == "C06"
                else "gap_research_status_v1"
            )

            summary = dict(claim.evidence_summary or {})
            if state_final == "SUPPORTED":
                status = "SUPPORTED"
            elif (
                all_ranked_checked
                and len(ranked) >= 3
                and len({str(x.get("source_family") or "") for x in ranked}) >= 2
            ):
                status = "SOURCE_SET_EXHAUSTED"
            else:
                status = "INSUFFICIENT"

            summary[status_key] = {
                "status": status,
                "method": "pairwise_same_problem_v1",
                "required_dimensions": required_dims,
                "ranked_candidates": len(ranked),
                "adjudicated_pairs": len(adjudications),
                "same_problem_families": len(same_families),
                "dimension_rejects": len(rejected_dims),
                "corpus_docs": len(docs),
                "updated_at": datetime.utcnow().isoformat(),
            }
            if status == "SOURCE_SET_EXHAUSTED":
                summary[status_key]["recheck_after"] = (
                    datetime.utcnow() + timedelta(days=7)
                ).isoformat()
                summary[status_key]["warning"] = (
                    "Current configured solution evidence set did not yield "
                    "two independent SAME_PROBLEM families. This is not REFUTE."
                )

            claim.evidence_summary = summary

            details[case.id] = {
                "case_id": case.id,
                "title": candidate.title,
                "claim_code": claim_code,
                "claim_state": state_final,
                "research_status": status,
                "required_dimensions": required_dims,
                "ranked_candidates": len(ranked),
                "adjudicated_pairs": len(adjudications),
                "same_problem_families": len(same_families),
                "dimension_rejects": len(rejected_dims),
                "pairs": [
                    {
                        "solution": _solution_identity(row["item"]),
                        "source_type": row["item"].get("source_type"),
                        "family": row["item"].get("source_family"),
                        "title": row["item"].get("title"),
                        "verdict": row["verdict"],
                        "matching_dimensions": row.get(
                            "matching_dimensions", []
                        ),
                        "conflicting_dimensions": row.get(
                            "conflicting_dimensions", []
                        ),
                    }
                    for row in adjudications
                ],
                "identity_gate_rejected_examples": rejected_dims[:5],
            }
            runtime_progress.heartbeat(
                detail="c06/c07 case complete",
                progress={
                    "cases_completed": case_index,
                    "cases_total": len(session_pairs),
                    "case_id": int(case.id),
                    "ai_calls": ai_calls,
                    "ai_allowance": int(ai_call_allowance),
                    "support_links": support_links,
                },
            )

        await session.commit()

    return {
        "engine_version": ENGINE_VERSION,
        "cases": len(target_by_case),
        "c06_targets": sum(
            1 for gate in target_by_case.values()
            if gate == "CURRENT_SOLUTION"
        ),
        "c07_targets": sum(
            1 for gate in target_by_case.values()
            if gate == "UNRESOLVED_GAP"
        ),
        "corpus": {
            "github_issues": len(github_rows),
            "external_direct": len(external_rows),
            "product_reviews": len(review_rows),
            "product_review_posts": len(review_posts),
            "community_solution_posts": len(community_docs),
            "radar_evidence": len(radar_rows),
            "docs": len(docs),
        },
        "support_links": support_links,
        "ai_calls": ai_calls,
        "ai_cache_hits": ai_cache_hits,
        "ai_support": ai_support,
        "ai_insufficient": ai_insufficient,
        "ai_errors": ai_errors,
        "ai_gate_denied": ai_gate_denied,
        "ai_deferred": ai_deferred,
        "ai_tokens": ai_tokens,
        "ai_cost_twd": round(ai_cost_twd, 6),
        "same_problem": same_problem,
        "different_problem": different_problem,
        "same_problem_insufficient": same_problem_insufficient,
        "dimension_rejects": dimension_rejects,
        "c07_same_cycle_evaluated": c07_same_cycle_evaluated,
        "c07_same_cycle_supported": c07_same_cycle_supported,
        "ai_validation_failures": dict(validation_failures),
        "ai_exception_types": dict(exception_types),
        "details": details,
        "allocation_version": ALLOCATION_VERSION,
        "per_case_fresh_cap": per_case_fresh_cap,
    }
