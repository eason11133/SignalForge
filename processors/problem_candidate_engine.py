"""Cross-Source Problem Candidate Engine v2.

Precision is preserved by an LLM verifier, while recall is improved through
source-specific retrieval profiles and hybrid word/character matching.

Incremental caches:
- .radar_cache/candidate_retrieval_profiles_v2.json
- .radar_cache/candidate_evidence_verdicts_v2.json
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import structlog
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from database.connection import async_session, ProblemCandidate, CandidateEvidence
from processors.llm_client import TokenUsage, call_llm
from processors.opportunity_engine import OpportunityEngine, refresh_problem_fingerprint_cache
from processors.solo_transition_opportunity import fingerprint_is_founder_unit
from processors.signalforge_production_admission import assess_pre_enrichment_discovery
from processors.signalforge_discovery_portfolio import select_enrichment_portfolio

log = structlog.get_logger().bind(processor="problem_candidate_engine_v2")

ENGINE_VERSION = "candidate-cross-source-v3-solo-atom"
DISCOVERY_RUNTIME_VERSION = "candidate-discovery-v5-incremental-solo-transition"
CACHE_DIR = Path(".radar_cache")
PROFILE_CACHE_FILE = CACHE_DIR / "candidate_retrieval_profiles_v2.json"
EVIDENCE_CACHE_FILE = CACHE_DIR / "candidate_evidence_verdicts_v2.json"
ZH_CACHE_FILE = CACHE_DIR / "candidate_chinese_quickread_v1.json"

PROFILE_BATCH = 8
VERIFY_BATCH = 2
TOP_PER_SOURCE = 4
MAX_LEADS_PER_CANDIDATE = 12

SOURCE_PATTERNS = {
    "stackoverflow": ("stackoverflow", "stack_overflow", "so_question"),
    "github": ("github",),
    "jobs": ("job",),
    "packages": ("package", "pypi", "npm"),
    "yc": ("yc_", "ycombinator", "y_combinator"),
    "news": ("news_event", "news"),
    "huggingface": ("huggingface", "hf_model"),
}

TEXT_HINTS = (
    "title", "name", "full_name", "repo_name", "package_name", "model_name",
    "description", "body", "summary", "abstract", "content", "text",
    "tags", "topics", "skills", "technology", "tech_stack", "role",
    "position", "company", "industry", "category", "language", "readme",
    "question", "answer", "event_type", "source", "source_name",
)
TITLE_HINTS = (
    "title", "full_name", "repo_name", "package_name", "model_name",
    "name", "role", "position", "company",
)
URL_HINTS = ("url", "html_url", "link", "apply_url", "repo_url")
DATE_HINTS = (
    "posted_at", "published_at", "created_at", "updated_at",
    "date", "scraped_at", "fetched_at",
)
NOISE_TABLE_TERMS = (
    "candidate", "opportunit", "pain_point", "topic", "persona",
    "agent_run", "scraper_run", "signal",
)

MEANINGFUL_RELATIONS = {
    "direct_problem_corroboration",
    "buyer_demand",
    "solution_supply",
    "competitor",
    "ecosystem_activity",
    "why_now",
    "research_enabler",
}

GENERIC_TOKENS = {
    "ai", "llm", "model", "models", "software", "tool", "tools",
    "system", "systems", "user", "users", "problem", "issue", "issues",
    "work", "working", "use", "using", "need", "needs", "new",
}


def clean(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, (list, tuple, set)):
        v = " ".join(map(str, v))
    elif isinstance(v, dict):
        v = " ".join(f"{k} {x}" for k, x in v.items())
    s = re.sub(r"<[^>]+>", " ", str(v))
    s = re.sub(r"https?://\S+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def sf(v, default=0.0):
    try:
        return float(v)
    except Exception:
        return default


def load_json(path: Path) -> dict:
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {}


def save_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    tmp.replace(path)


def tokens(text_value: str) -> set[str]:
    return {
        t for t in re.findall(r"[a-z0-9][a-z0-9_+\-\.]{1,}", text_value.lower())
        if len(t) >= 3 and t not in GENERIC_TOKENS
    }


def same_problem_posts(discussion: dict) -> list[dict]:
    """Conservatively select posts that support the extracted problem atom.

    A discussion/thread may contain several unrelated sub-problems. Candidate-level
    recurrence/counts must not treat every participant in the thread as supporting the
    dominant extracted fingerprint. Zero matching posts is valid.
    """
    fp = discussion.get("fingerprint") or {}
    anchor_text = " ".join(clean(fp.get(k)) for k in (
        "canonical_problem", "failure_mode", "task", "object", "consequence"
    ) if clean(fp.get(k)))
    anchor = tokens(anchor_text)
    if not anchor:
        return []
    # Preserve thesis-specific anchors; generic technology nouns were already removed
    # by tokens(). Require either two shared terms, or one highly-specific term plus
    # meaningful phrase overlap.
    specific = {t for t in anchor if len(t) >= 6}
    out = []
    for post in discussion.get("posts") or []:
        text = clean((post.get("title") or "") + " " + (post.get("problem_text") or ""))
        pt = tokens(text)
        shared = anchor & pt
        phrase_hit = any(
            clean(fp.get(k)).lower() in text.lower()
            for k in ("failure_mode", "object")
            if len(clean(fp.get(k))) >= 10
        )
        if len(shared) >= 2 or bool(shared & specific and phrase_hit):
            out.append(post)
    return out


def hash_obj(obj: Any) -> str:
    raw = json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def title_for(fp: dict) -> str:
    s = clean(fp.get("canonical_problem") or fp.get("failure_mode"))
    return s[:1].upper() + s[1:] if s else "Unspecified problem candidate"


class DiscoveryBudgetExhausted(RuntimeError):
    pass


class ProblemCandidateEngine:
    def __init__(
        self,
        *,
        fingerprint_ai_call_allowance: int = 2,
        profile_ai_call_allowance: int = 0,
        verify_ai_call_allowance: int = 2,
        translate: bool = False,
        incremental_only: bool = False,
        max_incremental_candidates: int = 16,
    ):
        self.usage = TokenUsage()
        self.schema: dict[str, list[dict]] = {}
        self.docs: dict[str, list[dict]] = {}
        self.profile_cache = load_json(PROFILE_CACHE_FILE)
        self.evidence_cache = load_json(EVIDENCE_CACHE_FILE)
        self.zh_cache = load_json(ZH_CACHE_FILE)
        self.fingerprint_ai_call_allowance = max(0, int(fingerprint_ai_call_allowance))
        self.profile_ai_call_allowance = max(0, int(profile_ai_call_allowance))
        self.verify_ai_call_allowance = max(0, int(verify_ai_call_allowance))
        self.translate = bool(translate)
        self.incremental_only = bool(incremental_only)
        self.max_incremental_candidates = max(1, int(max_incremental_candidates))
        self.profile_ai_calls = 0
        self.verify_ai_calls = 0
        self.fingerprint_refresh: dict[str, Any] = {}

    @staticmethod
    def _deterministic_profile(fp: dict[str, Any]) -> dict[str, list[str]]:
        def vals(*keys: str) -> list[str]:
            out = []
            for key in keys:
                value = clean(fp.get(key))
                if value and value.lower() not in {"unclear", "none", "none mentioned"}:
                    out.append(value[:160])
            return out[:8]
        return {
            "core_terms": vals("canonical_problem", "failure_mode", "object"),
            "task_terms": vals("task"),
            "object_terms": vals("object"),
            "solution_terms": vals("object", "task", "failure_mode"),
            "buyer_capability_terms": vals("buyer_context", "actor", "task"),
            "research_terms": vals("canonical_problem", "failure_mode", "consequence"),
        }

    async def run(self):
        print("\n" + "=" * 100)
        print("AI OPPORTUNITY RADAR — CROSS-SOURCE ENRICHMENT V2")
        print("=" * 100)

        self.fingerprint_refresh = await refresh_problem_fingerprint_cache(
            ai_call_allowance=self.fingerprint_ai_call_allowance,
        )
        discussions = await self.load_candidates()
        total_structured = len(discussions)
        if self.incremental_only:
            discussions = await self._incremental_candidates(discussions)

        pre_enrichment_deferred = []
        admitted_discussions = []
        for discussion in discussions:
            decision = assess_pre_enrichment_discovery(discussion)
            discussion["_pre_enrichment_admission"] = decision
            if decision.get("admit_external_enrichment"):
                admitted_discussions.append(discussion)
            else:
                pre_enrichment_deferred.append(decision)
        enrichment_pool = admitted_discussions
        discussions, discovery_portfolio = select_enrichment_portfolio(
            enrichment_pool,
            limit=self.max_incremental_candidates if self.incremental_only else len(enrichment_pool),
        )

        print(
            f"Structured community problem candidates: {total_structured} "
            f"| enrichment_pool={len(enrichment_pool)} "
            f"| enrichment_batch={len(discussions)} "
            f"| pre_enrichment_deferred={len(pre_enrichment_deferred)}"
        )
        print(
            "Discovery portfolio: "
            f"selected={discovery_portfolio.get('selected', 0)} "
            f"roles={discovery_portfolio.get('role_counts_selected', {})}"
        )
        print(
            "Fingerprint refresh: "
            f"calls={self.fingerprint_refresh.get('fingerprint_ai_calls', 0)} "
            f"unprocessed={self.fingerprint_refresh.get('unprocessed_discussions', 0)}"
        )

        if not discussions:
            fx = sf(os.getenv("USD_TWD_RATE"), 31.83)
            save_json(PROFILE_CACHE_FILE, self.profile_cache)
            save_json(EVIDENCE_CACHE_FILE, self.evidence_cache)
            return {
                "engine_version": ENGINE_VERSION,
                "runtime_version": DISCOVERY_RUNTIME_VERSION,
                "problem_candidates": total_structured,
                "enrichment_batch": 0,
                "pre_enrichment_deferred": len(pre_enrichment_deferred),
                "pre_enrichment_deferred_reasons": dict(Counter(
                    reason
                    for row in pre_enrichment_deferred
                    for reason in (row.get("ephemeral_flags") or ["OTHER"])
                )),
                "discovery_portfolio": discovery_portfolio,
                "retrieval_leads": 0,
                "verified_external_evidence": 0,
                "stages": {},
                "fingerprint_refresh": self.fingerprint_refresh,
                "profile_ai_calls": 0,
                "verify_ai_calls": 0,
                "llm_calls": int(self.fingerprint_refresh.get("fingerprint_ai_calls", 0) or 0),
                "llm_tokens": int(self.fingerprint_refresh.get("llm_tokens", 0) or 0),
                "llm_cost_usd": round(float(self.fingerprint_refresh.get("llm_cost_usd", 0) or 0), 6),
                "llm_cost_twd": round(float(self.fingerprint_refresh.get("llm_cost_usd", 0) or 0) * fx, 2),
            }

        await self.build_profiles(discussions)
        profile_hits = sum(d.get("_profile_cache_hit", False) for d in discussions)
        print(
            f"Retrieval profiles: {profile_hits} cache hits / "
            f"{len(discussions) - profile_hits} generated"
        )

        await self.reflect_schema()
        await self.load_sources()
        for src, docs in sorted(self.docs.items()):
            print(f"External source {src:16s}: {len(docs):5d} searchable records")

        leads = self.retrieve(discussions)
        lead_total = sum(len(v) for v in leads.values())
        print(f"Hybrid source-specific retrieval leads: {lead_total}")

        verified = await self.verify(discussions, leads)
        verified_total = sum(len(v) for v in verified.values())
        cache_verdicts = sum(
            1 for items in leads.values() for item in items
            if item.get("_verdict_cache_hit")
        )
        print(f"Evidence verdict cache hits: {cache_verdicts}")
        print(f"Verified relevant external evidence: {verified_total}")

        if self.translate:
            await self.ensure_chinese_display(discussions)
        else:
            await self.attach_cached_chinese_display(discussions)
        processed_candidate_ids = await self.persist(discussions, verified)
        stages = Counter(d["stage"] for d in discussions)

        print("\n" + "-" * 100)
        print("RADAR RESULT")
        print("-" * 100)
        for st in ("candidate", "market_supported", "corroborated", "opportunity"):
            print(f"{st:14s}: {stages.get(st, 0)}")

        ranked = sorted(
            discussions,
            key=lambda d: (
                d["stage"] == "opportunity",
                d["stage"] == "corroborated",
                d["stage"] == "market_supported",
                d["market_score"],
                d["confidence_score"],
            ),
            reverse=True,
        )
        print("\nTOP RADAR ITEMS")
        for d in ranked[:10]:
            src = ", ".join(
                f"{k}:{v}" for k, v in d["source_counts"].items()
            ) or "community only"
            print(
                f"  [{d['stage']:<12}] "
                f"{d['market_score']:5.1f} / conf {d['confidence_score']:5.1f} "
                f"| {d['title'][:72]} | {src}"
            )

        fx = sf(os.getenv("USD_TWD_RATE"), 31.83)
        twd = self.usage.estimated_cost_usd * fx
        print(f"\nTracked LLM cost this run: NT${twd:.2f}")

        save_json(PROFILE_CACHE_FILE, self.profile_cache)
        save_json(EVIDENCE_CACHE_FILE, self.evidence_cache)

        return {
            "engine_version": ENGINE_VERSION,
            "runtime_version": DISCOVERY_RUNTIME_VERSION,
            "problem_candidates": total_structured,
            "enrichment_batch": len(discussions),
            "pre_enrichment_deferred": len(pre_enrichment_deferred),
            "pre_enrichment_deferred_reasons": dict(Counter(
                reason
                for row in pre_enrichment_deferred
                for reason in (row.get("ephemeral_flags") or ["OTHER"])
            )),
            "discovery_portfolio": discovery_portfolio,
            "retrieval_leads": lead_total,
            "verified_external_evidence": verified_total,
            "processed_candidate_ids": processed_candidate_ids,
            "stages": dict(stages),
            "fingerprint_refresh": self.fingerprint_refresh,
            "profile_ai_calls": self.profile_ai_calls,
            "verify_ai_calls": self.verify_ai_calls,
            "llm_calls": (
                int(self.fingerprint_refresh.get("fingerprint_ai_calls", 0) or 0)
                + self.profile_ai_calls
                + self.verify_ai_calls
            ),
            "llm_tokens": (
                int(self.fingerprint_refresh.get("llm_tokens", 0) or 0)
                + int(self.usage.total_tokens or 0)
            ),
            "llm_cost_usd": round(
                float(self.fingerprint_refresh.get("llm_cost_usd", 0) or 0)
                + self.usage.estimated_cost_usd,
                6,
            ),
            "llm_cost_twd": round(
                (float(self.fingerprint_refresh.get("llm_cost_usd", 0) or 0)
                + self.usage.estimated_cost_usd) * fx,
                2,
            ),
        }

    async def load_candidates(self):
        engine = OpportunityEngine()
        posts = await engine.find_candidates()
        discussions = engine.build_discussions(posts)

        out = []
        for d in discussions:
            cached = engine.fp_cache.get(d["content_hash"])
            fp = cached.get("fingerprint") if isinstance(cached, dict) else None
            if not isinstance(fp, dict):
                continue
            if not fingerprint_is_founder_unit(fp):
                # Broad themes / phenomena stay in research context. They do not
                # become Founder opportunity candidates just because they are painful.
                continue

            d["fingerprint"] = fp
            d["canonical_key"] = hashlib.sha1(
                (
                    d["discussion_key"]
                    + "|"
                    + clean(fp.get("canonical_problem"))
                    + "|"
                    + clean(fp.get("failure_mode"))
                ).encode()
            ).hexdigest()[:24]
            d["title"] = title_for(fp)
            out.append(d)

        return out

    async def _incremental_candidates(self, discussions):
        if not discussions:
            return []
        keys = [d.get("canonical_key") for d in discussions if d.get("canonical_key")]
        async with async_session() as session:
            existing = list((await session.execute(
                select(ProblemCandidate).where(ProblemCandidate.canonical_key.in_(keys))
            )).scalars().all())
        by_key = {str(row.canonical_key): row for row in existing}

        pending = []
        for d in discussions:
            key = str(d.get("canonical_key") or "")
            row = by_key.get(key)
            dates = [p.get("posted_at") for p in (d.get("posts") or []) if p.get("posted_at") is not None]
            latest = max(dates) if dates else None
            changed = row is None
            if row is not None:
                stored = getattr(row, "last_seen_at", None)
                if latest is not None and (stored is None or latest > stored):
                    changed = True
            if changed:
                d["_incremental_new"] = row is None
                d["_incremental_latest"] = latest
                pending.append(d)

        pending.sort(
            key=lambda d: (
                1 if d.get("_incremental_new") else 0,
                d.get("_incremental_latest") or datetime.min,
            ),
            reverse=True,
        )
        # Return a bounded changed-candidate pool. R5 discovery-portfolio
        # scheduling chooses the actual enrichment batch after the deterministic
        # pre-enrichment gate, so recent troubleshooting cannot consume all 16
        # slots before buyer/workaround/transition signals are considered.
        pool_limit = max(self.max_incremental_candidates, min(64, self.max_incremental_candidates * 4))
        return pending[:pool_limit]

    async def build_profiles(self, discussions):
        missing = []

        for d in discussions:
            fp = d["fingerprint"]
            fp_hash = hash_obj(fp)
            cache_key = f"{ENGINE_VERSION}:{fp_hash}"
            cached = self.profile_cache.get(cache_key)

            if isinstance(cached, dict):
                d["retrieval_profile"] = cached
                d["_profile_cache_hit"] = True
            else:
                d["_profile_cache_hit"] = False
                d["_profile_cache_key"] = cache_key
                missing.append(d)

        if self.profile_ai_call_allowance <= 0:
            for d in missing:
                d["retrieval_profile"] = self._deterministic_profile(d["fingerprint"])
            return

        for start in range(0, len(missing), PROFILE_BATCH):
            if self.profile_ai_calls >= self.profile_ai_call_allowance:
                for d in missing[start:]:
                    d["retrieval_profile"] = self._deterministic_profile(d["fingerprint"])
                break
            batch = missing[start:start + PROFILE_BATCH]
            payload = []
            idmap = {}

            for i, d in enumerate(batch):
                cid = f"C{i+1}"
                idmap[cid] = d
                fp = d["fingerprint"]
                payload.append({
                    "id": cid,
                    "problem": {
                        "actor": fp.get("actor"),
                        "actor_category": fp.get("actor_category"),
                        "task": fp.get("task"),
                        "object": fp.get("object"),
                        "failure_mode": fp.get("failure_mode"),
                        "consequence": fp.get("consequence"),
                        "buyer_context": fp.get("buyer_context"),
                        "canonical_problem": fp.get("canonical_problem"),
                    },
                })

            prompt = f"""Create compact SEARCH RETRIEVAL PROFILES for these validated user problems.

