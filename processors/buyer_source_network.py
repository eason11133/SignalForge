"""Structured Buyer Source Network V1.

Purpose:
Provide named-organization hiring evidence for BUYER_REALITY without relying on
the legacy generic JobListing scraper's broken company field.

Sources:
- Remotive public remote-jobs API (structured company_name + search)
- Arbeitnow public job-board API (structured company_name from ATS-backed jobs)

Design constraints:
- No API keys.
- No LLM calls.
- Bounded requests and 12-hour local cache.
- Source errors never become negative market evidence.
- Named company + strong problem/capability alignment is still required before
  a job can support C05 buyer_exists.
"""

from __future__ import annotations

import asyncio
import html
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

ENGINE_VERSION = "structured-buyer-source-network-v2-hn-coverage"
CACHE_PATH = Path(".radar_runtime/structured_buyer_jobs_v2.json")
CACHE_TTL_HOURS = 12

REMOTIVE_URL = "https://remotive.com/api/remote-jobs"
ARBEITNOW_URL = "https://www.arbeitnow.com/api/job-board-api"
HN_SEARCH_BY_DATE_URL = "https://hn.algolia.com/api/v1/search_by_date"
HN_SEARCH_URL = "https://hn.algolia.com/api/v1/search"

USER_AGENT = (
    "community-mind-mirror/1.0 buyer-research "
    "(evidence-only; no job republishing)"
)


def _clean_html(value: Any) -> str:
    s = str(value or "")
    if not s:
        return ""
    s = re.sub(r"(?is)<script.*?>.*?</script>", " ", s)
    s = re.sub(r"(?is)<style.*?>.*?</style>", " ", s)
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None

    if isinstance(value, (int, float)):
        try:
            # Arbeitnow commonly returns epoch seconds.
            return datetime.fromtimestamp(float(value), tz=timezone.utc).replace(
                tzinfo=None
            )
        except Exception:
            return None

    raw = str(value).strip()
    if not raw:
        return None

    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except Exception:
        return None


def _cache_fresh() -> bool:
    if not CACHE_PATH.exists():
        return False
    try:
        data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        fetched = datetime.fromisoformat(str(data.get("fetched_at")))
        return datetime.utcnow() - fetched < timedelta(hours=CACHE_TTL_HOURS)
    except Exception:
        return False


def _load_cache() -> dict[str, Any] | None:
    if not CACHE_PATH.exists():
        return None
    try:
        data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        return None
    return None


def _write_cache(payload: dict[str, Any]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


async def _fetch_json(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict[str, Any] | None = None,
) -> tuple[Any | None, str | None, int | None]:
    try:
        resp = await client.get(url, params=params)
        status = resp.status_code
        if status != 200:
            return None, f"HTTP_{status}", status
        return resp.json(), None, status
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}", None


def _remotive_rows(payload: Any, query: str) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    jobs = payload.get("jobs")
    if not isinstance(jobs, list):
        return []

    out = []
    for item in jobs:
        if not isinstance(item, dict):
            continue

        company = str(item.get("company_name") or "").strip()
        title = str(item.get("title") or "").strip()
        url = str(item.get("url") or "").strip()
        description = _clean_html(item.get("description"))
        category = str(item.get("category") or "").strip()
        location = str(item.get("candidate_required_location") or "").strip()
        salary = str(item.get("salary") or "").strip()

        if not title or not company:
            continue

        out.append({
            "source": "remotive",
            "external_id": str(item.get("id") or url or title),
            "company": company[:255],
            "title": title,
            "url": url or "https://remotive.com/",
            "published_at": (
                _parse_dt(item.get("publication_date")).isoformat()
                if _parse_dt(item.get("publication_date"))
                else None
            ),
            "text": " ".join(
                x
                for x in (
                    title,
                    company,
                    category,
                    location,
                    salary,
                    description,
                )
                if x
            )[:20000],
            "metadata": {
                "query": query,
                "category": category,
                "location": location,
                "salary": salary,
                "attribution": "Remotive",
            },
        })
    return out


