"""AI Opportunity Radar — Opportunity Engine v2

A precision-first business-problem discovery engine.

Pipeline
--------
raw HN / Reddit rows
    -> explicit actionable-friction filter
    -> independent discussion aggregation
    -> batched LLM Problem Fingerprints
    -> deterministic candidate retrieval
    -> batched LLM same-problem verification
    -> component-level coherence verification
    -> deterministic community opportunity signal
    -> auditable Opportunity + Evidence rows

Design rules
------------
- One viral thread is not repeated demand.
- Topic similarity is not problem equivalence.
- LLMs extract/verify meaning; they do not invent the final numeric score.
- Unknown Reddit timestamps never masquerade as recent growth.
- Missing external supply/market evidence stays neutral, not "high opportunity".
- False positives are more costly than missed weak opportunities.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import html
import json
import math
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import structlog
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from database.connection import (
    async_session,
    Opportunity,
    OpportunityEvidence,
    Platform,
    Post,
)
from processors.llm_client import TokenUsage, call_llm

log = structlog.get_logger().bind(processor="opportunity_engine_v2")

ENGINE_VERSION = "v2.1-solo-transition-atom"
CACHE_DIR = Path(".radar_cache")
FINGERPRINT_CACHE = CACHE_DIR / "opportunity_v2_fingerprints.json"
PAIR_CACHE = CACHE_DIR / "opportunity_v2_pair_verdicts.json"

FINGERPRINT_BATCH_SIZE = 8
PAIR_VERIFY_BATCH_SIZE = 14
MAX_PAIR_CANDIDATES = 180
MAX_NEIGHBORS_PER_DISCUSSION = 6

URL_RE = re.compile(r"https?://\S+|www\.\S+", re.I)
MD_LINK_RE = re.compile(r"\[([^\]]+)\]\((?:https?://)?[^)]+\)")
TAG_RE = re.compile(r"<[^>]+>")
CODE_FENCE_RE = re.compile(r"```.*?```", re.S)
REDDIT_THREAD_RE = re.compile(r"/comments/([a-z0-9]+)/", re.I)
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
REDDIT_BOILERPLATE_RE = re.compile(
    r"submitted\s+by\s+/u/\S+.*?(?:\[link\]|\[comments\]|$)",
    re.I | re.S,
)

# Admission must represent something a product/service/process could plausibly fix.
ACTIONABLE_FRICTION_RE = re.compile(
    r"""(?ix)
    \b(
        frustrat\w* |
        broken |
        unusable |
        unreliable |
        inconsistent |
        regress(?:ion|ed|ing)? |
        keeps?\s+(?:breaking|failing|ignoring|forgetting|crashing|resetting) |
        doesn['’]?t\s+(?:work|follow|remember|respect|connect|integrate|deploy|load|run|fit) |
        does\s+not\s+(?:work|follow|remember|respect|connect|integrate|deploy|load|run|fit) |
        won['’]?t\s+(?:work|follow|remember|respect|connect|integrate|deploy|load|run|fit) |
        will\s+not\s+(?:work|follow|remember|respect|connect|integrate|deploy|load|run|fit) |
        can['’]?t\s+(?:use|change|configure|deploy|integrate|connect|debug|control|manage|run|load|fit|access|export|import|recover|switch|remove|disable|enable|get|make) |
        cannot\s+(?:use|change|configure|deploy|integrate|connect|debug|control|manage|run|load|fit|access|export|import|recover|switch|remove|disable|enable|get|make) |
        fail(?:s|ed|ing)?\s+to\s+(?:work|follow|remember|respect|connect|integrate|deploy|load|run|call|use) |
        no\s+good\s+way\s+to |
        wish\s+there\s+was |
        someone\s+needs\s+to\s+build |
        why\s+is\b.{0,50}\bso\s+hard |
        why\s+can['’]?t\s+(?:i|we|you|it)\s+ |
        gave\s+up\s+(?:on|trying) |
        workaround |
        work\s*around |
        waste(?:d|s|ing)?\s+(?:my\s+)?(?:time|hours?) |
        cannot\s+be\s+changed |
        can['’]?t\s+be\s+changed |
        hard\s+to\s+(?:use|debug|deploy|integrate|manage|control|configure|maintain|test) |
        difficult\s+to\s+(?:use|debug|deploy|integrate|manage|control|configure|maintain|test)
    )\b
    """
)

PRODUCT_CONTEXT_RE = re.compile(
    r"""(?ix)
    \b(
        ai | llm | model | agent | api | sdk | software | app | tool |
        developer | engineer | code | coding | database | workflow |
        automation | deploy\w* | hosting | cloud | github | prompt |
        rag | vector | embedding | gpu | inference | chatgpt | claude |
        openai | cursor | copilot | product | service | platform |
        startup | business | customer | pricing | subscription |
        enterprise | documentation | docs | integration | server |
        devops | saas | package | library | framework | account |
        authentication | auth | permission | memory | context |
        email | browser | extension | local\s+llm
    )\b
    """
)

BUYER_TERMS = {
    "developer", "engineer", "team", "company", "business", "customer",
    "enterprise", "client", "paid", "pricing", "subscription", "budget",
    "professional", "production", "startup", "agency", "manager",
}

STRONG_PAIN_TERMS = {
    "unusable", "broken", "impossible", "gave up", "waste", "hours",
    "fails", "failing", "unreliable", "keeps breaking", "keeps failing",
}

GENERIC_TERMS = {
    "ai", "llm", "model", "models", "people", "use", "using", "used",
    "like", "just", "really", "think", "thing", "things", "good", "bad",
    "new", "way", "need", "know", "work", "works", "problem", "problems",
    "issue", "issues", "user", "users", "content", "generated", "system",
    "systems", "make", "makes", "making", "human", "humans", "machine",
    "machines", "author", "authors", "day", "time", "real", "feedback",
    "company", "companies", "person", "someone", "something",
}

FINGERPRINT_FIELDS = (
    "actor",
    "task",
    "object",
    "failure_mode",
    "consequence",
    "canonical_problem",
    "legacy_workflow",
)


def clamp(x: float, lo: float = 0, hi: float = 100) -> float:
    return round(max(lo, min(hi, x)), 1)


def chunks(items: list[Any], size: int):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def load_json(path: Path) -> dict:
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {}


def save_json_atomic(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    tmp.replace(path)


def get_sentiment(meta) -> float | None:
    if not isinstance(meta, dict):
        return None
    s = meta.get("sentiment")
    if not isinstance(s, dict):
        return None
    try:
        return float(s.get("compound", 0))
    except (TypeError, ValueError):
        return None


def strip_quotes(text: str) -> str:
    return "\n".join(
        line for line in text.splitlines()
        if not line.lstrip().startswith(">")
    )


def clean_text(title: str | None, body: str | None) -> str:
    title = html.unescape(title or "")
    body = html.unescape(body or "")
    title = TAG_RE.sub(" ", title)
    body = TAG_RE.sub(" ", body)
    body = strip_quotes(body)
    body = CODE_FENCE_RE.sub(" ", body)
    body = REDDIT_BOILERPLATE_RE.sub(" ", body)
    title = MD_LINK_RE.sub(r"\1", title)
    body = MD_LINK_RE.sub(r"\1", body)
    title = URL_RE.sub(" ", title)
    body = URL_RE.sub(" ", body)

    for junk in ("x2f", "x27", "x3e", "x3c", "amp", "quot"):
        title = re.sub(rf"\b{junk}\b", " ", title, flags=re.I)
        body = re.sub(rf"\b{junk}\b", " ", body, flags=re.I)

    title = re.sub(r"\s+", " ", title).strip()
    body = re.sub(r"\s+", " ", body).strip()

    nt = re.sub(r"\W+", " ", title.lower()).strip()
    nb = re.sub(r"\W+", " ", body.lower()).strip()

    if nt and nb == nt:
        combined = title
    elif nt and nb.startswith(nt) and len(nb) < len(nt) * 1.35:
        combined = body
    else:
        combined = f"{title}. {body}" if title and body else title or body

    combined = re.sub(r"\b\d{4,}\b", " ", combined)
    return re.sub(r"\s+", " ", combined).strip()[:2200]


def extract_problem_text(text: str) -> str:
    sentences = SENTENCE_SPLIT_RE.split(text)
    selected = []
    for i, sentence in enumerate(sentences):
        if ACTIONABLE_FRICTION_RE.search(sentence):
            selected.extend(
                sentences[max(0, i - 1): min(len(sentences), i + 2)]
            )

    seen = set()
    out = []
    for sentence in selected:
        normalized = normalize_text(sentence)
        if len(normalized) < 12 or normalized in seen:
            continue
        seen.add(normalized)
        out.append(sentence.strip())

    return " ".join(out)[:1200] if out else text[:1200]


def normalize_text(text: str | None) -> str:
    return re.sub(
        r"\s+",
        " ",
        re.sub(r"[^a-z0-9]+", " ", (text or "").lower()),
    ).strip()


def token_set(text: str | None) -> set[str]:
    return {
        t for t in normalize_text(text).split()
        if len(t) >= 3 and t not in GENERIC_TERMS
    }


def content_hash(text: str) -> str:
    return hashlib.sha1(normalize_text(text).encode("utf-8")).hexdigest()


def canonical_key(title: str, fingerprints: list[dict]) -> str:
    parts = [normalize_text(title)]
    for fp in fingerprints:
        parts.extend([
            normalize_text(fp.get("task")),
            normalize_text(fp.get("object")),
            normalize_text(fp.get("failure_mode")),
        ])
    material = "|".join(sorted(set(p for p in parts if p)))
    return hashlib.sha1(material.encode("utf-8")).hexdigest()[:20]


def confidence_label(value: float) -> str:
    if value >= 75:
        return "HIGH"
    if value >= 55:
        return "MEDIUM"
    return "LOW"


class UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))
        self.rank = [0] * n

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int):
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self.rank[ra] < self.rank[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        if self.rank[ra] == self.rank[rb]:
            self.rank[ra] += 1


class OpportunityEngine:
    def __init__(self, *, fingerprint_ai_call_allowance: int | None = None):
        self.usage = TokenUsage()
        self.errors = 0
        self.fp_cache = load_json(FINGERPRINT_CACHE)
        self.pair_cache = load_json(PAIR_CACHE)
        self.fingerprint_ai_call_allowance = (
            None
            if fingerprint_ai_call_allowance is None
            else max(0, int(fingerprint_ai_call_allowance))
        )
        self.fingerprint_ai_calls = 0

    async def run(self, preview: bool = False) -> dict:
        candidates = await self.find_candidates()
        discussions = self.build_discussions(candidates)

        print("\n" + "=" * 100)
        print("AI OPPORTUNITY RADAR — OPPORTUNITY ENGINE V2")
        print("=" * 100)
        print(f"Raw actionable evidence rows: {len(candidates)}")
        print(f"Independent candidate discussions: {len(discussions)}")
        print(f"Sources: {dict(Counter(d['platform'] for d in discussions))}")
        print(
            f"Known-time discussions: "
            f"{sum(d['observed_at'] is not None for d in discussions)}"
        )
        print(
            f"Unknown-time discussions: "
            f"{sum(d['observed_at'] is None for d in discussions)}"
        )

        fingerprints = await self.extract_fingerprints(discussions)
        usable = [
            d for d in discussions
            if d.get("fingerprint")
            and d["fingerprint"].get("actionable_problem") is True
            and float(d["fingerprint"].get("confidence", 0) or 0) >= 0.65
            and d["fingerprint"].get("opinion_or_news_only") is not True
        ]

        print(f"Usable structured problem discussions: {len(usable)}")
        print(
            f"Fingerprint cache: "
            f"{sum(d.get('_fingerprint_cache_hit', False) for d in discussions)} hits / "
            f"{sum(not d.get('_fingerprint_cache_hit', False) for d in discussions)} misses"
        )

        pair_candidates = self.retrieve_candidate_pairs(usable)
        print(f"Candidate same-problem pairs after local retrieval: {len(pair_candidates)}")

        verified_edges = await self.verify_pairs(usable, pair_candidates)
        print(f"Verified same-problem edges: {len(verified_edges)}")

        components = self.build_components(usable, verified_edges)
        print(f"Multi-discussion components before final gate: {len(components)}")

        accepted = []
        rejected = 0
        for component in components:
            verdict = await self.verify_component(component)
            if not verdict or verdict.get("coherent") is not True:
                rejected += 1
                continue
            accepted.append((component, verdict))

        print(f"Final accepted recurring problems: {len(accepted)}")
        print(f"Final rejected components: {rejected}")

        for i, (component, verdict) in enumerate(accepted, 1):
            all_users = set()
            source_discussions = Counter()
            for d in component:
                all_users.update(d["user_ids"])
                source_discussions[d["platform"]] += 1
            print(
                f"\n#{i} {verdict.get('title', 'Untitled recurring problem')}\n"
                f"   discussions={len(component)} users={len(all_users)} "
                f"sources={dict(source_discussions)}\n"
                f"   {verdict.get('problem_statement', '')}"
            )

        save_json_atomic(FINGERPRINT_CACHE, self.fp_cache)
        save_json_atomic(PAIR_CACHE, self.pair_cache)

        if preview:
            print("\nPREVIEW: v2 analysis completed; Opportunity DB rows were not written.")
            return {
                "engine_version": ENGINE_VERSION,
                "candidate_rows": len(candidates),
                "discussions": len(discussions),
                "usable_fingerprints": len(usable),
                "candidate_pairs": len(pair_candidates),
                "verified_edges": len(verified_edges),
                "accepted": len(accepted),
                "llm_cost_usd": round(self.usage.estimated_cost_usd, 6),
                "preview": True,
            }

        persisted = 0
        for component, verdict in accepted:
            try:
                await self.persist(component, verdict)
                persisted += 1
            except Exception as exc:
                self.errors += 1
                log.warning("opportunity_persist_failed", error=str(exc))

        log.info(
            "opportunity_engine_v2_complete",
            persisted=persisted,
            rejected=rejected,
            errors=self.errors,
            llm_cost=f"${self.usage.estimated_cost_usd:.4f}",
        )

        print("\n" + "-" * 100)
        print(
            f"Persisted opportunities: {persisted} | "
            f"Errors: {self.errors} | "
            f"Tracked LLM cost this run: ${self.usage.estimated_cost_usd:.4f}"
        )
        print(
            "Evidence scope: COMMUNITY ONLY (HN + Reddit). "
            "GitHub / Jobs / YC / Packages enrichment is not scored yet."
        )

        return {
            "engine_version": ENGINE_VERSION,
            "opportunities": persisted,
            "clusters_rejected": rejected,
            "errors": self.errors,
            "llm_cost_usd": round(self.usage.estimated_cost_usd, 6),
        }

    async def find_candidates(self) -> list[dict]:
        cutoff = datetime.utcnow() - timedelta(days=30)

        async with async_session() as session:
            rows = (
                await session.execute(
                    select(
                        Post.id,
                        Post.user_id,
                        Post.platform_post_id,
                        Post.post_type,
                        Post.title,
                        Post.body,
                        Post.url,
                        Post.subreddit,
                        Post.score,
                        Post.num_comments,
                        Post.posted_at,
                        Post.raw_metadata,
                        Platform.name,
                    )
                    .join(Platform, Post.platform_id == Platform.id)
                    .where(
                        Post.body.isnot(None),
                        Platform.name.in_(["reddit", "hackernews"]),
                    )
                    .order_by(Post.posted_at.desc().nullslast())
                    .limit(12000)
                )
            ).all()

        hn_parent: dict[str, str] = {}
        for row in rows:
            meta = row[11] if isinstance(row[11], dict) else {}
            platform = row[12]
            if platform != "hackernews":
                continue

            hn_id = str(meta.get("hn_id") or "").strip()
            if not hn_id:
                platform_id = str(row[2] or "")
                if platform_id.startswith("hn_"):
                    hn_id = platform_id[3:]

            parent = str(meta.get("parent_hn_id") or "").strip()
            if hn_id and parent:
                hn_parent[hn_id] = parent

        def hn_root(hn_id: str) -> str:
            current = hn_id
            seen = set()
            for _ in range(16):
                if not current or current in seen:
                    break
                seen.add(current)
                parent = hn_parent.get(current)
                if not parent:
                    break
                current = parent
            return current or hn_id

        out = []
        seen_exact = set()

        for row in rows:
            (
                post_id,
                user_id,
                platform_post_id,
                post_type,
                title,
                body,
                url,
                subreddit,
                score,
                num_comments,
                posted_at,
                meta,
                platform,
            ) = row

            meta = meta if isinstance(meta, dict) else {}

            # HN has timestamps. Current Reddit RSS rows in this dataset do not.
            # Keep unknown-time rows, but never use them as "recent growth".
            if posted_at is not None and posted_at < cutoff:
                continue

            text = clean_text(title, body)
            if len(text) < 45:
                continue
            if not ACTIONABLE_FRICTION_RE.search(text):
                continue
            if not PRODUCT_CONTEXT_RE.search(text):
                continue

            problem_text = extract_problem_text(text)
            digest = content_hash(problem_text)
            if digest in seen_exact:
                continue
            seen_exact.add(digest)

            if platform == "reddit":
                root = str(meta.get("parent_post_id") or "").strip()
                if not root and url:
                    match = REDDIT_THREAD_RE.search(url)
                    if match:
                        root = match.group(1)

                if not root:
                    platform_id = str(platform_post_id or "")
                    if (
                        platform_id.startswith("reddit_")
                        and not platform_id.startswith("reddit_comment_")
                    ):
                        root = platform_id[len("reddit_"):]

                discussion_key = (
                    f"reddit:{root or platform_post_id or post_id}"
                )
            else:
                hn_id = str(meta.get("hn_id") or "").strip()
                if not hn_id:
                    platform_id = str(platform_post_id or "")
                    if platform_id.startswith("hn_"):
                        hn_id = platform_id[3:]
                root = hn_root(hn_id) if hn_id else ""
                discussion_key = f"hackernews:{root or post_id}"

            out.append({
                "id": post_id,
                "user_id": user_id,
                "source_ref": str(platform_post_id or post_id),
                "post_type": str(post_type or ""),
                "title": title or "",
                "text": text,
                "problem_text": problem_text,
                "url": url,
                "subreddit": subreddit,
                "score": score or 0,
                "num_comments": num_comments or 0,
                "posted_at": posted_at,
                "time_unknown": posted_at is None,
                "sentiment": get_sentiment(meta),
                "platform": platform,
                "discussion_key": discussion_key,
            })

        return out

    def build_discussions(self, posts: list[dict]) -> list[dict]:
        grouped = defaultdict(list)
        for post in posts:
            grouped[post["discussion_key"]].append(post)

        discussions = []
        for key, rows in grouped.items():
            rows.sort(
                key=lambda p: (
                    p["post_type"] == "submission",
                    p["score"] + min(p["num_comments"], 100),
                ),
                reverse=True,
            )

            snippets = []
            seen = set()
            for post in rows:
                normalized = normalize_text(post["problem_text"])
                if normalized in seen:
                    continue
                seen.add(normalized)
                snippets.append(post["problem_text"][:500])
                if len(snippets) >= 6:
                    break

            problem_text = " ".join(snippets)[:2600]
            if len(problem_text) < 45:
                continue

            dated = [p["posted_at"] for p in rows if p["posted_at"]]
            discussions.append({
                "discussion_key": key,
                "platform": rows[0]["platform"],
                "subreddit": rows[0].get("subreddit"),
                "problem_text": problem_text,
                "posts": rows,
                "user_ids": {
                    p["user_id"] for p in rows if p["user_id"] is not None
                },
                "observed_at": max(dated) if dated else None,
                "time_unknown": not bool(dated),
                "content_hash": content_hash(problem_text),
            })

        discussions.sort(
            key=lambda d: (
                len(d["user_ids"]),
                len(d["posts"]),
            ),
            reverse=True,
        )
        return discussions

    async def extract_fingerprints(self, discussions: list[dict]) -> list[dict]:
        missing = []

        for discussion in discussions:
            cached = self.fp_cache.get(discussion["content_hash"])
            if isinstance(cached, dict) and cached.get("engine_version") == ENGINE_VERSION:
                discussion["fingerprint"] = cached.get("fingerprint")
                discussion["_fingerprint_cache_hit"] = True
            else:
                discussion["_fingerprint_cache_hit"] = False
                missing.append(discussion)

        for batch in chunks(missing, FINGERPRINT_BATCH_SIZE):
            if (
                self.fingerprint_ai_call_allowance is not None
                and self.fingerprint_ai_calls >= self.fingerprint_ai_call_allowance
            ):
                break
            payload = []
            by_id = {}
            for i, discussion in enumerate(batch):
                local_id = f"D{i+1}"
                by_id[local_id] = discussion
                payload.append({
                    "id": local_id,
                    "source": discussion["platform"],
                    "text": discussion["problem_text"][:1300],
                })

            prompt = f"""Extract a structured problem fingerprint for each independent community discussion.

INPUT:
{json.dumps(payload, ensure_ascii=False)}

Return JSON with this exact shape:
{{
  "items": [
    {{
      "id": "D1",
      "actionable_problem": true,
      "opportunity_unit_ready": true,
      "opinion_or_news_only": false,
      "confidence": 0.0,
      "actor": "specific user/group or unclear",
      "actor_category": "developer|business|consumer|researcher|creator|operator|other|unclear",
      "task": "what they are trying to do",
      "object": "product/system/workflow involved",
      "failure_mode": "what specifically fails, is impossible, unreliable, costly, or missing",
      "consequence": "concrete cost/harm caused by the failure, or unclear",
      "workaround": "explicit workaround, or none mentioned",
      "buyer_context": "explicit professional/business/payment context, or unclear",
      "change_signal": "explicit technology/platform/regulation/cost/behavior change, or unclear",
      "legacy_workflow": "explicit old/manual/current workflow still being used, or unclear",
      "transition_gap": "explicit evidence that adoption/current supply has not caught up with the change, or unclear",
      "canonical_problem": "short normalized Actor + workflow + failure description",
      "severity": 1
    }}
  ]
}}

Rules:
- This is problem extraction, NOT startup ideation. Never invent a product or solution.
- actionable_problem=false for pure opinions, culture/policy debates, generic predictions,
  benchmarks without a user failure, news summaries, or vague dislike.
- opportunity_unit_ready=true ONLY when the text supports a narrow Actor + concrete workflow/task + concrete failure + consequence.
- opportunity_unit_ready=false for broad research themes such as "AI is unreliable", "LLMs hallucinate", "AI makes juniors worse", or an entire industry problem.
- If one discussion contains several materially different failures, extract the dominant explicitly supported one; do not merge them into a broad umbrella.
- A frontier technical bug may still be an actionable_problem, but do not make it broader than the exact configuration/failure stated.
- Do not infer willingness to pay, buyer identity, transition, adoption lag, or economic loss. Use "unclear" when absent.
- change_signal / legacy_workflow / transition_gap must be explicit in the supplied text; otherwise "unclear".
- Do not convert a broad topic into a problem.
- failure_mode must describe the actual failure relation, not merely a noun like "email" or "AI".
- canonical_problem must preserve the concrete workflow and failure; never normalize upward to an industry-wide theme.
- severity is 1-5 based only on consequences visible in the discussion.
- confidence is 0-1 for how clearly the discussion supports the fingerprint.
"""

            self.fingerprint_ai_calls += 1
            result = await call_llm(
                prompt=prompt,
                system_message=(
                    "You are a skeptical product research analyst. "
                    "Extract only problems supported by the supplied text. "
                    "False positives are more costly than omissions."
                ),
                model="mini",
                parse_json=True,
                usage_tracker=self.usage,
                max_tokens=2600,
            )

            items = result.get("items", []) if isinstance(result, dict) else []
            returned = {
                str(item.get("id")): item
                for item in items
                if isinstance(item, dict)
            }

            for local_id, discussion in by_id.items():
                fp = returned.get(local_id)
                if not isinstance(fp, dict):
                    fp = {
                        "actionable_problem": False,
                        "opportunity_unit_ready": False,
                        "opinion_or_news_only": False,
                        "confidence": 0,
                        "actor": "unclear",
                        "actor_category": "unclear",
                        "task": "",
                        "object": "",
                        "failure_mode": "",
                        "consequence": "",
                        "workaround": "none mentioned",
                        "buyer_context": "unclear",
                        "change_signal": "unclear",
                        "legacy_workflow": "unclear",
                        "transition_gap": "unclear",
                        "canonical_problem": "",
                        "severity": 1,
                    }

                # Defensive normalization.
                try:
                    fp["confidence"] = max(
                        0.0,
                        min(1.0, float(fp.get("confidence", 0) or 0)),
                    )
                except Exception:
                    fp["confidence"] = 0.0

                try:
                    fp["severity"] = max(
                        1,
                        min(5, int(fp.get("severity", 1) or 1)),
                    )
                except Exception:
                    fp["severity"] = 1

                discussion["fingerprint"] = fp
                self.fp_cache[discussion["content_hash"]] = {
                    "engine_version": ENGINE_VERSION,
                    "fingerprint": fp,
                }

            save_json_atomic(FINGERPRINT_CACHE, self.fp_cache)

        return discussions

    def fingerprint_text(self, fp: dict) -> str:
        parts = []
        for field in FINGERPRINT_FIELDS:
            value = str(fp.get(field) or "").strip()
            if value and value.lower() not in {"unclear", "none", "none mentioned"}:
                weight = 2 if field in {"task", "failure_mode", "canonical_problem"} else 1
                parts.extend([f"{field} {value}"] * weight)
        return " ".join(parts)

    def retrieve_candidate_pairs(self, discussions: list[dict]) -> list[dict]:
        if len(discussions) < 2:
            return []

        texts = [
            self.fingerprint_text(d["fingerprint"])
            for d in discussions
        ]

        vectorizer = TfidfVectorizer(
            stop_words="english",
            ngram_range=(1, 2),
            min_df=1,
            sublinear_tf=True,
        )
        X = vectorizer.fit_transform(texts)
        similarity = cosine_similarity(X)

        pairs = {}
        for i in range(len(discussions)):
            order = np.argsort(similarity[i])[::-1]
            neighbors = 0

            for j in order:
                if i == j or j < i:
                    continue

                sim = float(similarity[i, j])
                fpa = discussions[i]["fingerprint"]
                fpb = discussions[j]["fingerprint"]

                task_overlap = self.field_overlap(fpa.get("task"), fpb.get("task"))
                object_overlap = self.field_overlap(fpa.get("object"), fpb.get("object"))
                failure_overlap = self.field_overlap(
                    fpa.get("failure_mode"),
                    fpb.get("failure_mode"),
                )

                # Broad retrieval only. The LLM verifier still decides equivalence.
                candidate = (
                    sim >= 0.18
                    or (failure_overlap >= 0.25 and (task_overlap >= 0.15 or object_overlap >= 0.15))
                )
                if not candidate:
                    continue

                score = (
                    sim * 0.55
                    + failure_overlap * 0.25
                    + task_overlap * 0.12
                    + object_overlap * 0.08
                )

                pair_id = f"{i}:{j}"
                pairs[pair_id] = {
                    "pair_id": pair_id,
                    "i": i,
                    "j": j,
                    "retrieval_score": round(score, 4),
                }

                neighbors += 1
                if neighbors >= MAX_NEIGHBORS_PER_DISCUSSION:
                    break

        ranked = sorted(
            pairs.values(),
            key=lambda x: x["retrieval_score"],
            reverse=True,
        )
        return ranked[:MAX_PAIR_CANDIDATES]

    @staticmethod
    def field_overlap(a: str | None, b: str | None) -> float:
        sa, sb = token_set(a), token_set(b)
        if not sa or not sb:
            return 0.0
        return len(sa & sb) / len(sa | sb)

    def pair_cache_key(self, a: dict, b: dict) -> str:
        ha, hb = sorted([a["content_hash"], b["content_hash"]])
        return hashlib.sha1(f"{ENGINE_VERSION}|{ha}|{hb}".encode()).hexdigest()

    async def verify_pairs(
        self,
        discussions: list[dict],
        pairs: list[dict],
    ) -> list[dict]:
        verified = []
        missing = []

        for pair in pairs:
            a, b = discussions[pair["i"]], discussions[pair["j"]]
            key = self.pair_cache_key(a, b)
            cached = self.pair_cache.get(key)
            if isinstance(cached, dict):
                verdict = cached
                if (
                    verdict.get("same_problem") is True
                    and float(verdict.get("confidence", 0) or 0) >= 0.80
                ):
                    verified.append({**pair, "verdict": verdict})
            else:
                missing.append(pair)

        for batch in chunks(missing, PAIR_VERIFY_BATCH_SIZE):
            prompt_pairs = []
            local_map = {}

            for n, pair in enumerate(batch):
                local_id = f"P{n+1}"
                local_map[local_id] = pair
                a = discussions[pair["i"]]
                b = discussions[pair["j"]]
                prompt_pairs.append({
                    "id": local_id,
                    "a": {
                        k: a["fingerprint"].get(k)
                        for k in FINGERPRINT_FIELDS
                    },
                    "b": {
                        k: b["fingerprint"].get(k)
                        for k in FINGERPRINT_FIELDS
                    },
                })

            prompt = f"""Decide whether each pair describes the SAME underlying actionable problem.

INPUT:
{json.dumps(prompt_pairs, ensure_ascii=False)}

Return:
{{
  "pairs": [
    {{
      "id": "P1",
      "same_problem": false,
      "confidence": 0.0,
      "reason": "short reason"
    }}
  ]
}}

Same problem requires:
- materially compatible actor/use context,
- the same or equivalent task,
- the same underlying failure relation,
- and a product addressing one would plausibly address the other.

Reject pairs that merely share a topic/product/noun.
Examples that MUST be false:
- cannot change Claude account email vs Fastmail misclassifies email
- database single-point-of-failure vs privacy app has no central server
- AI art authorship debate vs company staffing/adoption problem

Be conservative. False positives are more costly than false negatives.
"""

            result = await call_llm(
                prompt=prompt,
                system_message=(
                    "You are a strict problem-equivalence verifier. "
                    "Topic similarity is not problem equivalence."
                ),
                model="mini",
                parse_json=True,
                usage_tracker=self.usage,
                max_tokens=1800,
            )

            returned = {}
            if isinstance(result, dict):
                returned = {
                    str(item.get("id")): item
                    for item in result.get("pairs", [])
                    if isinstance(item, dict)
                }

            for local_id, pair in local_map.items():
                a, b = discussions[pair["i"]], discussions[pair["j"]]
                cache_key = self.pair_cache_key(a, b)
                verdict = returned.get(local_id) or {
                    "same_problem": False,
                    "confidence": 0,
                    "reason": "missing verifier result",
                }

                try:
                    verdict["confidence"] = max(
                        0.0,
                        min(1.0, float(verdict.get("confidence", 0) or 0)),
                    )
                except Exception:
                    verdict["confidence"] = 0.0

                self.pair_cache[cache_key] = verdict

                if (
                    verdict.get("same_problem") is True
                    and verdict["confidence"] >= 0.80
                ):
                    verified.append({**pair, "verdict": verdict})

            save_json_atomic(PAIR_CACHE, self.pair_cache)

        return verified

    def build_components(
        self,
        discussions: list[dict],
        verified_edges: list[dict],
    ) -> list[list[dict]]:
        if not verified_edges:
            return []

        uf = UnionFind(len(discussions))
        for edge in verified_edges:
            uf.union(edge["i"], edge["j"])

        groups = defaultdict(list)
        for i, discussion in enumerate(discussions):
            groups[uf.find(i)].append(discussion)

        components = []
        for group in groups.values():
            if len(group) < 2:
                continue

            platforms = {d["platform"] for d in group}
            users = set()
            for d in group:
                users.update(d["user_ids"])

            # Cross-source corroboration can qualify with 2 independent
            # discussions. Same-source requires 3.
            if len(platforms) == 1 and len(group) < 3:
                continue
            if len(users) < 2:
                continue

            components.append(group)

        components.sort(
            key=lambda c: (
                len({d["platform"] for d in c}),
                len(c),
                sum(len(d["user_ids"]) for d in c),
            ),
            reverse=True,
        )
        return components

    async def verify_component(self, component: list[dict]) -> dict | None:
        evidence = []
        for i, discussion in enumerate(component[:10]):
            fp = discussion["fingerprint"]
            evidence.append({
                "id": f"D{i+1}",
                "source": discussion["platform"],
                "time_known": discussion["observed_at"] is not None,
                "fingerprint": {
                    k: fp.get(k)
                    for k in (
                        "actor",
                        "actor_category",
                        "task",
                        "object",
                        "failure_mode",
                        "consequence",
                        "workaround",
                        "buyer_context",
                        "canonical_problem",
                        "severity",
                    )
                },
                "evidence_excerpt": discussion["problem_text"][:500],
            })

        prompt = f"""This is the FINAL precision gate for a recurring market problem.

Independent discussions:
{json.dumps(evidence, ensure_ascii=False)}

Return JSON:
{{
  "coherent": true,
  "confidence": 0.0,
  "title": "short neutral recurring problem title",
  "problem_statement": "one precise sentence",
  "who_has_problem": "specific affected user/group",
  "why_now": "supported timing statement, or No strong timing evidence yet.",
  "buyer_signals": [],
  "workarounds": [],
  "existing_solutions": [],
  "normalized_actor": "",
  "normalized_task": "",
  "normalized_failure_mode": "",
  "rejection_reason": ""
}}

coherent=true only if these independent discussions represent essentially the SAME
actionable failure. Reject:
- broad topic clusters,
- culture/opinion/policy debates,
- different failures involving the same product,
- same noun but different task,
- same task but materially different failure,
- one news event echoed across discussions.

Do not infer payment intent, market size, competition, or supply gap.
If timestamps are unknown, do not claim acceleration or recent growth.
"""

        result = await call_llm(
            prompt=prompt,
            system_message=(
                "You are the final precision gate for an opportunity radar. "
                "Reject questionable clusters. False positives are costly."
            ),
            model="mini",
            parse_json=True,
            usage_tracker=self.usage,
            max_tokens=1100,
        )

        if not isinstance(result, dict):
            return None

        try:
            result["confidence"] = max(
                0.0,
                min(1.0, float(result.get("confidence", 0) or 0)),
            )
        except Exception:
            result["confidence"] = 0.0

        # A weak "yes" is treated as a no.
        if (
            result.get("coherent") is True
            and result["confidence"] < 0.78
        ):
            result["coherent"] = False
            result["rejection_reason"] = (
                result.get("rejection_reason")
                or "Final verifier confidence below 0.78"
            )

        return result

    def score(self, component: list[dict], verdict: dict) -> dict:
        posts = []
        users = set()
        platforms = set()
        severities = []
        fp_confidences = []
        buyer_explicit = 0
        workaround_explicit = 0

        for discussion in component:
            posts.extend(discussion["posts"])
            users.update(discussion["user_ids"])
            platforms.add(discussion["platform"])

            fp = discussion["fingerprint"]
            severities.append(float(fp.get("severity", 1) or 1))
            fp_confidences.append(float(fp.get("confidence", 0) or 0))

            buyer_context = str(fp.get("buyer_context") or "").lower()
            if buyer_context not in {"", "unclear", "none", "none mentioned"}:
                buyer_explicit += 1

            workaround = str(fp.get("workaround") or "").lower()
            if workaround not in {"", "none", "none mentioned", "unclear"}:
                workaround_explicit += 1

        discussion_count = len(component)
        user_count = len(users)
        source_count = len(platforms)

        neg_sentiments = [
            abs(p["sentiment"])
            for p in posts
            if p["sentiment"] is not None and p["sentiment"] < 0
        ]
        avg_negative = (
            sum(neg_sentiments) / len(neg_sentiments)
            if neg_sentiments
            else 0.25
        )

        strong_pain_ratio = (
            sum(
                any(
                    term in p["problem_text"].lower()
                    for term in STRONG_PAIN_TERMS
                )
                for p in posts
            )
            / max(len(posts), 1)
        )

        avg_severity = (
            sum(severities) / len(severities)
            if severities else 1
        )

        pain = clamp(
            18
            + (avg_severity - 1) * 15
            + avg_negative * 18
            + strong_pain_ratio * 18
        )

        demand = clamp(
            15
            + 23 * math.log1p(discussion_count)
            + 13 * math.log1p(user_count)
        )

        buyer_ratio = buyer_explicit / max(discussion_count, 1)
        buyer = clamp(25 + 65 * buyer_ratio)

        workaround_ratio = workaround_explicit / max(discussion_count, 1)
        workaround_pressure = clamp(30 + 60 * workaround_ratio)

        cross_source = 35 if source_count == 1 else 82 if source_count == 2 else 95

        dated = [
            d for d in component
            if d["observed_at"] is not None
        ]
        undated = [
            d for d in component
            if d["observed_at"] is None
        ]

        if len(dated) < 2:
            growth = 50
            growth_quality = "unknown"
        else:
            now = datetime.utcnow()
            recent = sum(
                d["observed_at"] >= now - timedelta(days=7)
                for d in dated
            )
            older = len(dated) - recent
            recent_rate = recent / 7
            older_rate = older / 23 if older else 0

            if older_rate <= 0:
                growth = 62 if recent >= 2 else 50
            else:
                growth = clamp(
                    50
                    + 22 * math.log(
                        max(recent_rate / older_rate, 0.15),
                        2,
                    )
                )

            growth_quality = "partial" if undated else "dated"

        # External supply evidence is not attached in v2. Never convert
        # "we didn't check" into "supply gap is high".
        supply_gap = 50

        opportunity_signal = clamp(
            pain * 0.25
            + demand * 0.30
            + buyer * 0.15
            + growth * 0.10
            + workaround_pressure * 0.08
            + cross_source * 0.12
        )

        avg_fp_conf = (
            sum(fp_confidences) / len(fp_confidences)
            if fp_confidences else 0
        )
        final_verifier_conf = float(verdict.get("confidence", 0) or 0)

        discussion_conf = clamp(
            22 + 24 * math.log1p(discussion_count)
        )
        user_conf = clamp(
            18 + 19 * math.log1p(user_count)
        )
        source_conf = 42 if source_count == 1 else 84 if source_count == 2 else 96

        confidence = clamp(
            discussion_conf * 0.20
            + user_conf * 0.18
            + source_conf * 0.18
            + avg_fp_conf * 100 * 0.20
            + final_verifier_conf * 100 * 0.24
        )

        return {
            "opportunity_score": opportunity_signal,
            "confidence_score": confidence,
            "pain_score": pain,
            "demand_score": demand,
            "growth_score": growth,
            "buyer_score": buyer,
            "supply_gap_score": supply_gap,
            "cross_source_score": cross_source,
            "workaround_pressure": workaround_pressure,
            "discussion_count": discussion_count,
            "user_count": user_count,
            "source_count": source_count,
            "growth_data_quality": growth_quality,
            "avg_fingerprint_confidence": round(avg_fp_conf, 4),
            "final_verifier_confidence": round(final_verifier_conf, 4),
        }

    async def persist(self, component: list[dict], verdict: dict):
        scores = self.score(component, verdict)
        fingerprints = [d["fingerprint"] for d in component]
        key = canonical_key(
            verdict.get("title", "Untitled recurring problem"),
            fingerprints,
        )

        posts = []
        users = set()
        source_discussion_counts = Counter()

        for discussion in component:
            posts.extend(discussion["posts"])
            users.update(discussion["user_ids"])
            source_discussion_counts[discussion["platform"]] += 1

        times = [
            d["observed_at"]
            for d in component
            if d["observed_at"] is not None
        ]

        workarounds = []
        buyer_signals = []
        existing_solutions = list(verdict.get("existing_solutions") or [])

        for fp in fingerprints:
            workaround = str(fp.get("workaround") or "").strip()
            if workaround.lower() not in {
                "", "none", "none mentioned", "unclear"
            }:
                workarounds.append(workaround)

            buyer = str(fp.get("buyer_context") or "").strip()
            if buyer.lower() not in {
                "", "none", "none mentioned", "unclear"
            }:
                buyer_signals.append(buyer)

        workarounds.extend(verdict.get("workarounds") or [])
        buyer_signals.extend(verdict.get("buyer_signals") or [])

        values = {
            "canonical_key": key,
            "title": verdict.get(
                "title",
                "Untitled recurring problem",
            ),
            "problem_statement": verdict.get(
                "problem_statement",
                "",
            ),
            "who_has_problem": verdict.get(
                "who_has_problem",
                "unclear",
            ),
            "why_now": verdict.get(
                "why_now",
                "No strong timing evidence yet.",
            ),
            "opportunity_score": scores["opportunity_score"],
            "confidence_score": scores["confidence_score"],
            "pain_score": scores["pain_score"],
            "demand_score": scores["demand_score"],
            "growth_score": scores["growth_score"],
            "buyer_score": scores["buyer_score"],
            "supply_gap_score": scores["supply_gap_score"],
            "cross_source_score": scores["cross_source_score"],
            "independent_users": len(users),
            "evidence_count": len(posts),
            # Important: counts are independent discussions, not raw comments.
            "source_counts": dict(source_discussion_counts),
            "score_breakdown": {
                "engine_version": ENGINE_VERSION,
                "evidence_scope": "community_hn_reddit",
                "community_only": True,
                "discussion_count": scores["discussion_count"],
                "raw_evidence_count": len(posts),
                "unique_users": scores["user_count"],
                "workaround_pressure": scores["workaround_pressure"],
                "growth_data_quality": scores["growth_data_quality"],
                "avg_fingerprint_confidence": scores[
                    "avg_fingerprint_confidence"
                ],
                "final_verifier_confidence": scores[
                    "final_verifier_confidence"
                ],
                "supply_gap_status": "pending_external_enrichment",
                "normalized_actor": verdict.get("normalized_actor", ""),
                "normalized_task": verdict.get("normalized_task", ""),
                "normalized_failure_mode": verdict.get(
                    "normalized_failure_mode",
                    "",
                ),
                "weights": {
                    "pain": 0.25,
                    "repeat_demand": 0.30,
                    "buyer": 0.15,
                    "growth": 0.10,
                    "workaround_pressure": 0.08,
                    "cross_source": 0.12,
                },
            },
            "workarounds": list(dict.fromkeys(workarounds)),
            "existing_solutions": list(dict.fromkeys(existing_solutions)),
            "buyer_signals": list(dict.fromkeys(buyer_signals)),
            "cluster_cohesion": scores[
                "final_verifier_confidence"
            ],
            "first_seen_at": min(times) if times else None,
            "last_seen_at": max(times) if times else None,
            "calculated_at": datetime.utcnow(),
        }

        async with async_session() as session:
            stmt = pg_insert(Opportunity).values(**values)
            updates = {
                field: getattr(stmt.excluded, field)
                for field in values
                if field not in {"canonical_key", "status"}
            }

            opp_id = (
                await session.execute(
                    stmt.on_conflict_do_update(
                        index_elements=[Opportunity.canonical_key],
                        set_=updates,
                    ).returning(Opportunity.id)
                )
            ).scalar_one()

            await session.execute(
                delete(OpportunityEvidence).where(
                    OpportunityEvidence.opportunity_id == opp_id
                )
            )

            evidence_rows = []
            seen_sources = set()

            for post in sorted(
                posts,
                key=lambda p: (
                    p["score"] + min(p["num_comments"], 100),
                    p["posted_at"] or datetime.min,
                ),
                reverse=True,
            ):
                source_key = (
                    post["platform"],
                    post["source_ref"],
                )
                if source_key in seen_sources:
                    continue
                seen_sources.add(source_key)

                sentiment = post["sentiment"]
                strength = clamp(
                    45
                    + (
                        abs(sentiment) * 25
                        if sentiment is not None and sentiment < 0
                        else 0
                    )
                    + min(post["score"], 50) * 0.25
                ) / 100

                evidence_rows.append({
                    "opportunity_id": opp_id,
                    "post_id": post["id"],
                    "source_type": "community",
                    "platform": post["platform"],
                    "source_ref": post["source_ref"],
                    "evidence_type": "problem_evidence",
                    "title": (
                        post["title"][:500]
                        if post["title"]
                        else None
                    ),
                    "excerpt": post["problem_text"][:700],
                    "url": post["url"],
                    "strength": strength,
                    "observed_at": post["posted_at"],
                })

                if len(evidence_rows) >= 60:
                    break

            if evidence_rows:
                await session.execute(
                    pg_insert(OpportunityEvidence),
                    evidence_rows,
                )

            await session.commit()


def synthetic_self_check() -> bool:
    """No DB, no LLM. Ensures local retrieval behaves sanely."""
    engine = OpportunityEngine()

    def d(
        key: str,
        actor: str,
        task: str,
        obj: str,
        failure: str,
        canonical: str,
    ):
        return {
            "content_hash": key,
            "fingerprint": {
                "actor": actor,
                "task": task,
                "object": obj,
                "failure_mode": failure,
                "consequence": "",
                "canonical_problem": canonical,
                "confidence": 0.95,
                "actionable_problem": True,
                "opinion_or_news_only": False,
            },
        }

    discussions = [
        d(
            "a",
            "developer",
            "keep coding agent aligned with project instructions",
            "coding agent",
            "agent forgets or ignores persistent instructions",
            "coding agents fail to reliably follow persistent project instructions",
        ),
        d(
            "b",
            "software engineer",
            "make coding assistant follow repository rules",
            "AI coding assistant",
            "assistant does not consistently follow stored repository instructions",
            "coding agents fail to reliably follow persistent project instructions",
        ),
        d(
            "c",
            "Claude user",
            "change account email",
            "Claude account",
            "account email cannot be changed",
            "Claude account email cannot be changed",
        ),
        d(
            "d",
            "email user",
            "filter incoming email",
            "spam filter",
            "legitimate email is misclassified",
            "spam filter misclassifies legitimate email",
        ),
    ]

    pairs = engine.retrieve_candidate_pairs(discussions)
    pair_set = {
        tuple(sorted((p["i"], p["j"])))
        for p in pairs
    }

    expected_positive = (0, 1) in pair_set
    obvious_false_pair = (2, 3) in pair_set

    print("SELF-CHECK")
    print(" expected similar pair retrieved:", expected_positive)
    print(
        " email-account vs spam-filter pair retrieved:",
        obvious_false_pair,
        "(retrieval may be broad; verifier would still reject)",
    )

    return expected_positive


async def cli_main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Run v2 analysis but do not write Opportunity DB rows. "
             "LLM fingerprint/verifier calls may still occur.",
    )
    parser.add_argument(
        "--self-check",
        action="store_true",
        help="Local synthetic check only; no DB and no LLM.",
    )
    args = parser.parse_args()

    if args.self_check:
        ok = synthetic_self_check()
        raise SystemExit(0 if ok else 2)

    result = await OpportunityEngine().run(preview=args.preview)
    print("\nRESULT:", result)



async def refresh_problem_fingerprint_cache(
    *,
    ai_call_allowance: int = 2,
) -> dict[str, Any]:
    """Refresh only missing actionable-discussion fingerprints under a hard call cap.

    This is the bounded discovery primitive used by SignalForge. It does not run
    pair clustering, component verification, or legacy Opportunity persistence.
    Unprocessed discussions remain uncached rather than being written as negative
    evidence when the call budget is exhausted.
    """
    engine = OpportunityEngine(
        fingerprint_ai_call_allowance=max(0, int(ai_call_allowance)),
    )
    posts = await engine.find_candidates()
    discussions = engine.build_discussions(posts)
    await engine.extract_fingerprints(discussions)
    usable = [
        d for d in discussions
        if isinstance(d.get("fingerprint"), dict)
        and d["fingerprint"].get("actionable_problem") is True
        and float(d["fingerprint"].get("confidence", 0) or 0) >= 0.65
        and d["fingerprint"].get("opinion_or_news_only") is not True
    ]
    return {
        "engine_version": "v2.0-bounded-fingerprint-refresh",
        "candidate_rows": len(posts),
        "discussions": len(discussions),
        "usable_fingerprints": len(usable),
        "fingerprint_ai_calls": engine.fingerprint_ai_calls,
        "llm_tokens": int(engine.usage.total_tokens or 0),
        "llm_cost_usd": round(engine.usage.estimated_cost_usd, 6),
        "unprocessed_discussions": sum(
            1 for d in discussions if not isinstance(d.get("fingerprint"), dict)
        ),
    }

if __name__ == "__main__":
    asyncio.run(cli_main())
