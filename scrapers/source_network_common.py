"""Shared primitives for the adaptive multi-site source network."""
from __future__ import annotations

import hashlib
import html
import os
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from database.connection import (
    async_session,
    ExternalProblemItem,
    RadarSourceCoverage,
    SourceRegistry,
)
from scrapers.base_scraper import _utc_naive

USER_AGENT = os.getenv(
    "SOURCE_NETWORK_USER_AGENT",
    "community-mind-mirror/1.0 source-network",
)

GENERIC_TERMS = {
    "about","after","again","agent","agents","also","because","being","build",
    "building","cannot","could","data","does","doing","from","have","into",
    "issue","issues","just","like","model","models","more","need","problem",
    "problems","really","same","software","some","still","system","that",
    "their","there","these","they","thing","things","this","tool","tools",
    "using","very","want","when","where","which","with","work","works","would",
    "output","user","users","application","applications","code","good",
}

PROBLEM_RE = re.compile(
    r"""(?ix)\b(
        error|exception|fail(?:ed|ing|s|ure)?|broken|bug|bugs|
        unable|cannot|can't|cant|won't|doesn't|doesnt|
        not\s+working|does\s+not\s+work|issue|problem|
        unreliable|inconsistent|regression|timeout|crash|
        difficult|hard\s+to|struggl\w*|workaround|work\s*around|
        missing|incorrect|wrong|unexpected|invalid|pain|frustrat\w*|
        forget(?:s|ting)?|memory|context\s+loss|permission\s+error
    )\b"""
)

URL_RE = re.compile(r"https?://[^\s<>\]\[\)\(\"']+", re.I)

EXCLUDED_DISCOVERY_DOMAINS = {
    "github.com", "api.github.com", "reddit.com", "www.reddit.com",
    "stackoverflow.com", "stackexchange.com", "api.stackexchange.com",
    "gitlab.com", "news.ycombinator.com", "youtube.com", "www.youtube.com",
    "youtu.be", "x.com", "twitter.com", "linkedin.com", "facebook.com",
    "instagram.com", "t.co", "bit.ly", "arxiv.org", "huggingface.co",
}