def _arbeitnow_rows(payload: Any, page: int) -> tuple[list[dict[str, Any]], str | None]:
    if not isinstance(payload, dict):
        return [], None

    rows = payload.get("data")
    if not isinstance(rows, list):
        return [], None

    out = []
    for item in rows:
        if not isinstance(item, dict):
            continue

        company = str(item.get("company_name") or "").strip()
        title = str(item.get("title") or "").strip()
        url = str(item.get("url") or "").strip()
        description = _clean_html(item.get("description"))
        location = str(item.get("location") or "").strip()
        tags = item.get("tags")
        job_types = item.get("job_types")

        if not title or not company:
            continue

        tag_text = " ".join(str(x) for x in tags) if isinstance(tags, list) else str(tags or "")
        type_text = (
            " ".join(str(x) for x in job_types)
            if isinstance(job_types, list)
            else str(job_types or "")
        )

        published = _parse_dt(item.get("created_at"))

        out.append({
            "source": "arbeitnow",
            "external_id": str(item.get("slug") or url or title),
            "company": company[:255],
            "title": title,
            "url": url or "https://www.arbeitnow.com/",
            "published_at": published.isoformat() if published else None,
            "text": " ".join(
                x
                for x in (
                    title,
                    company,
                    location,
                    tag_text,
                    type_text,
                    description,
                )
                if x
            )[:20000],
            "metadata": {
                "page": page,
                "location": location,
                "tags": tags,
                "job_types": job_types,
                "attribution": "Arbeitnow",
            },
        })

    next_url = None
    links = payload.get("links")
    if isinstance(links, dict):
        nxt = links.get("next")
        if nxt:
            next_url = str(nxt)

    return out, next_url


def _hn_lines(value: Any) -> list[str]:
    raw = str(value or "")
    if not raw:
        return []
    raw = re.sub(r"(?i)<br\s*/?>", "\n", raw)
    raw = re.sub(r"(?i)</p\s*>", "\n", raw)
    raw = re.sub(r"(?i)<p[^>]*>", "", raw)
    clean = html.unescape(re.sub(r"(?s)<[^>]+>", " ", raw))
    return [
        re.sub(r"\s+", " ", line).strip()
        for line in clean.splitlines()
        if re.sub(r"\s+", " ", line).strip()
    ]


def _hn_company(value: Any) -> str | None:
    lines = _hn_lines(value)
    if not lines:
        return None

    first = lines[0]
    if "|" in first:
        candidate = first.split("|", 1)[0].strip()
    elif " — " in first:
        candidate = first.split(" — ", 1)[0].strip()
    else:
        return None

    candidate = re.sub(r"\s+", " ", candidate).strip(" -–—:")
    low = candidate.lower()

    if not (2 <= len(candidate) <= 100):
        return None
    if len(candidate.split()) > 10:
        return None
    if any(
        low.startswith(prefix)
        for prefix in (
            "we are", "we're", "looking for", "hiring", "remote",
            "http", "ask hn", "email", "apply",
        )
    ):
        return None
    if low in {"remote", "onsite", "hybrid", "company"}:
        return None

    return candidate


def _hn_rows(payload: Any, story_id: str) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    hits = payload.get("hits")
    if not isinstance(hits, list):
        return []

    out = []
    for item in hits:
        if not isinstance(item, dict):
            continue
        raw = item.get("comment_text")
        company = _hn_company(raw)
        if not company:
            continue

        text = " ".join(_hn_lines(raw))
        if len(text) < 40:
            continue

        obj_id = str(item.get("objectID") or "")
        created = _parse_dt(item.get("created_at"))

        out.append({
            "source": "hn_hiring",
            "external_id": obj_id or f"{story_id}:{company}",
            "company": company[:255],
            "title": f"HN Hiring: {company}",
            "url": (
                f"https://news.ycombinator.com/item?id={obj_id}"
                if obj_id
                else f"https://news.ycombinator.com/item?id={story_id}"
            ),
            "published_at": created.isoformat() if created else None,
            "text": text[:20000],
            "metadata": {
                "story_id": story_id,
                "author": item.get("author"),
                "attribution": "Hacker News / Algolia",
            },
        })
    return out