INPUT:
{json.dumps(payload, ensure_ascii=False)}

Return JSON:
{{
  "candidates": [
    {{
      "id": "C1",
      "core_terms": ["3-8 concrete nouns/phrases"],
      "task_terms": ["phrases describing the job-to-be-done"],
      "object_terms": ["products, systems, technologies, functions"],
      "solution_terms": ["phrases a GitHub repo/package/startup solving this may use"],
      "buyer_capability_terms": ["skills/capabilities a job posting addressing this area may use"],
      "research_terms": ["phrases research/news about the enabling problem may use"]
    }}
  ]
}}

Rules:
- Search expansion only; do not invent evidence.
- Prefer concrete technical/business phrases, not generic AI/model/software.
- Include common synonyms when wording differs across communities, repos, jobs and research.
- Do not invent brand names not supported by the problem.
- Keep each list <= 8 items.
"""

            self.profile_ai_calls += 1
            result = await call_llm(
                prompt=prompt,
                system_message=(
                    "You create precise information-retrieval query expansions. "
                    "Optimize recall without changing the underlying problem."
                ),
                model="mini",
                parse_json=True,
                usage_tracker=self.usage,
                max_tokens=2400,
            )

            returned = {}
            if isinstance(result, dict):
                returned = {
                    str(x.get("id")): x
                    for x in result.get("candidates", [])
                    if isinstance(x, dict)
                }

            for cid, d in idmap.items():
                profile = returned.get(cid) or {
                    "core_terms": [],
                    "task_terms": [],
                    "object_terms": [],
                    "solution_terms": [],
                    "buyer_capability_terms": [],
                    "research_terms": [],
                }

                for field in (
                    "core_terms", "task_terms", "object_terms",
                    "solution_terms", "buyer_capability_terms", "research_terms",
                ):
                    vals = profile.get(field)
                    if not isinstance(vals, list):
                        vals = []
                    profile[field] = [
                        clean(v) for v in vals if clean(v)
                    ][:8]

                d["retrieval_profile"] = profile
                self.profile_cache[d["_profile_cache_key"]] = profile

            save_json(PROFILE_CACHE_FILE, self.profile_cache)

    async def reflect_schema(self):
        async with async_session() as session:
            rows = (
                await session.execute(
                    text("""
                        SELECT table_name,column_name,data_type
                        FROM information_schema.columns
                        WHERE table_schema='public'
                        ORDER BY table_name,ordinal_position
                    """)
                )
            ).all()

        schema = defaultdict(list)
        for table_name, column_name, data_type in rows:
            schema[str(table_name)].append({
                "name": str(column_name),
                "type": str(data_type),
            })
        self.schema = dict(schema)

    def source_for_table(self, table):
        lower = table.lower()
        if any(n in lower for n in NOISE_TABLE_TERMS):
            return None
        for source, patterns in SOURCE_PATTERNS.items():
            if any(p in lower for p in patterns):
                return source
        return None

    def table_spec(self, table):
        names = [x["name"] for x in self.schema.get(table, [])]
        lower_map = {n.lower(): n for n in names}

        pk = next(
            (
                lower_map[x]
                for x in (
                    "id", "repo_id", "question_id", "job_id",
                    "company_id", "model_id",
                )
                if x in lower_map
            ),
            names[0] if names else None,
        )

        text_cols = [
            n for n in names
            if any(h in n.lower() for h in TEXT_HINTS)
        ][:14]

        title_cols = [
            n for n in names
            if any(h == n.lower() for h in TITLE_HINTS)
        ][:4]

        url = next(
            (
                n for n in names
                if any(h == n.lower() or h in n.lower() for h in URL_HINTS)
            ),
            None,
        )
        date = next(
            (n for n in names if n.lower() in DATE_HINTS),
            None,
        )
        event_type = lower_map.get("event_type")

        return {
            "pk": pk,
            "text_cols": text_cols,
            "title_cols": title_cols,
            "url": url,
            "date": date,
            "event_type": event_type,
        }

    async def load_table(self, table, source, limit):
        spec = self.table_spec(table)
        if not spec["pk"] or not spec["text_cols"]:
            return []

        selected = [spec["pk"], *spec["text_cols"]]
        for extra in (spec["url"], spec["date"], spec["event_type"]):
            if extra and extra not in selected:
                selected.append(extra)

        cols = ", ".join(f'"{x}"' for x in selected)

        try:
            async with async_session() as session:
                rows = (
                    await session.execute(
                        text(
                            f'SELECT {cols} FROM "{table}" '
                            f'LIMIT {int(limit)}'
                        )
                    )
                ).mappings().all()
        except Exception as exc:
            log.warning(
                "source_table_read_failed",
                table=table,
                error=str(exc),
            )
            return []

        docs = []
        package_seen = set()

        for row in rows:
            row_source = source
            event_type = clean(
                row.get(spec["event_type"])
                if spec["event_type"]
                else ""
            ).lower()

            if source == "news":
                if event_type == "arxiv":
                    row_source = "arxiv"
                elif "stackoverflow" in event_type:
                    row_source = "stackoverflow_trend"

            title = ""
            for col in spec["title_cols"]:
                value = clean(row.get(col))
                if value:
                    title = value
                    break

            pieces = []
            for col in spec["text_cols"]:
                value = clean(row.get(col))
                if value:
                    # Weight title/name/role fields by repetition.
                    multiplier = 2 if col in spec["title_cols"] else 1
                    pieces.extend([f"{col}: {value}"] * multiplier)

            document = " | ".join(pieces)
            if len(document) < 8:
                continue

            # Package table is intentionally time-series. Search one entity doc
            # per package rather than treating every daily measurement as a new solution.
            if row_source == "packages":
                pkg_key = title.lower() if title else document.lower()
                if pkg_key in package_seen:
                    continue
                package_seen.add(pkg_key)

            docs.append({
                "source": row_source,
                "table": table,
                "pk": str(row.get(spec["pk"])),
                "text": document[:2200],
                "title": title[:500],
                "url": clean(row.get(spec["url"])) if spec["url"] else "",
                "date": (
                    str(row.get(spec["date"]) or "")
                    if spec["date"]
                    else ""
                ),
            })

        return docs

    async def load_sources(self):
        counts = {}
        async with async_session() as session:
            for table in self.schema:
                source = self.source_for_table(table)
                if not source:
                    continue
                try:
                    counts[table] = int(
                        (
                            await session.execute(
                                text(f'SELECT COUNT(*) FROM "{table}"')
                            )
                        ).scalar()
                        or 0
                    )
                except Exception:
                    counts[table] = 0

        grouped = defaultdict(list)
        for table, count in counts.items():
            if count <= 0:
                continue
            source = self.source_for_table(table)
            docs = await self.load_table(
                table,
                source,
                min(count, 5000),
            )
            for doc in docs:
                grouped[doc["source"]].append(doc)

        self.docs = dict(grouped)

    def source_query(self, d, source):
        fp = d["fingerprint"]
        p = d["retrieval_profile"]

        base = {
            "canonical": clean(fp.get("canonical_problem")),
            "failure": clean(fp.get("failure_mode")),
            "task": clean(fp.get("task")),
            "object": clean(fp.get("object")),
            "actor": clean(fp.get("actor")),
            "consequence": clean(fp.get("consequence")),
            "buyer": clean(fp.get("buyer_context")),
        }

        core = " ".join(p.get("core_terms", []))
        task_terms = " ".join(p.get("task_terms", []))
        object_terms = " ".join(p.get("object_terms", []))
        solution_terms = " ".join(p.get("solution_terms", []))
        buyer_terms = " ".join(p.get("buyer_capability_terms", []))
        research_terms = " ".join(p.get("research_terms", []))

        if source in {"stackoverflow", "stackoverflow_trend"}:
            parts = [
                base["canonical"], base["failure"], base["failure"],
                base["task"], base["task"], base["object"],
                core, task_terms, object_terms,
            ]
        elif source in {"github", "packages", "huggingface"}:
            parts = [
                base["canonical"], base["task"], base["task"],
                base["object"], base["object"], base["failure"],
                core, object_terms, solution_terms,
            ]
        elif source == "jobs":
            parts = [
                base["task"], base["task"], base["object"], base["object"],
                base["actor"], base["buyer"], core, task_terms,
                buyer_terms, object_terms,
            ]
        elif source == "yc":
            parts = [
                base["canonical"], base["task"], base["task"],
                base["object"], base["actor"], core,
                solution_terms, buyer_terms,
            ]
        elif source in {"news", "arxiv"}:
            parts = [
                base["canonical"], base["failure"], base["object"],
                base["object"], base["consequence"], base["task"],
                core, object_terms, research_terms,
            ]
        else:
            parts = [
                base["canonical"], base["failure"], base["task"],
                base["object"], core,
            ]

        return " ".join(x for x in parts if x)

    @staticmethod
    def token_overlap(query, doc):
        a, b = tokens(query), tokens(doc)
        if not a or not b:
            return 0.0
        return len(a & b) / max(1, min(len(a), len(b)))

    def retrieve(self, discussions):
        output = {d["canonical_key"]: [] for d in discussions}

        thresholds = {
            "stackoverflow": 0.055,
            "stackoverflow_trend": 0.055,
            "github": 0.045,
            "jobs": 0.045,
            "packages": 0.055,
            "yc": 0.045,
            "news": 0.050,
            "arxiv": 0.050,
            "huggingface": 0.050,
        }

        for source, docs in self.docs.items():
            if not docs:
                continue

            queries = [
                self.source_query(d, source)
                for d in discussions
            ]
            doc_texts = [doc["text"] for doc in docs]
            corpus = queries + doc_texts

            try:
                word_vec = TfidfVectorizer(
                    stop_words="english",
                    ngram_range=(1, 2),
                    sublinear_tf=True,
                    max_features=30000,
                )
                word_x = word_vec.fit_transform(corpus)
                word_sim = cosine_similarity(
                    word_x[:len(queries)],
                    word_x[len(queries):],
                )

                char_vec = TfidfVectorizer(
                    analyzer="char_wb",
                    ngram_range=(3, 5),
                    sublinear_tf=True,
                    max_features=35000,
                )
                char_x = char_vec.fit_transform(corpus)
                char_sim = cosine_similarity(
                    char_x[:len(queries)],
                    char_x[len(queries):],
                )
            except Exception:
                continue

            for i, d in enumerate(discussions):
                combined = (
                    word_sim[i] * 0.58
                    + char_sim[i] * 0.30
                )

                # Take a broad preliminary pool, then add lexical overlap.
                pool = np.argsort(combined)[::-1][:12]
                scored = []

                for j in pool:
                    j = int(j)
                    overlap = self.token_overlap(
                        queries[i],
                        docs[j]["text"],
                    )
                    score = float(combined[j] + overlap * 0.12)
                    scored.append((score, j, overlap))

                scored.sort(reverse=True)

                for score, j, overlap in scored[:TOP_PER_SOURCE]:
                    if score < thresholds.get(source, 0.05):
                        continue

                    output[d["canonical_key"]].append({
                        **docs[j],
                        "retrieval_score": round(score, 4),
                        "token_overlap": round(overlap, 4),
                    })

        # Cap total evidence leads per candidate so verifier spend is bounded.
        for key, items in output.items():
            items.sort(
                key=lambda x: x["retrieval_score"],
                reverse=True,
            )
            output[key] = items[:MAX_LEADS_PER_CANDIDATE]

        return output

    def verdict_cache_key(self, candidate, lead):
        raw = "|".join([
            ENGINE_VERSION,
            candidate["canonical_key"],
            lead["source"],
            lead["table"],
            lead["pk"],
            hash_obj(candidate["retrieval_profile"]),
        ])
        return hashlib.sha1(raw.encode()).hexdigest()

    async def _verify_payload(self, payload, local_map, max_tokens=1900):
        prompt = f"""Classify external market evidence for each validated community problem.