def clean_text(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def tokenize(text: str) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z0-9_+.#-]{2,}", text or "")
    out, seen = [], set()
    for word in words:
        key = word.lower().strip(".")
        if len(key) < 4 or key in GENERIC_TERMS or key in seen:
            continue
        seen.add(key)
        out.append(word)
    return out


def compact_query(candidate) -> str:
    pools = [
        tokenize(str(getattr(candidate, "object", "") or "")),
        tokenize(str(getattr(candidate, "failure_mode", "") or "")),
        tokenize(str(getattr(candidate, "task", "") or "")),
        tokenize(
            " ".join([
                str(getattr(candidate, "title", "") or ""),
                str(getattr(candidate, "problem_statement", "") or ""),
            ])
        ),
    ]
    picked, seen = [], set()
    for pool in pools:
        for term in pool:
            key = term.lower()
            if key in seen:
                continue
            seen.add(key)
            picked.append(term)
            if len(picked) >= 3:
                return " ".join(picked)[:120]
    return " ".join(picked)[:120]


def is_direct_problem(text: str) -> bool:
    return bool(PROBLEM_RE.search(clean_text(text)))


def stable_external_id(*parts: Any) -> str:
    raw = "|".join(str(x or "") for x in parts)
    return hashlib.sha256(raw.encode("utf-8", "ignore")).hexdigest()[:40]


def parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(
            timezone.utc
        ).replace(tzinfo=None)
    except Exception:
        return None


async def upsert_external_problem(
    *,
    source_type: str,
    source_key: str,
    external_id: str,
    title: str | None,
    body: str | None,
    url: str | None,
    author: str | None = None,
    published_at: datetime | None = None,
    updated_at: datetime | None = None,
    score: float | None = None,
    matched_candidate_id: int | None = None,
    raw_metadata: dict | None = None,
) -> bool:
    text = f"{title or ''} {body or ''}".strip()
    direct = is_direct_problem(text)
    now = _utc_naive()
    table = ExternalProblemItem.__table__

    async with async_session() as session:
        stmt = pg_insert(table).values(
            source_type=source_type,
            source_key=source_key,
            external_id=str(external_id),
            title=title,
            body=body,
            url=url,
            author=author,
            published_at=published_at,
            updated_at=updated_at,
            score=score,
            is_direct_problem=direct,
            matched_candidate_id=matched_candidate_id,
            raw_metadata=raw_metadata or {},
            last_scraped_at=now,
        ).on_conflict_do_update(
            constraint="uq_external_problem_item",
            set_={
                "title": title,
                "body": body,
                "url": url,
                "author": author,
                "updated_at": updated_at,
                "score": score,
                "is_direct_problem": direct,
                "matched_candidate_id": matched_candidate_id,
                "raw_metadata": raw_metadata or {},
                "last_scraped_at": now,
            },
        )
        await session.execute(stmt)
        await session.commit()
    return direct


async def observe_source(
    *,
    source_type: str,
    source_key: str,
    source_url: str | None,
    origin: str = "discovered",
    evidence_role: str = "DIRECT_PROBLEM",
    seen: int = 0,
    relevant: int = 0,
    direct_problem: int = 0,
    metadata: dict | None = None,
    status_hint: str | None = None,
    error: str | None = None,
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
                status=status_hint or ("ACTIVE" if origin == "seed" else "WATCH"),
                evidence_role=evidence_role,
                records_seen=0,
                relevant_hits=0,
                direct_problem_hits=0,
                yield_score=0.0,
                source_metadata=metadata or {},
            )
            session.add(row)
            await session.flush()

        row.records_seen = int(row.records_seen or 0) + int(seen)
        row.relevant_hits = int(row.relevant_hits or 0) + int(relevant)
        row.direct_problem_hits = int(row.direct_problem_hits or 0) + int(direct_problem)
        row.last_seen_at = now
        if error:
            row.last_error = str(error)[:2000]
        else:
            row.last_success_at = now
            row.last_error = None

        row.yield_score = round(
            float(row.direct_problem_hits or 0) / max(1, int(row.records_seen or 0)),
            4,
        )

        if status_hint:
            row.status = status_hint
        elif row.origin != "seed":
            if int(row.direct_problem_hits or 0) >= 2 and int(row.relevant_hits or 0) >= 2:
                row.status = "ACTIVE"
            elif int(row.records_seen or 0) >= 50 and row.yield_score < 0.02:
                row.status = "WATCH"

        meta = dict(row.source_metadata or {})
        meta.update(metadata or {})
        row.source_metadata = meta
        await session.commit()
        return row.id


async def mark_coverage(
    *,
    case_id: int,
    source_type: str,
    query: str | None,
    hits_seen: int,
    direct_problem_hits: int,
    status: str,
    error: str | None = None,
    metadata: dict | None = None,
):
    """Write one auditable targeted-search attempt.

    SUCCESS_ZERO is intentionally a success: it proves a relevant source was
    actually searched and returned no results. ERROR/RATE_LIMITED never count
    as negative evidence.
    """
    table = RadarSourceCoverage.__table__
    meta_col = table.c["metadata"]
    now = _utc_naive()

    normalized = str(status or "").upper()
    success_statuses = {"COMPLETED", "SUCCESS_HITS", "SUCCESS_ZERO"}
    success = 1 if normalized in success_statuses else 0
    zero = 1 if success and int(hits_seen or 0) == 0 else 0

    async with async_session() as session:
        existing = (await session.execute(
            select(RadarSourceCoverage).where(
                RadarSourceCoverage.case_id == case_id,
                RadarSourceCoverage.source_type == source_type,
            )
        )).scalar_one_or_none()

        old_meta = dict(existing.coverage_metadata or {}) if existing else {}
        old_meta.update(metadata or {})
        old_meta["coverage_truth_version"] = "v4.4a"

        stmt = pg_insert(table).values({
            table.c.case_id: case_id,
            table.c.source_type: source_type,
            table.c.attempt_count: 1,
            table.c.successful_attempts: success,
            table.c.zero_result_attempts: zero,
            table.c.hits_seen: int(hits_seen or 0),
            table.c.direct_problem_hits: int(direct_problem_hits or 0),
            table.c.last_status: normalized,
            table.c.last_query: query,
            table.c.last_attempt_at: now,
            table.c.last_error: error,
            meta_col: old_meta,
        }).on_conflict_do_update(
            constraint="uq_radar_source_coverage",
            set_={
                table.c.attempt_count: table.c.attempt_count + 1,
                table.c.successful_attempts: table.c.successful_attempts + success,
                table.c.zero_result_attempts: table.c.zero_result_attempts + zero,
                table.c.hits_seen: table.c.hits_seen + int(hits_seen or 0),
                table.c.direct_problem_hits: (
                    table.c.direct_problem_hits + int(direct_problem_hits or 0)
                ),
                table.c.last_status: normalized,
                table.c.last_query: query,
                table.c.last_attempt_at: now,
                table.c.last_error: error,
                meta_col: old_meta,
            },
        )
        await session.execute(stmt)
        await session.commit()


def extract_domains(text: str) -> list[str]:
    out, seen = [], set()
    for url in URL_RE.findall(str(text or "")):
        try:
            host = urlsplit(url.rstrip(".,;:!?'")).netloc.lower().split("@")[-1]
            if host.startswith("www."):
                host = host[4:]
            if not host or host in EXCLUDED_DISCOVERY_DOMAINS:
                continue
            if host.endswith(".github.com") or host.endswith(".reddit.com"):
                continue
            if host in seen:
                continue
            seen.add(host)
            out.append(host)
        except Exception:
            continue
    return out


async def robots_allows(client: httpx.AsyncClient, base_url: str, target_url: str) -> bool:
    try:
        robots_url = urljoin(base_url.rstrip("/") + "/", "robots.txt")
        response = await client.get(
            robots_url,
            headers={"User-Agent": USER_AGENT},
            timeout=10.0,
        )
        if response.status_code >= 400:
            return True
        parser = RobotFileParser()
        parser.set_url(robots_url)
        parser.parse(response.text.splitlines())
        return parser.can_fetch(USER_AGENT, target_url)
    except Exception:
        # Fail closed only when we know access is disallowed. Network failure alone
        # should not permanently blacklist a public feed; the adapter will still
        # make one conservative request and honor HTTP errors/rate limits.
        return True
