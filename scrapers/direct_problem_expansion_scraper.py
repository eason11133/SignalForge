
"""Direct Problem Source Expansion — API + dynamic source discovery.

Adds a separate direct-problem collector without replacing the existing
Reddit/GitHub/StackOverflow scrapers.

No LLM calls.
"""

from __future__ import annotations

import asyncio
import html
import os
import re
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode, urlsplit

import feedparser
import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from database.connection import (
    async_session,
    ProblemCandidate,
    RadarCase,
    RadarClaim,
    GithubIssue,
    SOQuestion,
    SourceRegistry,
    SourceCheckpoint,
)
from scrapers.base_scraper import BaseScraper, _utc_naive
from scrapers.coverage_controller import choose_cases_for_source
from scrapers.source_network_common import mark_coverage

try:
    from config.settings import GITHUB_TOKEN as CFG_GITHUB_TOKEN
except Exception:
    CFG_GITHUB_TOKEN = None
try:
    from config.settings import SO_API_KEY as CFG_SO_API_KEY
except Exception:
    CFG_SO_API_KEY = None
try:
    from config.sources import REDDIT_SUBREDDITS, GITHUB_WATCHLIST_REPOS
except Exception:
    REDDIT_SUBREDDITS, GITHUB_WATCHLIST_REPOS = [], []
try:
    from scrapers.stackoverflow_scraper import SO_TAGS_TO_TRACK
except Exception:
    SO_TAGS_TO_TRACK = []

GITHUB_API = "https://api.github.com"
STACK_API = "https://api.stackexchange.com/2.3"
REDDIT_WEB = "https://www.reddit.com"
REDDIT_OAUTH = "https://oauth.reddit.com"

GITHUB_TOKEN = CFG_GITHUB_TOKEN or os.getenv("GITHUB_TOKEN")
SO_API_KEY = CFG_SO_API_KEY or os.getenv("SO_API_KEY")
REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET")
REDDIT_USER_AGENT = os.getenv(
    "REDDIT_USER_AGENT",
    "community-mind-mirror/1.0 direct-problem-source-discovery",
)

GENERIC = {
    "about","after","again","agent","agents","also","because","being","build",
    "building","cannot","could","data","does","doing","from","have","into",
    "issue","issues","just","like","model","models","more","need","problem",
    "problems","really","same","software","some","still","system","that",
    "their","there","these","they","thing","things","this","tool","tools",
    "using","very","want","when","where","which","with","work","works","would",
    "output","user","users","application","applications","code",
}
PROBLEM_RE = re.compile(
    r"""(?ix)\b(
        error|exception|fail(?:ed|ing|s|ure)?|broken|bug|bugs|
        unable|cannot|can't|cant|won't|doesn't|doesnt|
        not\s+working|does\s+not\s+work|issue|problem|
        unreliable|inconsistent|regression|timeout|crash|
        difficult|hard\s+to|struggl\w*|workaround|work\s*around|
        missing|incorrect|wrong|unexpected|invalid|
        forget(?:s|ting)?|memory|context\s+loss|permission\s+error
    )\b"""
)
SUBREDDIT_RE = re.compile(r"/r/([^/]+)/", re.I)


def clean_text(value: Any) -> str:
    x = html.unescape(str(value or ""))
    x = re.sub(r"<[^>]+>", " ", x)
    x = re.sub(r"https?://\S+", " ", x)
    return re.sub(r"\s+", " ", x).strip()


def tokenize(text: str) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z0-9_+.#-]{2,}", text or "")
    out, seen = [], set()
    for w in words:
        k = w.lower().strip(".")
        if len(k) < 4 or k in GENERIC or k in seen:
            continue
        seen.add(k)
        out.append(w)
    return out


def build_query(candidate: ProblemCandidate) -> str:
    # Compact search signature: object + failure + task/fallback.
    object_terms = tokenize(str(candidate.object or ""))
    failure_terms = tokenize(str(candidate.failure_mode or ""))
    task_terms = tokenize(str(candidate.task or ""))
    fallback_terms = tokenize(
        " ".join([
            str(candidate.title or ""),
            str(candidate.problem_statement or ""),
        ])
    )

    picked = []
    seen = set()

    def add(term):
        key = term.lower().strip(".")
        if not key or key in seen:
            return
        seen.add(key)
        picked.append(term)

    if object_terms:
        add(object_terms[0])

    for term in failure_terms[:2]:
        add(term)

    for source in (task_terms, fallback_terms):
        for term in source:
            if len(picked) >= 3:
                break
            add(term)
        if len(picked) >= 3:
            break

    return " ".join(picked[:3])[:120]