INPUT:
{json.dumps(payload, ensure_ascii=False)}

Return ONLY valid JSON:
{{
  "candidates": [
    {{
      "id": "C1",
      "evidence": [
        {{
          "id": "E1",
          "relevant": true,
          "confidence": 0.0,
          "relation": "direct_problem_corroboration|buyer_demand|solution_supply|competitor|ecosystem_activity|why_now|research_enabler|adjacent_only|irrelevant",
          "reason": "max 20 words"
        }}
      ]
    }}
  ]
}}

Rules:
- Stack Overflow => direct_problem_corroboration only for the same/equivalent task and failure.
- Jobs => buyer_demand only when the named organization is spending on responsibilities that own the SAME actor/workflow/failure. Adjacent AI/software hiring is insufficient.
- GitHub => solution_supply only when the repo materially solves/enables the same task/problem.
- Package/HuggingFace => ecosystem_activity only when materially connected to the solution/task.
- YC => competitor only when the startup addresses the same customer job/problem space.
- News => why_now only when it supports urgency/adoption/regulation/market timing.
- ArXiv => research_enabler only when research materially advances/exposes the relevant problem/solution.
- Generic AI/LLM overlap is never enough.
- A source entity/repository name is not a market solution merely because it appears in evidence.
- Buyer evidence must match the concrete workflow and failure; senior/adjacent roles do not prove a junior/user problem.
- Keep every reason <= 20 words.
- Output JSON only. No markdown fences. No commentary.
"""
        if self.verify_ai_calls >= self.verify_ai_call_allowance:
            raise DiscoveryBudgetExhausted("cross-source verifier AI budget exhausted")
        self.verify_ai_calls += 1
        result = await call_llm(
            prompt=prompt,
            system_message=(
                "You are a conservative cross-source market evidence analyst. "
                "Return compact valid JSON only. Topical overlap alone is not evidence."
            ),
            model="mini",
            parse_json=True,
            usage_tracker=self.usage,
            max_tokens=max_tokens,
        )
        if not isinstance(result, dict):
            raise ValueError("Verifier returned non-object JSON")

        returned = {
            str(x.get("id")): x
            for x in result.get("candidates", [])
            if isinstance(x, dict)
        }
        out = {}
        for cid, candidate_key in local_map.items():
            item = returned.get(cid, {})
            out[candidate_key] = {
                str(v.get("id")): v
                for v in item.get("evidence", [])
                if isinstance(v, dict)
            }
        return out

    def _make_verify_payload(self, items):
        payload = []
        local_map = {}
        for i, (d, lead_chunk) in enumerate(items):
            cid = f"C{i+1}"
            local_map[cid] = d["canonical_key"]
            fp = d["fingerprint"]
            evidence = [
                {
                    "id": f"E{n+1}",
                    "source": lead["source"],
                    "title": lead["title"],
                    "text": lead["text"][:500],
                }
                for n, lead in enumerate(lead_chunk)
            ]
            payload.append({
                "id": cid,
                "problem": {
                    "actor": fp.get("actor"),
                    "task": fp.get("task"),
                    "object": fp.get("object"),
                    "failure_mode": fp.get("failure_mode"),
                    "consequence": fp.get("consequence"),
                    "buyer_context": fp.get("buyer_context"),
                    "canonical_problem": fp.get("canonical_problem"),
                },
                "evidence": evidence,
            })
        return payload, local_map

    async def _verify_one_candidate_resilient(self, d, lead_chunk):
        payload, local_map = self._make_verify_payload([(d, lead_chunk)])
        try:
            verdicts = await self._verify_payload(payload, local_map, max_tokens=1600)
            return verdicts.get(d["canonical_key"], {})
        except Exception as exc:
            log.warning(
                "verifier_single_candidate_json_failed_splitting",
                candidate=d["canonical_key"],
                evidence=len(lead_chunk),
                error=str(exc),
            )

        # Last-resort: split into <=6 evidence calls.
        merged = {}
        for start in range(0, len(lead_chunk), 6):
            piece = lead_chunk[start:start + 6]
            payload, local_map = self._make_verify_payload([(d, piece)])
            try:
                verdicts = await self._verify_payload(payload, local_map, max_tokens=1100)
                local = verdicts.get(d["canonical_key"], {})
                # Remap E1..En from this sub-piece back to global E ids.
                for local_idx in range(len(piece)):
                    v = local.get(f"E{local_idx+1}")
                    if v:
                        merged[f"E{start+local_idx+1}"] = v
            except Exception as exc:
                log.warning(
                    "verifier_small_piece_skipped",
                    candidate=d["canonical_key"],
                    piece_start=start,
                    evidence=len(piece),
                    error=str(exc),
                )
        return merged

    async def verify(self, discussions, leads):
        verified = {d["canonical_key"]: [] for d in discussions}
        uncached_candidates = []

        for d in discussions:
            pending = []
            for lead in leads.get(d["canonical_key"], []):
                key = self.verdict_cache_key(d, lead)
                cached = self.evidence_cache.get(key)

                if isinstance(cached, dict):
                    if (
                        cached.get("relevant") is True
                        and cached.get("relation") in MEANINGFUL_RELATIONS
                        and sf(cached.get("confidence")) >= 0.70
                    ):
                        verified[d["canonical_key"]].append({
                            **lead,
                            "verified": True,
                            "verification_confidence": sf(cached.get("confidence")),
                            "relation": cached.get("relation"),
                            "reason": clean(cached.get("reason"))[:500],
                        })
                else:
                    pending.append({
                        **lead,
                        "_evidence_cache_key": key,
                    })

            if pending:
                uncached_candidates.append((d, pending))

        total = len(uncached_candidates)
        completed = 0

        for start in range(0, total, VERIFY_BATCH):
            if self.verify_ai_calls >= self.verify_ai_call_allowance:
                break
            batch = uncached_candidates[start:start + VERIFY_BATCH]
            payload, local_map = self._make_verify_payload(batch)

            batch_verdicts = None
            try:
                batch_verdicts = await self._verify_payload(
                    payload,
                    local_map,
                    max_tokens=1900,
                )
            except DiscoveryBudgetExhausted:
                break
            except Exception as exc:
                log.warning(
                    "verifier_batch_json_failed_degrading",
                    candidates=len(batch),
                    error=str(exc),
                )

            for d, lead_chunk in batch:
                if batch_verdicts is not None:
                    verdicts = batch_verdicts.get(d["canonical_key"], {})
                elif self.verify_ai_calls < self.verify_ai_call_allowance:
                    verdicts = await self._verify_one_candidate_resilient(
                        d,
                        lead_chunk,
                    )
                else:
                    # Budget exhaustion is not an irrelevant verdict. Leave
                    # unreviewed leads uncached so a future discovery pass can
                    # adjudicate them.
                    continue

                for n, lead in enumerate(lead_chunk):
                    verdict = verdicts.get(f"E{n+1}") or {
                        "relevant": False,
                        "confidence": 0,
                        "relation": "irrelevant",
                        "reason": "no valid verifier verdict",
                    }
                    conf = max(0.0, min(1.0, sf(verdict.get("confidence"))))
                    relation = str(verdict.get("relation") or "irrelevant")
                    normalized = {
                        "relevant": verdict.get("relevant") is True,
                        "confidence": conf,
                        "relation": relation,
                        "reason": clean(verdict.get("reason"))[:240],
                    }

                    self.evidence_cache[lead["_evidence_cache_key"]] = normalized

                    if (
                        normalized["relevant"] is True
                        and relation in MEANINGFUL_RELATIONS
                        and conf >= 0.70
                    ):
                        clean_lead = {
                            k: v for k, v in lead.items()
                            if not k.startswith("_")
                        }
                        verified[d["canonical_key"]].append({
                            **clean_lead,
                            "verified": True,
                            "verification_confidence": conf,
                            "relation": relation,
                            "reason": normalized["reason"],
                        })

                completed += 1

            save_json(EVIDENCE_CACHE_FILE, self.evidence_cache)
            print(
                f"Verifier progress: {completed}/{total} candidates "
                f"(cached incrementally)"
            )

        return verified


    async def attach_cached_chinese_display(self, discussions):
        for d in discussions:
            fp = d["fingerprint"]
            material = {
                "canonical_problem": fp.get("canonical_problem"),
                "actor": fp.get("actor"),
                "task": fp.get("task"),
                "object": fp.get("object"),
                "failure_mode": fp.get("failure_mode"),
                "consequence": fp.get("consequence"),
            }
            cached = self.zh_cache.get(hash_obj(material))
            if isinstance(cached, dict) and cached.get("title_zh"):
                d["display_zh"] = cached

    async def ensure_chinese_display(self, discussions):
        cache_hits = 0
        missing = []

        for d in discussions:
            fp = d["fingerprint"]
            material = {
                "canonical_problem": fp.get("canonical_problem"),
                "actor": fp.get("actor"),
                "task": fp.get("task"),
                "object": fp.get("object"),
                "failure_mode": fp.get("failure_mode"),
                "consequence": fp.get("consequence"),
            }
            key = hash_obj(material)
            cached = self.zh_cache.get(key)
            if isinstance(cached, dict) and cached.get("title_zh"):
                d["display_zh"] = cached
                cache_hits += 1
            else:
                d["_zh_cache_key"] = key
                missing.append(d)

        print(f"Chinese quick-read: {cache_hits} cache hits / {len(missing)} generated")

        for start in range(0, len(missing), 10):
            batch = missing[start:start + 10]
            payload = []
            idmap = {}

            for i, d in enumerate(batch):
                cid = f"C{i+1}"
                idmap[cid] = d
                fp = d["fingerprint"]
                payload.append({
                    "id": cid,
                    "problem": {
                        "canonical_problem": fp.get("canonical_problem"),
                        "actor": fp.get("actor"),
                        "task": fp.get("task"),
                        "object": fp.get("object"),
                        "failure_mode": fp.get("failure_mode"),
                        "consequence": fp.get("consequence"),
                    },
                })

            prompt = f"""Translate these problem candidates into concise Traditional Chinese for a founder dashboard.