def _dedupe(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    out = []
    for row in rows:
        key = (
            str(row.get("source") or ""),
            str(row.get("external_id") or ""),
            str(row.get("company") or "").lower(),
            str(row.get("title") or "").lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


async def fetch_structured_buyer_jobs(
    *,
    force: bool = False,
) -> dict[str, Any]:
    if not force and _cache_fresh():
        cached = _load_cache() or {}
        cached["cache_hit"] = True
        return cached

    rows: list[dict[str, Any]] = []
    source_status: dict[str, Any] = {}
    request_count = 0

    timeout = httpx.Timeout(30.0, connect=10.0)
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }

    async with httpx.AsyncClient(
        timeout=timeout,
        headers=headers,
        follow_redirects=True,
    ) as client:
        # Remotive explicitly recommends no more than a few requests per day.
        # Two broad queries + 12h cache keeps this at <=4/day in normal use.
        remotive_total = 0
        remotive_errors = []
        for query in ("AI", "machine learning"):
            payload, error, status = await _fetch_json(
                client,
                REMOTIVE_URL,
                params={"search": query, "limit": 500},
            )
            request_count += 1
            if error:
                remotive_errors.append({"query": query, "error": error})
            else:
                found = _remotive_rows(payload, query)
                remotive_total += len(found)
                rows.extend(found)

            # Be polite even though this is far below documented burst limits.
            await asyncio.sleep(1.0)

        source_status["remotive"] = {
            "status": "PASS" if remotive_total else (
                "ERROR" if remotive_errors else "SUCCESS_ZERO"
            ),
            "rows": remotive_total,
            "errors": remotive_errors,
        }

        # Arbeitnow is paginated. Five pages keeps the first pass bounded.
        arbeit_total = 0
        arbeit_errors = []
        next_url = ARBEITNOW_URL
        for page in range(1, 13):
            payload, error, status = await _fetch_json(
                client,
                next_url if page > 1 and next_url else ARBEITNOW_URL,
                params=None if page > 1 and next_url else {"page": page},
            )
            request_count += 1

            if error:
                arbeit_errors.append({"page": page, "error": error})
                break

            found, parsed_next = _arbeitnow_rows(payload, page)
            arbeit_total += len(found)
            rows.extend(found)

            if not parsed_next:
                break
            next_url = parsed_next
            await asyncio.sleep(0.5)

        source_status["arbeitnow"] = {
            "status": "PASS" if arbeit_total else (
                "ERROR" if arbeit_errors else "SUCCESS_ZERO"
            ),
            "rows": arbeit_total,
            "errors": arbeit_errors,
        }

        # Latest monthly HN "Who is hiring?" thread. Hiring comments are
        # direct public budget-allocation signals when a company is named.
        hn_rows = []
        hn_errors = []
        story_payload, error, _ = await _fetch_json(
            client,
            HN_SEARCH_BY_DATE_URL,
            params={
                "query": "Who is hiring?",
                "tags": "story",
                "hitsPerPage": 20,
            },
        )
        request_count += 1

        story_id = None
        if error:
            hn_errors.append({"stage": "story_search", "error": error})
        elif isinstance(story_payload, dict):
            for hit in story_payload.get("hits", []) or []:
                title = str(hit.get("title") or "").lower()
                if "who is hiring" in title:
                    story_id = str(hit.get("objectID") or "")
                    if story_id:
                        break

        if story_id:
            comments_payload, error, _ = await _fetch_json(
                client,
                HN_SEARCH_URL,
                params={
                    "tags": f"comment,story_{story_id}",
                    "hitsPerPage": 1000,
                },
            )
            request_count += 1
            if error:
                hn_errors.append({
                    "stage": "comment_search",
                    "error": error,
                    "story_id": story_id,
                })
            else:
                hn_rows = _hn_rows(comments_payload, story_id)
                rows.extend(hn_rows)
        elif not hn_errors:
            hn_errors.append({
                "stage": "story_search",
                "error": "NO_RECENT_HIRING_THREAD_FOUND",
            })

        source_status["hn_hiring"] = {
            "status": "PASS" if hn_rows else (
                "ERROR" if hn_errors else "SUCCESS_ZERO"
            ),
            "rows": len(hn_rows),
            "errors": hn_errors,
            "story_id": story_id,
        }

    rows = _dedupe(rows)

    payload = {
        "engine_version": ENGINE_VERSION,
        "fetched_at": datetime.utcnow().isoformat(timespec="seconds"),
        "cache_hit": False,
        "request_count": request_count,
        "source_status": source_status,
        "rows": rows,
        "row_count": len(rows),
    }
    _write_cache(payload)
    return payload