def overlap_count(query: str, text: str) -> int:
    q = {x.lower() for x in tokenize(query)}
    t = {x.lower() for x in tokenize(text)}
    return len(q & t)


def is_problem_hit(query: str, text: str) -> bool:
    return bool(PROBLEM_RE.search(text or "")) and overlap_count(query, text) >= 1


def gh_repo_from_item(item: dict) -> str | None:
    repo_url = str(item.get("repository_url") or "")
    if "/repos/" in repo_url:
        return repo_url.split("/repos/", 1)[1].strip("/")
    try:
        bits = [x for x in urlsplit(str(item.get("html_url") or "")).path.split("/") if x]
        if len(bits) >= 2:
            return f"{bits[0]}/{bits[1]}"
    except Exception:
        pass
    return None


def naive_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
            timezone.utc
        ).replace(tzinfo=None)
    except Exception:
        return None


class DirectProblemExpansionScraper(BaseScraper):
    def __init__(self):
        super().__init__("direct_problem_expansion", request_delay=1.0)
        self.stats = Counter()
        self.github_headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "community-mind-mirror",
        }
        if GITHUB_TOKEN:
            self.github_headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
        self.reddit_token = None
        self.reddit_rate_limited = False

    async def scrape(self, **kwargs):
        await self._seed_registry()
        cases = await self._open_problem_cases()
        if not cases:
            self.log.info("no_open_problem_cases")
            return

        self.log.info(
            "direct_problem_expansion_start",
            cases=len(cases),
            github_mode="authenticated" if GITHUB_TOKEN else "anonymous",
            stackexchange_mode="keyed" if SO_API_KEY else "anonymous",
            reddit_mode="oauth_if_approved"
            if REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET
            else "rss_conservative",
        )

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(35.0),
            follow_redirects=True,
        ) as client:
            if REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET:
                self.reddit_token = await self._reddit_get_token(client)
            await self._run_stackexchange(client, cases)
            await self._run_github(client, cases)
            await self._run_reddit(client, cases)
            await self._poll_active_stack_tags(client)
            await self._poll_active_github_repos(client)
            await self._poll_active_reddit_subs(client)

        self.log.info("direct_problem_expansion_complete", **dict(self.stats))

    async def _open_problem_cases(self):
        async with async_session() as session:
            return list((await session.execute(
                select(RadarCase, ProblemCandidate)
                .join(ProblemCandidate, ProblemCandidate.id == RadarCase.candidate_id)
                .join(
                    RadarClaim,
                    (RadarClaim.case_id == RadarCase.id)
                    & (RadarClaim.claim_code == "C02"),
                )
                .where(RadarClaim.state.in_(["UNKNOWN", "INSUFFICIENT", "CONFLICTED"]))
                .order_by(RadarCase.id)
            )).all())

    async def _seed_registry(self):
        for sr in REDDIT_SUBREDDITS:
            await self._observe_source(
                "reddit_subreddit", str(sr),
                f"https://www.reddit.com/r/{sr}/",
                "seed", 0, 0, 0,
                {"seed_family": "REDDIT_SUBREDDITS"},
            )
        for tag in SO_TAGS_TO_TRACK:
            await self._observe_source(
                "stackoverflow_tag", str(tag),
                f"https://stackoverflow.com/questions/tagged/{tag}",
                "seed", 0, 0, 0,
                {"seed_family": "SO_TAGS_TO_TRACK"},
            )
        for repo in GITHUB_WATCHLIST_REPOS:
            await self._observe_source(
                "github_repo_issues", str(repo),
                f"https://github.com/{repo}/issues",
                "seed", 0, 0, 0,
                {"seed_family": "GITHUB_WATCHLIST_REPOS"},
            )

    async def _observe_source(
        self, source_type, source_key, source_url, origin,
        seen, relevant, problem, metadata=None
    ):
        now = _utc_naive()
        async with async_session() as session:
            row = (await session.execute(
                select(SourceRegistry).where(
                    SourceRegistry.source_type == source_type,
                    SourceRegistry.source_key == source_key,
                )
            )).scalar_one_or_none()

            if row is None:
                row = SourceRegistry(
                    source_type=source_type,
                    source_key=source_key,
                    source_url=source_url,
                    origin=origin,
                    status="ACTIVE" if origin == "seed" else "WATCH",
                    evidence_role="DIRECT_PROBLEM",
                    records_seen=0,
                    relevant_hits=0,
                    direct_problem_hits=0,
                    yield_score=0.0,
                    source_metadata=metadata or {},
                )
                session.add(row)
                await session.flush()
                self.stats["sources_discovered"] += 1

            row.records_seen = int(row.records_seen or 0) + int(seen)
            row.relevant_hits = int(row.relevant_hits or 0) + int(relevant)
            row.direct_problem_hits = int(row.direct_problem_hits or 0) + int(problem)
            row.last_seen_at = now
            row.last_success_at = now
            row.last_error = None
            row.yield_score = round(
                float(row.direct_problem_hits or 0) /
                max(1, int(row.records_seen or 0)),
                4,
            )
            if row.origin != "seed" and int(row.direct_problem_hits or 0) >= 2:
                row.status = "ACTIVE"

            meta = dict(row.source_metadata or {})
            meta.update(metadata or {})
            row.source_metadata = meta
            await session.commit()

    async def _active_sources(self, source_type, limit):
        async with async_session() as session:
            return list((await session.execute(
                select(SourceRegistry)
                .where(
                    SourceRegistry.source_type == source_type,
                    SourceRegistry.status == "ACTIVE",
                )
                .order_by(
                    SourceRegistry.yield_score.desc(),
                    SourceRegistry.last_success_at.asc().nullsfirst(),
                )
                .limit(limit)
            )).scalars().all())

    async def _source_error(self, src, error):
        async with async_session() as session:
            row = await session.get(SourceRegistry, src.id)
            if row:
                row.last_error = str(error)[:2000]
                row.last_seen_at = _utc_naive()
                await session.commit()

    async def _get_checkpoint(self, key):
        async with async_session() as session:
            row = (await session.execute(
                select(SourceCheckpoint).where(SourceCheckpoint.checkpoint_key == key)
            )).scalar_one_or_none()
            return int(row.cursor or 0) if row else 0

    async def _set_checkpoint(self, key, cursor, metadata=None):
        # SourceCheckpoint.checkpoint_metadata maps to physical column `metadata`.
        table = SourceCheckpoint.__table__
        meta_col = table.c["metadata"]

        async with async_session() as session:
            stmt = pg_insert(table).values({
                table.c.checkpoint_key: key,
                table.c.cursor: cursor,
                meta_col: metadata or {},
            })
            stmt = stmt.on_conflict_do_update(
                index_elements=[table.c.checkpoint_key],
                set_={
                    table.c.cursor: cursor,
                    meta_col: metadata or {},
                    table.c.updated_at: _utc_naive(),
                },
            )
            await session.execute(stmt)
            await session.commit()

    def _batch(self, rows, cursor, size):
        if not rows:
            return [], 0
        n = len(rows)
        cursor %= n
        out = [rows[(cursor + i) % n] for i in range(min(size, n))]
        return out, (cursor + len(out)) % n

    # -------------------- Stack Exchange --------------------

    async def _run_stackexchange(self, client, cases):
        batch_size = int(os.getenv(
            "DIRECT_PROBLEM_SO_QUERY_BATCH",
            "24" if SO_API_KEY else "12",
        ))
        batch = await choose_cases_for_source(
            cases,
            "stackoverflow",
            limit=min(batch_size, len(cases)),
            min_relevance=2,
        )
        self.stats["coverage_controller_so_selected"] += len(batch)

        for case, candidate in batch:
            query = build_query(candidate)
            if query:
                await self._so_search(
                    client,
                    query,
                    case.id,
                    candidate.id,
                )
                await asyncio.sleep(0.35)

    async def _so_search(self, client, query, case_id, candidate_id):
        params = {
            "site": "stackoverflow",
            "q": query,
            "sort": "activity",
            "order": "desc",
            "pagesize": 50,
            "filter": "withbody",
            "fromdate": int(
                (datetime.now(timezone.utc) - timedelta(days=365)).timestamp()
            ),
        }
        if SO_API_KEY:
            params["key"] = SO_API_KEY

        try:
            resp = await client.get(
                f"{STACK_API}/search/advanced",
                params=params,
            )
            if resp.status_code == 429:
                await mark_coverage(
                    case_id=case_id,
                    source_type="stackoverflow",
                    query=query,
                    hits_seen=0,
                    direct_problem_hits=0,
                    status="RATE_LIMITED",
                    error="HTTP 429",
                    metadata={"collector": "problem_sources"},
                )
                self.stats["so_rate_limited"] += 1
                return
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            self.stats["so_errors"] += 1
            await mark_coverage(
                case_id=case_id,
                source_type="stackoverflow",
                query=query,
                hits_seen=0,
                direct_problem_hits=0,
                status="ERROR",
                error=str(e),
                metadata={"collector": "problem_sources"},
            )
            self.log.warning("so_dynamic_search_failed", query=query, error=str(e))
            return

        if data.get("backoff"):
            await asyncio.sleep(min(int(data["backoff"]), 120))

        items = data.get("items", [])
        self.stats["so_queries"] += 1
        self.stats["so_items_seen"] += len(items)
        direct_hits = 0

        for item in items:
            text = f"{clean_text(item.get('title'))} {clean_text(item.get('body'))}"
            relevant = overlap_count(query, text) >= 1
            problem = is_problem_hit(query, text)
            await self._upsert_so_question(item, candidate_id, query)

            if relevant:
                self.stats["so_relevant"] += 1
            if problem:
                self.stats["so_problem_hits"] += 1
                direct_hits += 1

            for tag in item.get("tags") or []:
                await self._observe_source(
                    "stackoverflow_tag", str(tag),
                    f"https://stackoverflow.com/questions/tagged/{tag}",
                    "discovered",
                    1, 1 if relevant else 0, 1 if problem else 0,
                    {"discovered_by": "candidate_search", "last_query": query},
                )

        await mark_coverage(
            case_id=case_id,
            source_type="stackoverflow",
            query=query,
            hits_seen=len(items),
            direct_problem_hits=direct_hits,
            status="SUCCESS_HITS" if items else "SUCCESS_ZERO",
            metadata={
                "collector": "problem_sources",
                "quota_remaining": data.get("quota_remaining"),
            },
        )
        self.log.info(
            "so_dynamic_search",
            query=query,
            items=len(items),
            quota_remaining=data.get("quota_remaining"),
        )

    async def _upsert_so_question(self, item, matched_candidate_id, discovery_query):
        qid = item.get("question_id")
        if not qid:
            return
        values = {
            "so_question_id": qid,
            "title": item.get("title"),
            "tags": item.get("tags"),
            "view_count": item.get("view_count", 0),
            "answer_count": item.get("answer_count", 0),
            "score": item.get("score", 0),
            "is_answered": item.get("is_answered", False),
            "link": item.get("link"),
            "creation_date": (
                datetime.utcfromtimestamp(item["creation_date"])
                if item.get("creation_date") else None
            ),
            "last_activity_date": (
                datetime.utcfromtimestamp(item["last_activity_date"])
                if item.get("last_activity_date") else None
            ),
            "raw_metadata": {
                "owner": item.get("owner"),
                "content_license": item.get("content_license"),
                "body": item.get("body"),
                "discovery_query": discovery_query,
                "matched_candidate_id": matched_candidate_id,
                "source_expansion": True,
            },
            "created_at": _utc_naive(),
        }
        async with async_session() as session:
            stmt = pg_insert(SOQuestion).values(**values).on_conflict_do_update(
                index_elements=["so_question_id"],
                set_={
                    "title": values["title"],
                    "tags": values["tags"],
                    "view_count": values["view_count"],
                    "answer_count": values["answer_count"],
                    "score": values["score"],
                    "is_answered": values["is_answered"],
                    "last_activity_date": values["last_activity_date"],
                    "raw_metadata": values["raw_metadata"],
                },
            )
            await session.execute(stmt)
            await session.commit()
        self.records_fetched += 1

    async def _poll_active_stack_tags(self, client):
        for src in await self._active_sources("stackoverflow_tag", 8):
            params = {
                "site": "stackoverflow",
                "tagged": src.source_key,
                "sort": "activity",
                "order": "desc",
                "pagesize": 100,
                "filter": "withbody",
            }
            if SO_API_KEY:
                params["key"] = SO_API_KEY
            try:
                resp = await client.get(f"{STACK_API}/questions", params=params)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                await self._source_error(src, e)
                continue

            items = data.get("items", [])
            problems = 0
            for item in items:
                text = f"{clean_text(item.get('title'))} {clean_text(item.get('body'))}"
                if PROBLEM_RE.search(text):
                    problems += 1
                await self._upsert_so_question(item, None, f"tag:{src.source_key}")

            await self._observe_source(
                "stackoverflow_tag", src.source_key, src.source_url, src.origin,
                len(items), len(items), problems,
                {"last_poll": "tag_questions"},
            )
            self.stats["so_active_tags_polled"] += 1

            if data.get("backoff"):
                await asyncio.sleep(min(int(data["backoff"]), 120))

    # -------------------- GitHub Issues --------------------

    async def _run_github(self, client, cases):
        batch_size = int(os.getenv(
            "DIRECT_PROBLEM_GITHUB_QUERY_BATCH",
            "20" if GITHUB_TOKEN else "5",
        ))
        batch = await choose_cases_for_source(
            cases,
            "github_issues",
            limit=min(batch_size, len(cases)),
            min_relevance=2,
        )
        search_delay = 2.2 if GITHUB_TOKEN else 7.0
        self.stats["coverage_controller_github_selected"] += len(batch)

        for case, candidate in batch:
            query = build_query(candidate)
            if not query:
                continue
            if not await self._github_issue_search(
                client,
                query,
                case.id,
                candidate.id,
            ):
                break
            await asyncio.sleep(search_delay)

    async def _github_issue_search(self, client, query, case_id, candidate_id):
        params = {
            "q": f"{query} in:title,body is:issue is:public",
            "sort": "updated",
            "order": "desc",
            "per_page": 50,
        }
        try:
            resp = await client.get(
                f"{GITHUB_API}/search/issues",
                params=params,
                headers=self.github_headers,
            )
        except Exception as e:
            self.stats["github_errors"] += 1
            await mark_coverage(
                case_id=case_id,
                source_type="github_issues",
                query=query,
                hits_seen=0,
                direct_problem_hits=0,
                status="ERROR",
                error=str(e),
                metadata={"collector": "problem_sources"},
            )
            self.log.warning("github_issue_search_failed", query=query, error=str(e))
            return True

        if resp.status_code in (403, 429):
            self.stats["github_rate_limited"] += 1
            wait = self._github_wait_seconds(resp)
            await mark_coverage(
                case_id=case_id,
                source_type="github_issues",
                query=query,
                hits_seen=0,
                direct_problem_hits=0,
                status="RATE_LIMITED",
                error=f"HTTP {resp.status_code}",
                metadata={
                    "collector": "problem_sources",
                    "wait_seconds": wait,
                },
            )
            self.log.warning(
                "github_rate_limited",
                status=resp.status_code,
                wait_seconds=wait,
            )
            if wait <= 90:
                await asyncio.sleep(wait)
            return False

        try:
            resp.raise_for_status()
            items = resp.json().get("items", [])
        except Exception as e:
            self.stats["github_errors"] += 1
            await mark_coverage(
                case_id=case_id,
                source_type="github_issues",
                query=query,
                hits_seen=0,
                direct_problem_hits=0,
                status="ERROR",
                error=str(e),
                metadata={"collector": "problem_sources"},
            )
            self.log.warning("github_issue_search_bad_response", error=str(e))
            return True

        self.stats["github_queries"] += 1
        self.stats["github_items_seen"] += len(items)
        direct_hits = 0

        for item in items:
            if item.get("pull_request"):
                continue
            repo = gh_repo_from_item(item)
            if not repo:
                continue
            text = f"{clean_text(item.get('title'))} {clean_text(item.get('body'))}"
            relevant = overlap_count(query, text) >= 1
            problem = is_problem_hit(query, text)
            await self._upsert_github_issue(item, repo, candidate_id, query)

            if relevant:
                self.stats["github_relevant"] += 1
            if problem:
                self.stats["github_problem_hits"] += 1
                direct_hits += 1

            await self._observe_source(
                "github_repo_issues", repo,
                f"https://github.com/{repo}/issues",
                "discovered",
                1, 1 if relevant else 0, 1 if problem else 0,
                {"discovered_by": "candidate_issue_search", "last_query": query},
            )

        await mark_coverage(
            case_id=case_id,
            source_type="github_issues",
            query=query,
            hits_seen=len(items),
            direct_problem_hits=direct_hits,
            status="SUCCESS_HITS" if items else "SUCCESS_ZERO",
            metadata={
                "collector": "problem_sources",
                "remaining": resp.headers.get("x-ratelimit-remaining"),
            },
        )
        self.log.info(
            "github_issue_search",
            query=query,
            items=len(items),
            remaining=resp.headers.get("x-ratelimit-remaining"),
        )
        return True

    def _github_wait_seconds(self, resp):
        if resp.headers.get("retry-after"):
            try:
                return max(1, min(300, int(resp.headers["retry-after"])))
            except Exception:
                pass
        try:
            if int(resp.headers.get("x-ratelimit-remaining", "1")) == 0:
                reset = int(resp.headers.get("x-ratelimit-reset", "0"))
                return max(1, min(300, reset - int(time.time()) + 2))
        except Exception:
            pass
        return 60

    async def _upsert_github_issue(self, item, repo, candidate_id, query):
        iid = item.get("id")
        number = item.get("number")
        if not iid or number is None:
            return
        labels = [
            x.get("name") if isinstance(x, dict) else str(x)
            for x in (item.get("labels") or [])
        ]
        values = {
            "github_issue_id": iid,
            "repo_full_name": repo,
            "issue_number": number,
            "title": item.get("title"),
            "body": item.get("body"),
            "state": item.get("state"),
            "labels": labels,
            "author_login": (item.get("user") or {}).get("login"),
            "comments_count": item.get("comments", 0),
            "html_url": item.get("html_url"),
            "created_at": naive_iso(item.get("created_at")),
            "updated_at": naive_iso(item.get("updated_at")),
            "closed_at": naive_iso(item.get("closed_at")),
            "raw_metadata": {
                "repository_url": item.get("repository_url"),
                "discovery_query": query,
                "matched_candidate_id": candidate_id,
                "source_expansion": True,
            },
            "last_scraped_at": _utc_naive(),
        }
        async with async_session() as session:
            stmt = pg_insert(GithubIssue).values(**values).on_conflict_do_update(
                index_elements=["github_issue_id"],
                set_={
                    "title": values["title"],
                    "body": values["body"],
                    "state": values["state"],
                    "labels": values["labels"],
                    "comments_count": values["comments_count"],
                    "updated_at": values["updated_at"],
                    "closed_at": values["closed_at"],
                    "raw_metadata": values["raw_metadata"],
                    "last_scraped_at": values["last_scraped_at"],
                },
            )
            await session.execute(stmt)
            await session.commit()
        self.records_fetched += 1

    async def _poll_active_github_repos(self, client):
        for src in await self._active_sources("github_repo_issues", 8):
            since = src.last_success_at or (_utc_naive() - timedelta(days=30))
            since_iso = since.replace(
                tzinfo=timezone.utc
            ).isoformat().replace("+00:00", "Z")
            try:
                resp = await client.get(
                    f"{GITHUB_API}/repos/{src.source_key}/issues",
                    params={
                        "state": "all",
                        "sort": "updated",
                        "direction": "desc",
                        "per_page": 100,
                        "since": since_iso,
                    },
                    headers=self.github_headers,
                )
                if resp.status_code in (403, 429):
                    await self._source_error(src, f"rate_limited:{resp.status_code}")
                    break
                resp.raise_for_status()
                items = [
                    x for x in resp.json()
                    if isinstance(x, dict) and not x.get("pull_request")
                ]
            except Exception as e:
                await self._source_error(src, e)
                continue

            problems = 0
            for item in items:
                text = f"{clean_text(item.get('title'))} {clean_text(item.get('body'))}"
                if PROBLEM_RE.search(text):
                    problems += 1
                await self._upsert_github_issue(
                    item, src.source_key, None, f"repo:{src.source_key}"
                )

            await self._observe_source(
                "github_repo_issues", src.source_key, src.source_url, src.origin,
                len(items), len(items), problems,
                {"last_poll": "repo_issues"},
            )
            self.stats["github_active_repos_polled"] += 1
            await asyncio.sleep(1.0)

    # -------------------- Reddit --------------------

    async def _run_reddit(self, client, cases):
        oauth_mode = bool(self.reddit_token)
        batch_size = int(os.getenv(
            "DIRECT_PROBLEM_REDDIT_QUERY_BATCH",
            "12" if oauth_mode else "4",
        ))
        batch = await choose_cases_for_source(
            cases,
            "reddit",
            limit=min(batch_size, len(cases)),
            min_relevance=2,
        )
        self.stats["coverage_controller_reddit_selected"] += len(batch)

        for case, candidate in batch:
            if self.reddit_rate_limited:
                break
            query = build_query(candidate)
            if not query:
                continue
            if oauth_mode:
                await self._reddit_oauth_search(
                    client, query, case.id, candidate.id
                )
                await asyncio.sleep(1.2)
            else:
                await self._reddit_rss_search(
                    client, query, case.id, candidate.id
                )
                await asyncio.sleep(8.0)

    async def _reddit_get_token(self, client):
        try:
            resp = await client.post(
                f"{REDDIT_WEB}/api/v1/access_token",
                auth=(REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET),
                data={"grant_type": "client_credentials"},
                headers={"User-Agent": REDDIT_USER_AGENT},
            )
            if resp.status_code in (401, 403):
                self.log.warning(
                    "reddit_oauth_not_authorized",
                    status=resp.status_code,
                    note="Falling back to RSS; use only approved Data API credentials.",
                )
                return None
            resp.raise_for_status()
            return resp.json().get("access_token")
        except Exception as e:
            self.log.warning("reddit_oauth_token_failed", error=str(e))
            return None

    async def _reddit_oauth_search(self, client, query, case_id, candidate_id):
        try:
            resp = await client.get(
                f"{REDDIT_OAUTH}/search",
                params={
                    "q": query,
                    "sort": "new",
                    "t": "month",
                    "limit": 100,
                    "raw_json": 1,
                    "type": "link",
                },
                headers={
                    "Authorization": f"Bearer {self.reddit_token}",
                    "User-Agent": REDDIT_USER_AGENT,
                },
            )
            if resp.status_code == 429:
                self.reddit_rate_limited = True
                self.stats["reddit_rate_limited"] += 1
                await mark_coverage(
                    case_id=case_id,
                    source_type="reddit",
                    query=query,
                    hits_seen=0,
                    direct_problem_hits=0,
                    status="RATE_LIMITED",
                    error="HTTP 429",
                    metadata={"collector": "problem_sources", "mode": "oauth"},
                )
                return
            resp.raise_for_status()
            children = resp.json().get("data", {}).get("children", [])
        except Exception as e:
            self.stats["reddit_errors"] += 1
            await mark_coverage(
                case_id=case_id,
                source_type="reddit",
                query=query,
                hits_seen=0,
                direct_problem_hits=0,
                status="ERROR",
                error=str(e),
                metadata={"collector": "problem_sources", "mode": "oauth"},
            )
            self.log.warning("reddit_oauth_search_failed", query=query, error=str(e))
            return

        direct_hits = 0
        for child in children:
            problem = await self._store_reddit_json(
                child.get("data", {}), query, candidate_id
            )
            direct_hits += int(bool(problem))
        self.stats["reddit_queries"] += 1
        self.stats["reddit_items_seen"] += len(children)
        await mark_coverage(
            case_id=case_id,
            source_type="reddit",
            query=query,
            hits_seen=len(children),
            direct_problem_hits=direct_hits,
            status="SUCCESS_HITS" if children else "SUCCESS_ZERO",
            metadata={"collector": "problem_sources", "mode": "oauth"},
        )

    async def _store_reddit_json(self, data, query, candidate_id):
        post_id = data.get("id")
        if not post_id:
            return
        subreddit = data.get("subreddit")
        title = clean_text(data.get("title"))
        body = clean_text(data.get("selftext")) or title
        text = f"{title} {body}"
        relevant = overlap_count(query, text) >= 1
        problem = is_problem_hit(query, text)

        author = data.get("author")
        user_id = None
        if author and author != "[deleted]":
            user_id = await self.upsert_user(
                "reddit", author, username=author,
                profile_url=f"https://www.reddit.com/user/{author}",
            )
        await self.upsert_post(
            user_id=user_id,
            platform_name="reddit",
            post_type="submission",
            platform_post_id=f"reddit_{post_id}",
            title=title,
            body=body,
            url=f"https://www.reddit.com{data.get('permalink', '')}",
            subreddit=subreddit,
            score=int(data.get("score") or 0),
            num_comments=int(data.get("num_comments") or 0),
            posted_at=(
                datetime.fromtimestamp(float(data["created_utc"]), tz=timezone.utc)
                if data.get("created_utc") else None
            ),
            raw_metadata={
                "source_expansion": True,
                "discovery_query": query,
                "matched_candidate_id": candidate_id or None,
            },
        )
        if subreddit:
            await self._observe_source(
                "reddit_subreddit", subreddit,
                f"https://www.reddit.com/r/{subreddit}/",
                "discovered",
                1, 1 if relevant else 0, 1 if problem else 0,
                {"discovered_by": "candidate_search", "last_query": query},
            )
        if relevant:
            self.stats["reddit_relevant"] += 1
        if problem:
            self.stats["reddit_problem_hits"] += 1
        return problem

    async def _reddit_rss_search(self, client, query, case_id, candidate_id):
        try:
            resp = await client.get(
                f"{REDDIT_WEB}/search.rss",
                params={"q": query, "sort": "new", "t": "month"},
                headers={"User-Agent": REDDIT_USER_AGENT},
            )
            if resp.status_code == 429:
                self.reddit_rate_limited = True
                self.stats["reddit_rate_limited"] += 1
                await mark_coverage(
                    case_id=case_id,
                    source_type="reddit",
                    query=query,
                    hits_seen=0,
                    direct_problem_hits=0,
                    status="RATE_LIMITED",
                    error="HTTP 429",
                    metadata={"collector": "problem_sources", "mode": "rss"},
                )
                self.log.warning(
                    "reddit_rss_rate_limited_stop_for_run",
                    note="No bypass attempted; a later run resumes via coverage controller.",
                )
                return
            resp.raise_for_status()
            feed = feedparser.parse(resp.text)
        except Exception as e:
            self.stats["reddit_errors"] += 1
            await mark_coverage(
                case_id=case_id,
                source_type="reddit",
                query=query,
                hits_seen=0,
                direct_problem_hits=0,
                status="ERROR",
                error=str(e),
                metadata={"collector": "problem_sources", "mode": "rss"},
            )
            self.log.warning("reddit_rss_search_failed", query=query, error=str(e))
            return

        self.stats["reddit_queries"] += 1
        self.stats["reddit_items_seen"] += len(feed.entries)
        direct_hits = 0

        for entry in feed.entries:
            link = entry.get("link", "")
            m = re.search(r"/comments/([a-z0-9]+)/", link, re.I)
            if not m:
                continue
            post_id = m.group(1)
            sr_match = SUBREDDIT_RE.search(link)
            subreddit = sr_match.group(1) if sr_match else None
            title = clean_text(entry.get("title"))
            body = clean_text(
                entry.get("summary", "")
                or entry.get("content", [{}])[0].get("value", "")
            ) or title
            text = f"{title} {body}"
            relevant = overlap_count(query, text) >= 1
            problem = is_problem_hit(query, text)

            await self.upsert_post(
                user_id=None,
                platform_name="reddit",
                post_type="submission",
                platform_post_id=f"reddit_{post_id}",
                title=title,
                body=body,
                url=link,
                subreddit=subreddit,
                raw_metadata={
                    "source_expansion": True,
                    "discovery_query": query,
                    "matched_candidate_id": candidate_id,
                    "mode": "rss",
                },
            )
            if subreddit:
                await self._observe_source(
                    "reddit_subreddit", subreddit,
                    f"https://www.reddit.com/r/{subreddit}/",
                    "discovered",
                    1, 1 if relevant else 0, 1 if problem else 0,
                    {"discovered_by": "candidate_rss_search", "last_query": query},
                )
            if relevant:
                self.stats["reddit_relevant"] += 1
            if problem:
                self.stats["reddit_problem_hits"] += 1
                direct_hits += 1

        await mark_coverage(
            case_id=case_id,
            source_type="reddit",
            query=query,
            hits_seen=len(feed.entries),
            direct_problem_hits=direct_hits,
            status="SUCCESS_HITS" if feed.entries else "SUCCESS_ZERO",
            metadata={"collector": "problem_sources", "mode": "rss"},
        )

    async def _poll_active_reddit_subs(self, client):
        # Deliberately tiny in RSS fallback mode.
        for src in await self._active_sources(
            "reddit_subreddit",
            6 if self.reddit_token else 2,
        ):
            if self.reddit_rate_limited:
                break
            if self.reddit_token:
                try:
                    resp = await client.get(
                        f"{REDDIT_OAUTH}/r/{src.source_key}/new",
                        params={"limit": 100, "raw_json": 1},
                        headers={
                            "Authorization": f"Bearer {self.reddit_token}",
                            "User-Agent": REDDIT_USER_AGENT,
                        },
                    )
                    if resp.status_code == 429:
                        self.reddit_rate_limited = True
                        break
                    resp.raise_for_status()
                    children = resp.json().get("data", {}).get("children", [])
                except Exception as e:
                    await self._source_error(src, e)
                    continue

                problems = 0
                for child in children:
                    data = child.get("data", {})
                    text = f"{clean_text(data.get('title'))} {clean_text(data.get('selftext'))}"
                    if PROBLEM_RE.search(text):
                        problems += 1
                    await self._store_reddit_json(
                        data, src.source_key, 0
                    )
                await self._observe_source(
                    "reddit_subreddit", src.source_key, src.source_url, src.origin,
                    len(children), len(children), problems,
                    {"last_poll": "oauth_subreddit_new"},
                )
            else:
                try:
                    resp = await client.get(
                        f"{REDDIT_WEB}/r/{src.source_key}/new/.rss?limit=100",
                        headers={"User-Agent": REDDIT_USER_AGENT},
                    )
                    if resp.status_code == 429:
                        self.reddit_rate_limited = True
                        break
                    resp.raise_for_status()
                    feed = feedparser.parse(resp.text)
                except Exception as e:
                    await self._source_error(src, e)
                    continue

                problems = sum(
                    1 for entry in feed.entries
                    if PROBLEM_RE.search(
                        f"{clean_text(entry.get('title'))} "
                        f"{clean_text(entry.get('summary'))}"
                    )
                )
                await self._observe_source(
                    "reddit_subreddit", src.source_key, src.source_url, src.origin,
                    len(feed.entries), len(feed.entries), problems,
                    {"last_poll": "rss_subreddit_new"},
                )
                await asyncio.sleep(8.0)

            self.stats["reddit_active_subs_polled"] += 1