INPUT:
{json.dumps(payload, ensure_ascii=False)}

Return ONLY valid JSON:
{{
  "candidates": [
    {{
      "id": "C1",
      "title_zh": "12-24字，直接說問題",
      "problem_zh": "一到兩句，快速說清楚誰在做什麼時遇到什麼失敗，以及造成什麼影響"
    }}
  ]
}}

Rules:
- Traditional Chinese used in Taiwan.
- Preserve product/company/model names in English when clearer.
- Do not exaggerate business importance.
- Do not invent missing facts.
- Avoid academic wording.
- Optimize for 10-second scanning.
- title_zh must be concrete.
- Output JSON only.
"""

            try:
                result = await call_llm(
                    prompt=prompt,
                    system_message=(
                        "You write concise Traditional Chinese product-intelligence summaries. "
                        "Preserve uncertainty and never invent evidence."
                    ),
                    model="mini",
                    parse_json=True,
                    usage_tracker=self.usage,
                    max_tokens=1800,
                )
            except Exception as exc:
                log.warning(
                    "chinese_quickread_batch_failed",
                    candidates=len(batch),
                    error=str(exc),
                )
                continue

            returned = {}
            if isinstance(result, dict):
                returned = {
                    str(x.get("id")): x
                    for x in result.get("candidates", [])
                    if isinstance(x, dict)
                }

            for cid, d in idmap.items():
                item = returned.get(cid) or {}
                display = {
                    "title_zh": clean(item.get("title_zh")),
                    "problem_zh": clean(item.get("problem_zh")),
                }
                if not display["title_zh"]:
                    continue
                d["display_zh"] = display
                self.zh_cache[d["_zh_cache_key"]] = display

            save_json(ZH_CACHE_FILE, self.zh_cache)

    def score(self, d, evidence):
        fp = d["fingerprint"]
        severity = max(1, min(5, int(fp.get("severity", 1) or 1)))
        fp_conf = sf(fp.get("confidence"), 0.65)

        rel = Counter(x["relation"] for x in evidence)
        src = Counter(x["source"] for x in evidence)
        source_count = len(src)

        object_text = clean(fp.get("object")).lower()
        task_text = clean(fp.get("task")).lower()
        failure_text = clean(fp.get("failure_mode")).lower()
        canonical_text = clean(fp.get("canonical_problem")).lower()

        object_tokens = tokens(object_text)
        task_tokens = tokens(task_text)
        failure_tokens = tokens(failure_text)

        actor_text = clean(fp.get("actor")).lower()
        consequence_text = clean(fp.get("consequence")).lower()
        buyer_text = clean(fp.get("buyer_context")).lower()

        object_tokens = tokens(object_text)
        task_tokens = tokens(task_text)
        failure_tokens = tokens(failure_text)
        actor_tokens = tokens(actor_text)
        consequence_tokens = tokens(consequence_text)

        generic_actors = {"user", "users", "people", "developer", "developers", "engineer", "engineers", "team", "teams"}
        explicit_buyer = buyer_text not in {"", "unclear", "none", "none mentioned", "specific user/group or unclear"}
        founder_unit_ready = fingerprint_is_founder_unit(fp)

        specificity = (
            8
            + min(len(actor_tokens), 4) * 5
            + min(len(object_tokens), 5) * 5
            + min(len(task_tokens), 6) * 5
            + min(len(failure_tokens), 8) * 5
            + min(len(consequence_tokens), 5) * 3
            + (12 if explicit_buyer else 0)
        )

        if actor_text in generic_actors or not actor_text:
            specificity -= 12
        if not founder_unit_ready:
            specificity -= 35

        vague_phrases = (
            "ai model does not produce reliable outputs",
            "model fails to complete tasks reliably",
            "ai model output is unreliable",
            "ai model assumptions lead to incorrect outputs",
            "performance and output quality",
            "project success",
            "communication channels",
            "incorrect outputs",
            "over-reliance on tools",
            "skill gap",
        )
        if any(p in canonical_text for p in vague_phrases):
            specificity -= 40

        if len(canonical_text.split()) < 6:
            specificity -= 10

        specificity = max(0.0, min(100.0, float(specificity)))

        community = min(
            100,
            30
            + severity * 10
            + fp_conf * 20
            + min(len({p.get("user_id") for p in same_problem_posts(d) if p.get("user_id") is not None}), 5) * 2,
        )

        direct_problem = rel["direct_problem_corroboration"]

        problem_validation = min(
            100,
            direct_problem * 55
            + rel["buyer_demand"] * 12
            + rel["ecosystem_activity"] * 6,
        )

        buyer = min(
            100,
            rel["buyer_demand"] * 42
            + (28 if explicit_buyer else 0),
        )

        solution_count = rel["solution_supply"] + rel["competitor"]
        solution_context = solution_count + rel["ecosystem_activity"]

        supply_gap = (
            50 if solution_count == 0
            else 44 if solution_count == 1
            else 34 if solution_count == 2
            else 24
        )

        timing_context = rel["why_now"] + rel["research_enabler"]
        timing = min(
            100,
            32
            + rel["why_now"] * 30
            + rel["research_enabler"] * 16
            + rel["ecosystem_activity"] * 7,
        )

        cross = min(100, 18 + source_count * 19)

        market = round(
            community * 0.22
            + specificity * 0.15
            + problem_validation * 0.20
            + buyer * 0.17
            + supply_gap * 0.08
            + timing * 0.08
            + cross * 0.10,
            1,
        )

        evidence_conf = (
            sum(x["verification_confidence"] for x in evidence)
            / len(evidence)
            if evidence
            else 0
        )
        confidence = round(
            min(
                100,
                fp_conf * 42
                + evidence_conf * 33
                + min(source_count, 4) * 5
                + specificity * 0.05,
            ),
            1,
        )

        buyer_evidence = rel["buyer_demand"] > 0 or explicit_buyer
        market_context = solution_context > 0 or timing_context > 0
        any_market_support = (
            rel["buyer_demand"]
            + rel["solution_supply"]
            + rel["competitor"]
            + rel["ecosystem_activity"]
            + rel["why_now"]
            + rel["research_enabler"]
        ) > 0

        if (
            direct_problem >= 1
            and buyer_evidence
            and explicit_buyer
            and founder_unit_ready
            and market_context
            and source_count >= 2
            and specificity >= 68
            and confidence >= 72
        ):
            stage = "opportunity"
        elif direct_problem >= 1:
            stage = "corroborated"
        elif any_market_support:
            stage = "market_supported"
        else:
            stage = "candidate"

        return {
            "stage": stage,
            "market_score": market,
            "confidence_score": confidence,
            "community_problem_score": round(community, 1),
            "corroboration_score": round(problem_validation, 1),
            "buyer_demand_score": round(buyer, 1),
            "supply_gap_score": round(supply_gap, 1),
            "cross_source_score": round(cross, 1),
            "source_counts": dict(src),
            "relation_counts": {
                **dict(rel),
                "problem_specificity_score": round(specificity, 1),
            },
        }

    async def persist(self, discussions, verified):
        processed_candidate_ids: list[int] = []
        async with async_session() as session:
            for d in discussions:
                fp = d["fingerprint"]
                evidence = verified.get(d["canonical_key"], [])
                same_posts = same_problem_posts(d)
                same_user_ids = {p.get("user_id") for p in same_posts if p.get("user_id") is not None}
                scores = self.score(d, evidence)
                d.update(scores)

                dates = [
                    p["posted_at"]
                    for p in same_posts
                    if p.get("posted_at") is not None
                ]

                values = {
                    "canonical_key": d["canonical_key"],
                    "title": d["title"],
                    "problem_statement": clean(
                        fp.get("canonical_problem")
                        or fp.get("failure_mode")
                    ),
                    "actor": clean(fp.get("actor")),
                    "actor_category": clean(fp.get("actor_category")),
                    "task": clean(fp.get("task")),
                    "object": clean(fp.get("object")),
                    "failure_mode": clean(fp.get("failure_mode")),
                    "consequence": clean(fp.get("consequence")),
                    "buyer_context": clean(fp.get("buyer_context")),
                    "workaround": clean(fp.get("workaround")),
                    "community_platform": d["platform"],
                    "discussion_key": d["discussion_key"],
                    "community_evidence_count": len(same_posts),
                    "community_user_count": len(same_user_ids),
                    "stage": scores["stage"],
                    "market_score": scores["market_score"],
                    "confidence_score": scores["confidence_score"],
                    "community_problem_score": scores[
                        "community_problem_score"
                    ],
                    "corroboration_score": scores[
                        "corroboration_score"
                    ],
                    "buyer_demand_score": scores[
                        "buyer_demand_score"
                    ],
                    "supply_gap_score": scores[
                        "supply_gap_score"
                    ],
                    "cross_source_score": scores[
                        "cross_source_score"
                    ],
                    "source_support": scores["source_counts"],
                    "relation_support": scores["relation_counts"],
                    "fingerprint": {
                        **fp,
                        "retrieval_profile": d["retrieval_profile"],
                        "cross_source_engine": ENGINE_VERSION,
                        "display_zh": d.get("display_zh", {}),
                        "same_problem_grouping": {
                            "engine": "deterministic_problem_atom_filter_r1",
                            "raw_discussion_posts": len(d.get("posts") or []),
                            "same_problem_posts": len(same_posts),
                            "same_problem_users": len(same_user_ids),
                            "zero_is_valid": True,
                        },
                    },
                    "first_seen_at": min(dates) if dates else None,
                    "last_seen_at": max(dates) if dates else None,
                    "calculated_at": datetime.utcnow(),
                }

                stmt = pg_insert(ProblemCandidate).values(**values)
                updates = {
                    k: getattr(stmt.excluded, k)
                    for k in values
                    if k not in {"canonical_key", "founder_status"}
                }

                candidate_id = (
                    await session.execute(
                        stmt.on_conflict_do_update(
                            index_elements=[
                                ProblemCandidate.canonical_key
                            ],
                            set_=updates,
                        ).returning(ProblemCandidate.id)
                    )
                ).scalar_one()
                processed_candidate_ids.append(int(candidate_id))

                # CandidateEvidence is part of the provenance chain used by
                # RadarEvidence. M13 discovery deleted/reinserted every row,
                # changing ids and causing duplicate/orphaned ledger evidence
                # on each refresh. M14 keeps stable evidence identities and
                # updates matching observations in place. Historical evidence
                # is retained rather than silently deleted.
                existing_rows = list((await session.execute(
                    select(CandidateEvidence).where(
                        CandidateEvidence.candidate_id == candidate_id
                    )
                )).scalars().all())
                existing_by_key = {}
                for existing in existing_rows:
                    key = (
                        clean(existing.source_type),
                        clean(existing.source_table),
                        clean(existing.source_ref),
                        clean(existing.relation),
                    )
                    existing_by_key.setdefault(key, existing)

                rows = []

                for p in same_posts[:20]:
                    rows.append({
                        "candidate_id": candidate_id,
                        "source_type": d["platform"],
                        "source_table": "posts",
                        "source_ref": str(p["source_ref"]),
                        "relation": "community_problem",
                        "title": (
                            p["title"][:500]
                            if p["title"]
                            else None
                        ),
                        "excerpt": p["problem_text"][:900],
                        "url": p["url"],
                        "retrieval_score": 1.0,
                        "verified": True,
                        "verification_confidence": sf(
                            fp.get("confidence"),
                            0.65,
                        ),
                        "evidence_metadata": {
                            "discussion_key": d["discussion_key"],
                            "time_unknown": p["time_unknown"],
                        },
                    })

                for x in evidence:
                    rows.append({
                        "candidate_id": candidate_id,
                        "source_type": x["source"],
                        "source_table": x["table"],
                        "source_ref": x["pk"],
                        "relation": x["relation"],
                        "title": x["title"] or None,
                        "excerpt": x["text"][:900],
                        "url": x["url"] or None,
                        "retrieval_score": x["retrieval_score"],
                        "verified": True,
                        "verification_confidence": x[
                            "verification_confidence"
                        ],
                        "evidence_metadata": {
                            "date": x.get("date"),
                            "reason": x.get("reason"),
                            "token_overlap": x.get("token_overlap"),
                        },
                    })

                if rows:
                    seen_keys = set()
                    for item in rows:
                        key = (
                            clean(item.get("source_type")),
                            clean(item.get("source_table")),
                            clean(item.get("source_ref")),
                            clean(item.get("relation")),
                        )
                        if key in seen_keys:
                            continue
                        seen_keys.add(key)
                        existing = existing_by_key.get(key)
                        if existing is None:
                            session.add(CandidateEvidence(**item))
                            continue
                        existing.title = item.get("title")
                        existing.excerpt = item.get("excerpt")
                        existing.url = item.get("url")
                        existing.retrieval_score = item.get("retrieval_score")
                        existing.verified = bool(item.get("verified"))
                        existing.verification_confidence = item.get("verification_confidence")
                        meta = dict(existing.evidence_metadata or {})
                        meta.update(item.get("evidence_metadata") or {})
                        meta["last_seen_by_discovery"] = datetime.utcnow().isoformat()
                        existing.evidence_metadata = meta

            await session.commit()
        return processed_candidate_ids


async def run_problem_candidates(
    *,
    fingerprint_ai_call_allowance: int = 2,
    profile_ai_call_allowance: int = 0,
    verify_ai_call_allowance: int = 2,
    translate: bool = False,
    incremental_only: bool = False,
    max_incremental_candidates: int = 16,
):
    return await ProblemCandidateEngine(
        fingerprint_ai_call_allowance=fingerprint_ai_call_allowance,
        profile_ai_call_allowance=profile_ai_call_allowance,
        verify_ai_call_allowance=verify_ai_call_allowance,
        translate=translate,
        incremental_only=incremental_only,
        max_incremental_candidates=max_incremental_candidates,
    ).run()
