from __future__ import annotations

import html
import ipaddress
import json
import os
import re
import socket
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

from processors.signalforge_founder_query_contracts import classify_source_profile, compile_source_query, semantic_terms
from processors.signalforge_source_registry import (
    SOURCE_REGISTRY,
    configured_list,
    observation_families_for_source,
    public_feed_configs,
    discourse_site_configs,
    github_discussion_repos,
    mastodon_instance_configs,
    lemmy_instance_configs,
    stackexchange_site_configs,
    ashby_board_names,
    source_runtime_state,
)

ENGINE_VERSION = "signalforge-source-adapters-founder-observation-quality-repair-v1"
DEFAULT_TIMEOUT = 6.0
MAX_BYTES = 2_000_000

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


class SourceAdapterError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, category: str = "TRANSPORT"):
        super().__init__(message)
        self.status_code = status_code
        self.category = category


def _clean(value: Any) -> str:
    text = html.unescape(str(value or ""))
    return _WS_RE.sub(" ", _TAG_RE.sub(" ", text)).strip()


def _target_observation_families(source_id: str, query: str) -> list[str]:
    profile = str(classify_source_profile(query).get("source_profile") or "UNCLASSIFIED")
    if source_id == "BRAVE_WEB":
        mapping = {
            "AGENCY_SERVICES": ["AGENCY_SERVICE_PAGES", "PRODUCT_DISCOVERY_STRATEGY_PAGES", "RESEARCH_TOOL_REVIEWS"],
            "NONPROFIT_OPERATIONS": ["NONPROFIT_SERVICE_PAGES", "ASSOCIATION_SOFTWARE_REVIEWS"],
            "EDUCATION_EXAM": ["EDTECH_REVIEWS"],
            "ECOMMERCE_OPERATOR": ["ECOMMERCE_APP_REVIEWS", "SHOPIFY_ECOSYSTEM"],
        }
        return mapping.get(profile, ["GENERAL_WEB"])
    if source_id in {"THREADS_API", "YOUTUBE_DATA_API", "BLUESKY_PUBLIC_SEARCH", "X_RECENT_SEARCH", "MASTODON_SEARCH", "LEMMY_PUBLIC"}:
        mapping = {
            "AGENCY_SERVICES": ["FOUNDER_COMMUNITIES", "AGENCY_COMMUNITIES"],
            "NONPROFIT_OPERATIONS": ["NONPROFIT_COMMUNITIES"],
            "EDUCATION_EXAM": ["STUDENT_COMMUNITIES"],
            "ECOMMERCE_OPERATOR": ["MERCHANT_COMMUNITIES"],
            "DEVELOPER_TOOLING": ["DEVELOPER_COMMUNITIES"],
        }
        return mapping.get(profile, ["GENERAL_COMMUNITIES"])
    return observation_families_for_source(source_id)


def _finalize_result(result: dict[str, Any]) -> dict[str, Any]:
    obs = list(dict.fromkeys(str(x).upper() for x in (result.get("observation_source_families") or []) if str(x).strip()))
    result["observation_source_families"] = obs
    for trace in result.get("traces") or []:
        if not isinstance(trace, dict):
            continue
        metadata = trace.get("metadata") if isinstance(trace.get("metadata"), dict) else {}
        # Per-feed explicit observation families are more specific than adapter defaults.
        current = list(metadata.get("observation_source_families") or [])
        metadata["observation_source_families"] = current or obs
        trace["metadata"] = metadata
        trace["observation_source_families"] = list(metadata["observation_source_families"])
        trace["source_family"] = str(result.get("source_family") or trace.get("source_family") or "")
    result["count"] = len(result.get("traces") or [])
    return result


def _base_result(source_id: str, query: str) -> dict[str, Any]:
    spec = SOURCE_REGISTRY[source_id]
    return {
        "source": source_id,
        "source_family": spec.source_family,
        "observation_source_families": _target_observation_families(source_id, query),
        "status": "SUCCESS",
        "query": query,
        "count": 0,
        "traces": [],
        "transport": {},
        "discovery_scope": spec.discovery_scope,
        "absence_adequacy": spec.absence_adequacy,
        "truth_boundary": "SOURCE_ADAPTER_OUTPUT_IS_UNVALIDATED_SEARCH_TRACE_ONLY",
    }


def _request_bytes(
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    max_bytes: int = MAX_BYTES,
) -> tuple[bytes, dict[str, Any]]:
    req_headers = {
        "User-Agent": "SignalForge-Source-Expansion/1.0",
        "Accept": "application/json,text/xml,application/xml,application/atom+xml,application/rss+xml,text/plain;q=0.8,*/*;q=0.2",
    }
    if headers:
        req_headers.update(dict(headers))
    req = Request(url, headers=req_headers, method="GET")
    started = time.perf_counter()
    try:
        with urlopen(req, timeout=timeout) as response:
            body = response.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise SourceAdapterError("response exceeded size cap", category="SIZE_LIMIT")
            return body, {
                "status_code": int(getattr(response, "status", 200) or 200),
                "elapsed_ms": round((time.perf_counter() - started) * 1000),
                "content_type": response.headers.get("content-type"),
                "rate_remaining": response.headers.get("x-ratelimit-remaining"),
                "rate_reset": response.headers.get("x-ratelimit-reset"),
            }
    except HTTPError as exc:
        raise SourceAdapterError(f"HTTP {exc.code}", status_code=int(exc.code), category="HTTP") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise SourceAdapterError(f"{type(exc).__name__}: {exc}", category="NETWORK") from exc


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # pragma: no cover - urllib hook
        return None


def _request_public_bytes(
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    max_bytes: int = MAX_BYTES,
    max_redirects: int = 3,
) -> tuple[bytes, dict[str, Any]]:
    """SSRF-hardened public fetch: validate the initial URL and every redirect target."""
    current = url
    redirects: list[str] = []
    opener = build_opener(_NoRedirect())
    for _ in range(max_redirects + 1):
        _assert_public_http_url(current)
        req_headers = {
            "User-Agent": "SignalForge-Source-Expansion/1.0",
            "Accept": "application/rss+xml,application/atom+xml,text/xml,application/xml,text/plain;q=0.8,*/*;q=0.2",
        }
        if headers:
            req_headers.update(dict(headers))
        req = Request(current, headers=req_headers, method="GET")
        started = time.perf_counter()
        try:
            with opener.open(req, timeout=timeout) as response:
                body = response.read(max_bytes + 1)
                if len(body) > max_bytes:
                    raise SourceAdapterError("response exceeded size cap", category="SIZE_LIMIT")
                return body, {
                    "status_code": int(getattr(response, "status", 200) or 200),
                    "elapsed_ms": round((time.perf_counter() - started) * 1000),
                    "content_type": response.headers.get("content-type"),
                    "final_url": current,
                    "redirects": redirects,
                }
        except HTTPError as exc:
            if int(exc.code) in {301, 302, 303, 307, 308}:
                location = exc.headers.get("Location") if exc.headers else None
                if not location:
                    raise SourceAdapterError(f"redirect HTTP {exc.code} without Location", status_code=int(exc.code), category="HTTP") from exc
                nxt = urljoin(current, location)
                _assert_public_http_url(nxt)
                redirects.append(nxt)
                current = nxt
                continue
            raise SourceAdapterError(f"HTTP {exc.code}", status_code=int(exc.code), category="HTTP") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise SourceAdapterError(f"{type(exc).__name__}: {exc}", category="NETWORK") from exc
    raise SourceAdapterError("too many redirects", category="SECURITY")


def _request_json(url: str, *, headers: Mapping[str, str] | None = None, timeout: float = DEFAULT_TIMEOUT) -> tuple[Any, dict[str, Any]]:
    body, meta = _request_bytes(url, headers=headers, timeout=timeout)
    try:
        return json.loads(body.decode("utf-8", errors="replace")), meta
    except json.JSONDecodeError as exc:
        raise SourceAdapterError(f"invalid JSON: {exc}", category="PARSE") from exc


def _request_json_bounded_retry(
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    attempts: int = 2,
) -> tuple[Any, dict[str, Any]]:
    """Retry only transient NETWORK failures, with a strict attempt cap.

    HTTP/auth/policy rejections are never retried or hidden. This is for fragile
    handshakes such as GDELT, not a way to turn unavailable sources into success.
    """
    attempts = max(1, min(int(attempts), 2))
    last: SourceAdapterError | None = None
    for attempt in range(1, attempts + 1):
        try:
            data, meta = _request_json(url, headers=headers, timeout=timeout)
            meta = dict(meta)
            meta["attempts"] = attempt
            meta["retry_policy"] = "NETWORK_ONLY_MAX_2"
            return data, meta
        except SourceAdapterError as exc:
            last = exc
            if exc.category != "NETWORK" or attempt >= attempts:
                raise
            time.sleep(0.15)
    assert last is not None
    raise last


def _request_json_post(
    url: str,
    payload: Mapping[str, Any],
    *,
    headers: Mapping[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> tuple[Any, dict[str, Any]]:
    req_headers = {
        "User-Agent": "SignalForge-Source-Expansion/1.0",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if headers:
        req_headers.update(dict(headers))
    data = json.dumps(dict(payload), separators=(",", ":")).encode("utf-8")
    req = Request(url, data=data, headers=req_headers, method="POST")
    started = time.perf_counter()
    try:
        with urlopen(req, timeout=timeout) as response:
            raw = response.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise SourceAdapterError("response exceeded size cap", category="SIZE_LIMIT")
            meta = {
                "status_code": int(getattr(response, "status", 200)),
                "elapsed_ms": round((time.perf_counter() - started) * 1000),
            }
    except HTTPError as exc:
        raise SourceAdapterError(f"HTTP {exc.code}", status_code=int(exc.code), category="HTTP") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise SourceAdapterError(f"{type(exc).__name__}: {exc}", category="NETWORK") from exc
    try:
        return json.loads(raw.decode("utf-8", errors="replace")), meta
    except json.JSONDecodeError as exc:
        raise SourceAdapterError(f"invalid JSON: {exc}", category="PARSE") from exc


def _trace(
    *,
    source: str,
    kind: str,
    content_unit: str,
    title: str,
    excerpt: str = "",
    url: str | None = None,
    author: str | None = None,
    created_at: str | None = None,
    metadata: Mapping[str, Any] | None = None,
    observation_families: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "source": source,
        "kind": kind,
        "content_unit": content_unit,
        "title": _clean(title)[:300],
        "excerpt": _clean(excerpt)[:1400],
        "url": url,
        "author": author,
        "created_at": created_at,
        "metadata": {
            **dict(metadata or {}),
            "observation_source_families": list(observation_families or []),
        },
        "truth_status": "UNVALIDATED_SEARCH_TRACE",
    }


def search_brave(query: str) -> dict[str, Any]:
    source_id = "BRAVE_WEB"
    state = source_runtime_state(source_id)
    if state["runtime_state"] != "READY":
        raise SourceAdapterError("BRAVE_SEARCH_API_KEY not configured", category="CONFIG")
    compiled = compile_source_query(query, source_id)
    final = str(compiled.get("final_query") or "").strip()
    if not final:
        raise SourceAdapterError("compiled query is empty", category="QUERY")
    params = urlencode({"q": final, "count": 12, "search_lang": "en", "safesearch": "moderate"})
    url = f"https://api.search.brave.com/res/v1/web/search?{params}"
    data, meta = _request_json(url, headers={"X-Subscription-Token": os.environ["BRAVE_SEARCH_API_KEY"], "Accept": "application/json"})
    result = _base_result(source_id, query)
    result["final_search_query_used"] = final
    result["query_contract"] = compiled
    result["transport"] = meta
    rows = (data or {}).get("web", {}).get("results", []) if isinstance(data, Mapping) else []
    for item in rows[:12]:
        if not isinstance(item, Mapping):
            continue
        result["traces"].append(_trace(
            source=source_id, kind="WEB_PAGE", content_unit="WEB_PAGE",
            title=item.get("title") or "Web result", excerpt=item.get("description") or "",
            url=item.get("url"), metadata={"age": item.get("age"), "profile": item.get("profile")},
        ))
    return _finalize_result(result)


def search_gdelt(query: str) -> dict[str, Any]:
    source_id = "GDELT_DOC"
    compiled = compile_source_query(query, source_id)
    final = str(compiled.get("final_query") or "").strip()
    if not final:
        raise SourceAdapterError("compiled query is empty", category="QUERY")
    params = urlencode({"query": final, "mode": "ArtList", "maxrecords": 20, "format": "json", "sort": "HybridRel"})
    url = f"https://api.gdeltproject.org/api/v2/doc/doc?{params}"
    data, meta = _request_json_bounded_retry(url, attempts=2)
    result = _base_result(source_id, query)
    result["final_search_query_used"] = final
    result["query_contract"] = compiled
    result["transport"] = meta
    rows = (data or {}).get("articles", []) if isinstance(data, Mapping) else []
    for item in rows[:20]:
        if not isinstance(item, Mapping):
            continue
        result["traces"].append(_trace(
            source=source_id, kind="NEWS", content_unit="NEWS_ARTICLE_INDEX",
            title=item.get("title") or "News article", excerpt="",
            url=item.get("url"), created_at=item.get("seendate"),
            metadata={"domain": item.get("domain"), "language": item.get("language"), "sourcecountry": item.get("sourcecountry")},
        ))
    return _finalize_result(result)


def search_youtube(query: str) -> dict[str, Any]:
    source_id = "YOUTUBE_DATA_API"
    state = source_runtime_state(source_id)
    if state["runtime_state"] != "READY":
        raise SourceAdapterError("YOUTUBE_API_KEY not configured", category="CONFIG")
    key = os.environ["YOUTUBE_API_KEY"]
    compiled = compile_source_query(query, source_id)
    final = str(compiled.get("final_query") or "").strip()
    if not final:
        raise SourceAdapterError("compiled query is empty", category="QUERY")
    params = urlencode({"part": "snippet", "type": "video", "q": final, "maxResults": 6, "key": key})
    data, meta = _request_json(f"https://www.googleapis.com/youtube/v3/search?{params}")
    result = _base_result(source_id, query)
    result["final_search_query_used"] = final
    result["query_contract"] = compiled
    transport_children: list[dict[str, Any]] = [meta]
    max_reply_reads = max(0, min(_int_env("SIGNALFORGE_YOUTUBE_MAX_REPLY_READS_PER_VIDEO", 60), 200))
    max_reply_pages = max(0, min(_int_env("SIGNALFORGE_YOUTUBE_MAX_REPLY_PAGES_PER_THREAD", 2), 5))
    videos = (data or {}).get("items", []) if isinstance(data, Mapping) else []
    for item in videos[:6]:
        if not isinstance(item, Mapping):
            continue
        vid = ((item.get("id") or {}).get("videoId") if isinstance(item.get("id"), Mapping) else None)
        snippet = item.get("snippet") if isinstance(item.get("snippet"), Mapping) else {}
        if not vid:
            continue
        result["traces"].append(_trace(
            source=source_id, kind="VIDEO", content_unit="VIDEO",
            title=snippet.get("title") or "YouTube video", excerpt=snippet.get("description") or "",
            url=f"https://www.youtube.com/watch?v={vid}", author=snippet.get("channelTitle"), created_at=snippet.get("publishedAt"),
            metadata={"video_id": vid, "channel_id": snippet.get("channelId"), "independence_group_key": f"youtube:{vid}"},
        ))
        cparams = urlencode({"part": "snippet,replies", "videoId": vid, "maxResults": 20, "order": "relevance", "textFormat": "plainText", "key": key})
        try:
            cdata, cmeta = _request_json(f"https://www.googleapis.com/youtube/v3/commentThreads?{cparams}")
            transport_children.append({"video_id": vid, "endpoint": "commentThreads.list", **cmeta})
        except SourceAdapterError as exc:
            transport_children.append({"status_code": exc.status_code, "error": str(exc), "video_id": vid, "endpoint": "commentThreads.list"})
            continue
        reply_reads_for_video = 0
        for thread in ((cdata or {}).get("items", []) if isinstance(cdata, Mapping) else [])[:20]:
            if not isinstance(thread, Mapping):
                continue
            sn = thread.get("snippet") if isinstance(thread.get("snippet"), Mapping) else {}
            top = sn.get("topLevelComment") if isinstance(sn.get("topLevelComment"), Mapping) else {}
            top_sn = top.get("snippet") if isinstance(top.get("snippet"), Mapping) else {}
            cid = str(top.get("id") or "")
            group = f"youtube:{vid}:comment:{cid}" if cid else f"youtube:{vid}"
            result["traces"].append(_trace(
                source=source_id, kind="DISCUSSION", content_unit="TOP_LEVEL_COMMENT",
                title=f"Comment on {snippet.get('title') or 'YouTube video'}", excerpt=top_sn.get("textDisplay") or top_sn.get("textOriginal") or "",
                url=f"https://www.youtube.com/watch?v={vid}&lc={cid}" if cid else f"https://www.youtube.com/watch?v={vid}",
                author=top_sn.get("authorDisplayName"), created_at=top_sn.get("publishedAt"),
                metadata={"video_id": vid, "comment_id": cid or None, "like_count": top_sn.get("likeCount"), "independence_group_key": group},
            ))
            inline_replies = ((thread.get("replies") or {}).get("comments") if isinstance(thread.get("replies"), Mapping) else []) or []
            total_reply_count = int(sn.get("totalReplyCount") or 0)
            reply_map: dict[str, Mapping[str, Any]] = {}
            for reply in inline_replies:
                if isinstance(reply, Mapping):
                    rid = str(reply.get("id") or "")
                    if rid:
                        reply_map[rid] = reply

            # commentThreads.list may include only a subset of replies. If it tells us
            # more replies exist, use comments.list(parentId=...) with hard read/page caps.
            if cid and total_reply_count > len(reply_map) and max_reply_reads > reply_reads_for_video and max_reply_pages > 0:
                page_token: str | None = None
                pages = 0
                while pages < max_reply_pages and reply_reads_for_video < max_reply_reads:
                    remaining = max_reply_reads - reply_reads_for_video
                    rparams_obj = {
                        "part": "snippet",
                        "parentId": cid,
                        "maxResults": min(100, remaining),
                        "textFormat": "plainText",
                        "key": key,
                    }
                    if page_token:
                        rparams_obj["pageToken"] = page_token
                    try:
                        rdata, rmeta = _request_json(f"https://www.googleapis.com/youtube/v3/comments?{urlencode(rparams_obj)}")
                        transport_children.append({"video_id": vid, "comment_id": cid, "endpoint": "comments.list", **rmeta})
                    except SourceAdapterError as exc:
                        transport_children.append({"video_id": vid, "comment_id": cid, "endpoint": "comments.list", "status_code": exc.status_code, "error": str(exc)})
                        break
                    rows = (rdata or {}).get("items", []) if isinstance(rdata, Mapping) else []
                    for reply in rows:
                        if not isinstance(reply, Mapping):
                            continue
                        rid = str(reply.get("id") or "")
                        if rid:
                            reply_map[rid] = reply
                    reply_reads_for_video += len(rows)
                    pages += 1
                    page_token = str((rdata or {}).get("nextPageToken") or "") if isinstance(rdata, Mapping) else ""
                    if not page_token or not rows or len(reply_map) >= total_reply_count:
                        break

            for reply in list(reply_map.values())[:max_reply_reads if max_reply_reads else len(reply_map)]:
                rs = reply.get("snippet") if isinstance(reply.get("snippet"), Mapping) else {}
                result["traces"].append(_trace(
                    source=source_id, kind="DISCUSSION", content_unit="COMMENT_REPLY",
                    title=f"Reply on {snippet.get('title') or 'YouTube video'}", excerpt=rs.get("textDisplay") or rs.get("textOriginal") or "",
                    url=f"https://www.youtube.com/watch?v={vid}&lc={cid}" if cid else f"https://www.youtube.com/watch?v={vid}",
                    author=rs.get("authorDisplayName"), created_at=rs.get("publishedAt"),
                    metadata={
                        "video_id": vid, "comment_id": reply.get("id"), "parent_id": rs.get("parentId") or cid,
                        "like_count": rs.get("likeCount"), "independence_group_key": group,
                    },
                ))
    result["transport"] = {
        "search": meta,
        "children": transport_children,
        "reply_depth_contract": {
            "comment_threads_may_be_partial": True,
            "comments_list_parent_id_used_when_needed": True,
            "max_reply_reads_per_video": max_reply_reads,
            "max_reply_pages_per_thread": max_reply_pages,
        },
        "quota_note": "search.list, commentThreads.list, and comments.list are separately quota-governed",
    }
    return _finalize_result(result)

def search_threads(query: str) -> dict[str, Any]:
    source_id = "THREADS_API"
    state = source_runtime_state(source_id)
    if state["runtime_state"] != "READY":
        raise SourceAdapterError("THREADS_ACCESS_TOKEN not configured", category="CONFIG")
    token = os.environ["THREADS_ACCESS_TOKEN"]
    compiled = compile_source_query(query, source_id)
    final = str(compiled.get("final_query") or "").strip()
    if not final:
        raise SourceAdapterError("compiled query is empty", category="QUERY")
    fields = "id,text,timestamp,permalink,username,has_replies,is_quote_post,link_attachment_url"
    params = urlencode({"q": final, "search_type": "TOP", "fields": fields, "limit": 20})
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    data, meta = _request_json(f"https://graph.threads.net/keyword_search?{params}", headers=headers)
    result = _base_result(source_id, query)
    result["final_search_query_used"] = final
    result["query_contract"] = compiled
    child_meta: list[dict[str, Any]] = []
    rows = (data or {}).get("data", []) if isinstance(data, Mapping) else []
    for item in rows[:20]:
        if not isinstance(item, Mapping):
            continue
        tid = str(item.get("id") or "")
        result["traces"].append(_trace(
            source=source_id, kind="DISCUSSION", content_unit="POST",
            title=f"Threads post by @{item.get('username') or 'user'}", excerpt=item.get("text") or "",
            url=item.get("permalink"), author=item.get("username"), created_at=item.get("timestamp"),
            metadata={"thread_id": tid, "is_quote_post": item.get("is_quote_post"), "link_attachment_url": item.get("link_attachment_url")},
        ))
        if tid and item.get("has_replies"):
            rparams = urlencode({"fields": "id,text,timestamp,permalink,username,has_replies", "reverse": "false", "limit": 20})
            try:
                rdata, rmeta = _request_json(f"https://graph.threads.net/{quote(tid)}/replies?{rparams}", headers=headers)
                child_meta.append(rmeta)
            except SourceAdapterError as exc:
                child_meta.append({"status_code": exc.status_code, "error": str(exc), "thread_id": tid})
                continue
            for reply in ((rdata or {}).get("data", []) if isinstance(rdata, Mapping) else [])[:20]:
                if not isinstance(reply, Mapping):
                    continue
                result["traces"].append(_trace(
                    source=source_id, kind="DISCUSSION", content_unit="REPLY",
                    title=f"Threads reply by @{reply.get('username') or 'user'}", excerpt=reply.get("text") or "",
                    url=reply.get("permalink") or item.get("permalink"), author=reply.get("username"), created_at=reply.get("timestamp"),
                    metadata={"thread_id": tid, "reply_id": reply.get("id")},
                ))
    result["transport"] = {"search": meta, "reply_calls": child_meta}
    return _finalize_result(result)


def _query_overlap_score(query: str, text: str) -> int:
    q = {x.lower() for x in semantic_terms(query, include_lens_aliases=False)}
    t = {x.lower() for x in semantic_terms(text, include_lens_aliases=False)}
    return len(q & t)


def search_greenhouse_jobs(query: str) -> dict[str, Any]:
    source_id = "GREENHOUSE_PUBLIC_JOBS"
    boards = configured_list("SIGNALFORGE_GREENHOUSE_BOARDS")
    if not boards:
        raise SourceAdapterError("SIGNALFORGE_GREENHOUSE_BOARDS not configured", category="CONFIG")
    result = _base_result(source_id, query)
    transport: list[dict[str, Any]] = []
    candidates: list[tuple[int, dict[str, Any]]] = []
    for board in boards[:20]:
        url = f"https://boards-api.greenhouse.io/v1/boards/{quote(board, safe='')}/jobs?content=true"
        try:
            data, meta = _request_json(url)
            transport.append({"board": board, **meta})
        except SourceAdapterError as exc:
            transport.append({"board": board, "status_code": exc.status_code, "error": str(exc)})
            continue
        for job in ((data or {}).get("jobs", []) if isinstance(data, Mapping) else []):
            if not isinstance(job, Mapping):
                continue
            text = f"{job.get('title')} {job.get('content')} {((job.get('location') or {}).get('name') if isinstance(job.get('location'), Mapping) else '')}"
            score = _query_overlap_score(query, text)
            if score:
                candidates.append((score, {"board": board, **job}))
    for score, job in sorted(candidates, key=lambda x: x[0], reverse=True)[:20]:
        result["traces"].append(_trace(
            source=source_id, kind="JOB", content_unit="JOB_POST",
            title=job.get("title") or "Greenhouse job", excerpt=job.get("content") or "",
            url=job.get("absolute_url"), created_at=job.get("updated_at"),
            metadata={"board": job.get("board"), "job_id": job.get("id"), "location": ((job.get("location") or {}).get("name") if isinstance(job.get("location"), Mapping) else None), "query_overlap_score": score},
        ))
    result["transport"] = {"boards": transport}
    return _finalize_result(result)


def search_lever_jobs(query: str) -> dict[str, Any]:
    source_id = "LEVER_PUBLIC_JOBS"
    sites = configured_list("SIGNALFORGE_LEVER_SITES")
    if not sites:
        raise SourceAdapterError("SIGNALFORGE_LEVER_SITES not configured", category="CONFIG")
    result = _base_result(source_id, query)
    transport: list[dict[str, Any]] = []
    candidates: list[tuple[int, dict[str, Any]]] = []
    for site in sites[:20]:
        url = f"https://api.lever.co/v0/postings/{quote(site, safe='')}?mode=json&limit=200"
        try:
            data, meta = _request_json(url)
            transport.append({"site": site, **meta})
        except SourceAdapterError as exc:
            transport.append({"site": site, "status_code": exc.status_code, "error": str(exc)})
            continue
        rows = data if isinstance(data, list) else []
        for job in rows:
            if not isinstance(job, Mapping):
                continue
            text = f"{job.get('text')} {job.get('descriptionPlain')} {job.get('additionalPlain')} {((job.get('categories') or {}).get('team') if isinstance(job.get('categories'), Mapping) else '')}"
            score = _query_overlap_score(query, text)
            if score:
                candidates.append((score, {"site": site, **job}))
    for score, job in sorted(candidates, key=lambda x: x[0], reverse=True)[:20]:
        cats = job.get("categories") if isinstance(job.get("categories"), Mapping) else {}
        result["traces"].append(_trace(
            source=source_id, kind="JOB", content_unit="JOB_POST",
            title=job.get("text") or "Lever job", excerpt=job.get("descriptionPlain") or job.get("description") or "",
            url=job.get("hostedUrl") or job.get("applyUrl"), created_at=None,
            metadata={"site": job.get("site"), "posting_id": job.get("id"), "team": cats.get("team"), "location": cats.get("location"), "commitment": cats.get("commitment"), "query_overlap_score": score},
        ))
    result["transport"] = {"sites": transport}
    return _finalize_result(result)


def _assert_public_http_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise SourceAdapterError("feed URL must use http(s)", category="SECURITY")
    if not parsed.hostname or parsed.username or parsed.password:
        raise SourceAdapterError("feed URL must have a public hostname and no embedded credentials", category="SECURITY")
    host = parsed.hostname
    if host.lower() in {"localhost", "localhost.localdomain"}:
        raise SourceAdapterError("localhost is forbidden", category="SECURITY")
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise SourceAdapterError(f"DNS resolution failed: {exc}", category="NETWORK") from exc
    for info in infos:
        addr = info[4][0]
        ip = ipaddress.ip_address(addr.split("%", 1)[0])
        if not ip.is_global:
            raise SourceAdapterError(f"non-public feed IP forbidden: {ip}", category="SECURITY")


def _rss_text(node: ET.Element, names: tuple[str, ...]) -> str:
    for child in list(node):
        tag = child.tag.split("}")[-1].lower()
        if tag in names:
            return _clean("".join(child.itertext()))
    return ""


def search_rss_feeds(query: str) -> dict[str, Any]:
    source_id = "RSS_ATOM"
    feeds = public_feed_configs()
    if not feeds:
        raise SourceAdapterError("SIGNALFORGE_PUBLIC_FEEDS not configured", category="CONFIG")
    result = _base_result(source_id, query)
    transports: list[dict[str, Any]] = []
    candidates: list[tuple[int, dict[str, Any]]] = []
    for cfg in feeds:
        url = cfg["url"]
        _assert_public_http_url(url)
        try:
            body, meta = _request_public_bytes(url, headers={"Accept": "application/rss+xml,application/atom+xml,text/xml,application/xml"}, max_bytes=1_500_000)
            transports.append({"url": url, **meta})
            root = ET.fromstring(body)
        except (SourceAdapterError, ET.ParseError) as exc:
            transports.append({"url": url, "error": str(exc)})
            continue
        entries = [x for x in root.iter() if x.tag.split("}")[-1].lower() in {"item", "entry"}]
        for entry in entries[:100]:
            title = _rss_text(entry, ("title",))
            summary = _rss_text(entry, ("description", "summary", "content"))
            link = _rss_text(entry, ("link",))
            if not link:
                for child in list(entry):
                    if child.tag.split("}")[-1].lower() == "link" and child.attrib.get("href"):
                        link = child.attrib["href"]
                        break
            if link:
                link = urljoin(url, link)
            score = _query_overlap_score(query, f"{title} {summary}")
            if score:
                candidates.append((score, {"title": title, "summary": summary, "link": link, "feed": url, "cfg": cfg}))
    for score, item in sorted(candidates, key=lambda x: x[0], reverse=True)[:30]:
        obs = list(item["cfg"].get("observation_families") or [])
        result["traces"].append(_trace(
            source=source_id, kind="DISCUSSION", content_unit="FEED_ITEM",
            title=item["title"] or "Feed item", excerpt=item["summary"], url=item["link"],
            metadata={"feed_url": item["feed"], "query_overlap_score": score}, observation_families=obs,
        ))
    result["count"] = len(result["traces"])
    # RSS observations are per-config; union the configured families so source-fit can see them.
    union: list[str] = []
    for cfg in feeds:
        union.extend(cfg.get("observation_families") or [])
    result["observation_source_families"] = list(dict.fromkeys(str(x).upper() for x in union if str(x).strip()))
    result["transport"] = {"feeds": transports}
    return _finalize_result(result)



def _bsky_web_url(uri: str, handle: str | None = None) -> str | None:
    raw = str(uri or "")
    if not raw.startswith("at://"):
        return None
    parts = raw[5:].split("/")
    if len(parts) < 3:
        return None
    repo, collection, rkey = parts[0], parts[1], parts[2]
    if collection != "app.bsky.feed.post":
        return None
    actor = handle or repo
    return f"https://bsky.app/profile/{quote(actor, safe='.@:-')}/post/{quote(rkey, safe='')}"


def _walk_bsky_replies(node: Mapping[str, Any], *, parent_uri: str | None = None, limit: int = 16) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    stack = list((node.get("replies") or []))[:limit]
    while stack and len(out) < limit:
        item = stack.pop(0)
        if not isinstance(item, Mapping):
            continue
        post = item.get("post") if isinstance(item.get("post"), Mapping) else {}
        record = post.get("record") if isinstance(post.get("record"), Mapping) else {}
        author = post.get("author") if isinstance(post.get("author"), Mapping) else {}
        uri = str(post.get("uri") or "")
        out.append({
            "uri": uri,
            "text": record.get("text") or "",
            "created_at": record.get("createdAt"),
            "handle": author.get("handle"),
            "display_name": author.get("displayName"),
            "url": _bsky_web_url(uri, author.get("handle")),
            "reply_count": post.get("replyCount"),
            "like_count": post.get("likeCount"),
            "parent_uri": parent_uri,
        })
        for child in (item.get("replies") or []):
            if isinstance(child, Mapping) and len(stack) + len(out) < limit:
                stack.append(child)
    return out


def search_bluesky(query: str) -> dict[str, Any]:
    source_id = "BLUESKY_PUBLIC_SEARCH"
    compiled = compile_source_query(query, source_id)
    final = str(compiled.get("final_query") or "").strip()
    if not final:
        raise SourceAdapterError("compiled query is empty", category="QUERY")
    params = urlencode({"q": final, "limit": 20, "sort": "latest"})
    # Bluesky's current official HTTP reference still designates
    # public.api.bsky.app as the unauthenticated AppView for app.bsky.* GETs.
    # Live 403s therefore remain visible as transport/access failures; this
    # adapter does not switch to undocumented hosts, add auth, or bypass WAFs.
    search_base = "https://public.api.bsky.app"
    data, meta = _request_json(f"{search_base}/xrpc/app.bsky.feed.searchPosts?{params}")
    meta = dict(meta)
    meta["appview_host"] = search_base
    meta["auth_used"] = False
    meta["access_contract"] = "OFFICIAL_PUBLIC_APPVIEW;_403_REMAINS_VISIBLE_NO_BYPASS"
    result = _base_result(source_id, query)
    thread_meta: list[dict[str, Any]] = []
    posts = ((data or {}).get("posts") or []) if isinstance(data, Mapping) else []
    for post in posts[:20]:
        if not isinstance(post, Mapping):
            continue
        record = post.get("record") if isinstance(post.get("record"), Mapping) else {}
        author = post.get("author") if isinstance(post.get("author"), Mapping) else {}
        uri = str(post.get("uri") or "")
        result["traces"].append(_trace(
            source=source_id, kind="DISCUSSION", content_unit="POST",
            title=f"Bluesky post by @{author.get('handle') or 'user'}",
            excerpt=record.get("text") or "", url=_bsky_web_url(uri, author.get("handle")),
            author=author.get("handle"), created_at=record.get("createdAt"),
            metadata={"uri": uri, "cid": post.get("cid"), "reply_count": post.get("replyCount"), "like_count": post.get("likeCount"), "quote_count": post.get("quoteCount")},
        ))
        if uri and int(post.get("replyCount") or 0) > 0:
            try:
                tparams = urlencode({"uri": uri, "depth": 1, "parentHeight": 0})
                tdata, tmeta = _request_json(f"https://public.api.bsky.app/xrpc/app.bsky.feed.getPostThread?{tparams}")
                thread_meta.append(tmeta)
            except SourceAdapterError as exc:
                thread_meta.append({"status_code": exc.status_code, "error": str(exc), "uri": uri})
                continue
            thread = (tdata or {}).get("thread") if isinstance(tdata, Mapping) else None
            if isinstance(thread, Mapping):
                for reply in _walk_bsky_replies(thread, parent_uri=uri, limit=12):
                    result["traces"].append(_trace(
                        source=source_id, kind="DISCUSSION", content_unit="REPLY",
                        title=f"Bluesky reply by @{reply.get('handle') or 'user'}",
                        excerpt=reply.get("text") or "", url=reply.get("url"), author=reply.get("handle"), created_at=reply.get("created_at"),
                        metadata={"uri": reply.get("uri"), "parent_uri": reply.get("parent_uri"), "reply_count": reply.get("reply_count"), "like_count": reply.get("like_count")},
                    ))
    result["transport"] = {"search": meta, "thread_calls": thread_meta, "public_read": True}
    return _finalize_result(result)


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)).strip())
    except Exception:
        return default


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)).strip())
    except Exception:
        return default


def search_x_recent(query: str) -> dict[str, Any]:
    source_id = "X_RECENT_SEARCH"
    state = source_runtime_state(source_id)
    if state["runtime_state"] != "READY":
        raise SourceAdapterError("X_BEARER_TOKEN not configured", category="CONFIG")
    compiled = compile_source_query(query, source_id)
    final = str(compiled.get("final_query") or "").strip()
    if not final:
        raise SourceAdapterError("compiled query is empty", category="QUERY")
    # X Recent Search requires max_results >= 10. Bound paid reads and estimate before issuing the request.
    max_reads = max(10, min(100, _int_env("SIGNALFORGE_X_MAX_POST_READS_PER_PROBE", 20)))
    unit_usd = max(0.0, _float_env("SIGNALFORGE_X_POST_READ_UNIT_USD", 0.005))
    max_usd = max(0.0, _float_env("SIGNALFORGE_X_MAX_USD_PER_PROBE", 0.10))
    estimated = round(max_reads * unit_usd, 6)
    if max_usd and estimated > max_usd + 1e-12:
        raise SourceAdapterError(f"X probe budget exceeded before request: estimated ${estimated:.4f} > cap ${max_usd:.4f}", category="COST_BUDGET")
    xquery = f"({final}) -is:retweet"
    params = urlencode({
        "query": xquery,
        "max_results": max_reads,
        "tweet.fields": "created_at,author_id,conversation_id,lang,public_metrics,referenced_tweets",
        "expansions": "author_id",
        "user.fields": "username,name",
    })
    headers = {"Authorization": f"Bearer {os.environ['X_BEARER_TOKEN']}", "Accept": "application/json"}
    data, meta = _request_json(f"https://api.x.com/2/tweets/search/recent?{params}", headers=headers)
    result = _base_result(source_id, query)
    users = {}
    includes = (data or {}).get("includes") if isinstance(data, Mapping) else {}
    for user in ((includes or {}).get("users") or []) if isinstance(includes, Mapping) else []:
        if isinstance(user, Mapping) and user.get("id"):
            users[str(user.get("id"))] = user
    for post in ((data or {}).get("data") or [])[:max_reads] if isinstance(data, Mapping) else []:
        if not isinstance(post, Mapping):
            continue
        uid = str(post.get("author_id") or "")
        user = users.get(uid, {})
        username = user.get("username")
        pid = str(post.get("id") or "")
        refs = post.get("referenced_tweets") if isinstance(post.get("referenced_tweets"), list) else []
        is_reply = any(isinstance(x, Mapping) and x.get("type") == "replied_to" for x in refs)
        result["traces"].append(_trace(
            source=source_id, kind="DISCUSSION", content_unit="REPLY" if is_reply else "POST",
            title=f"X {'reply' if is_reply else 'post'} by @{username or uid or 'user'}",
            excerpt=post.get("text") or "", url=(f"https://x.com/{username}/status/{pid}" if username and pid else None),
            author=username or uid or None, created_at=post.get("created_at"),
            metadata={"post_id": pid, "conversation_id": post.get("conversation_id"), "lang": post.get("lang"), "public_metrics": post.get("public_metrics") or {}, "paid_resource_read": True},
        ))
    actual_reads = len(result["traces"])
    result["transport"] = {
        **meta,
        "pricing_assumption_usd_per_post_read": unit_usd,
        "max_post_reads_per_probe": max_reads,
        "max_probe_cost_usd": max_usd,
        "estimated_max_cost_usd": estimated,
        "estimated_actual_cost_usd": round(actual_reads * unit_usd, 6),
        "conversation_expansion": "DISABLED_IN_WAVE2_TO_AVOID_UNBOUNDED_PAID_READS",
    }
    return _finalize_result(result)


def _request_public_json(url: str, *, headers: Mapping[str, str] | None = None, timeout: float = DEFAULT_TIMEOUT, max_bytes: int = MAX_BYTES) -> tuple[Any, dict[str, Any]]:
    body, meta = _request_public_bytes(url, headers=headers, timeout=timeout, max_bytes=max_bytes)
    try:
        return json.loads(body.decode("utf-8", errors="replace")), meta
    except json.JSONDecodeError as exc:
        raise SourceAdapterError(f"invalid JSON: {exc}", category="PARSE") from exc



def search_github_discussions(query: str) -> dict[str, Any]:
    source_id = "GITHUB_DISCUSSIONS"
    state = source_runtime_state(source_id)
    if state["runtime_state"] != "READY":
        raise SourceAdapterError("GITHUB_TOKEN and SIGNALFORGE_GITHUB_DISCUSSION_REPOS are required", category="CONFIG")
    token = os.environ["GITHUB_TOKEN"]
    repos = github_discussion_repos()
    if not repos:
        raise SourceAdapterError("no valid GitHub Discussion repositories configured", category="CONFIG")
    compiled = compile_source_query(query, source_id)
    final = str(compiled.get("final_query") or "").strip()
    if not final:
        raise SourceAdapterError("compiled query is empty", category="QUERY")
    result = _base_result(source_id, query)
    result["final_search_query_used"] = final
    result["query_contract"] = compiled
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    transports: list[dict[str, Any]] = []
    graphql = """
    query SignalForgeDiscussions($owner:String!,$name:String!){
      repository(owner:$owner,name:$name){
        discussions(first:20,orderBy:{field:UPDATED_AT,direction:DESC}){
          nodes{
            id number title body url createdAt updatedAt
            author{login}
            comments(first:30){nodes{
              id body url createdAt updatedAt author{login}
              replies(first:12){nodes{id body url createdAt updatedAt author{login}}}
            }}
          }
        }
      }
    }
    """
    qterms = {x.lower() for x in semantic_terms(final, include_lens_aliases=False) if len(str(x)) >= 3}
    for repo_cfg in repos[:20]:
        owner, repo = repo_cfg["owner"], repo_cfg["repo"]
        payload = {"query": graphql, "variables": {"owner": owner, "name": repo}}
        try:
            data, meta = _request_json_post("https://api.github.com/graphql", payload, headers=headers)
            transports.append({"repo": f"{owner}/{repo}", **meta})
        except SourceAdapterError as exc:
            transports.append({"repo": f"{owner}/{repo}", "status_code": exc.status_code, "error": str(exc)})
            continue
        if isinstance(data, Mapping) and data.get("errors"):
            transports.append({"repo": f"{owner}/{repo}", "graphql_errors": data.get("errors")})
            continue
        nodes = (((data or {}).get("data") or {}).get("repository") or {}).get("discussions", {}).get("nodes", []) if isinstance(data, Mapping) else []
        for discussion in nodes or []:
            if not isinstance(discussion, Mapping):
                continue
            hay = _clean(f"{discussion.get('title') or ''} {discussion.get('body') or ''}").lower()
            overlap = sum(1 for t in qterms if t in hay)
            # Configured repos are domain-scoped, but still require at least one semantic
            # overlap before the discussion is emitted as an observation.
            if qterms and overlap < 1:
                continue
            did = str(discussion.get("id") or discussion.get("number") or "")
            group = f"github-discussion:{owner.lower()}/{repo.lower()}:{did}"
            result["traces"].append(_trace(
                source=source_id, kind="DISCUSSION", content_unit="DISCUSSION",
                title=discussion.get("title") or "GitHub discussion", excerpt=discussion.get("body") or "",
                url=discussion.get("url"), author=((discussion.get("author") or {}).get("login") if isinstance(discussion.get("author"), Mapping) else None),
                created_at=discussion.get("createdAt"),
                metadata={"repository": f"{owner}/{repo}", "discussion_id": did, "discussion_number": discussion.get("number"), "independence_group_key": group},
            ))
            comments = ((discussion.get("comments") or {}).get("nodes") if isinstance(discussion.get("comments"), Mapping) else []) or []
            for comment in comments[:30]:
                if not isinstance(comment, Mapping):
                    continue
                cid = str(comment.get("id") or "")
                result["traces"].append(_trace(
                    source=source_id, kind="DISCUSSION", content_unit="DISCUSSION_COMMENT",
                    title=f"Comment on {discussion.get('title') or 'GitHub discussion'}", excerpt=comment.get("body") or "",
                    url=comment.get("url") or discussion.get("url"), author=((comment.get("author") or {}).get("login") if isinstance(comment.get("author"), Mapping) else None),
                    created_at=comment.get("createdAt"),
                    metadata={"repository": f"{owner}/{repo}", "discussion_id": did, "comment_id": cid, "independence_group_key": group},
                ))
                replies = ((comment.get("replies") or {}).get("nodes") if isinstance(comment.get("replies"), Mapping) else []) or []
                for reply in replies[:12]:
                    if not isinstance(reply, Mapping):
                        continue
                    result["traces"].append(_trace(
                        source=source_id, kind="DISCUSSION", content_unit="DISCUSSION_REPLY",
                        title=f"Reply on {discussion.get('title') or 'GitHub discussion'}", excerpt=reply.get("body") or "",
                        url=reply.get("url") or comment.get("url") or discussion.get("url"), author=((reply.get("author") or {}).get("login") if isinstance(reply.get("author"), Mapping) else None),
                        created_at=reply.get("createdAt"),
                        metadata={"repository": f"{owner}/{repo}", "discussion_id": did, "comment_id": cid, "reply_id": reply.get("id"), "independence_group_key": group},
                    ))
    result["transport"] = {"repositories": transports, "graphql_read_only": True, "configured_repo_count": len(repos)}
    return _finalize_result(result)

def search_discourse(query: str) -> dict[str, Any]:
    source_id = "DISCOURSE_PUBLIC"
    sites = discourse_site_configs()
    if not sites:
        raise SourceAdapterError("SIGNALFORGE_DISCOURSE_SITES not configured", category="CONFIG")
    compiled = compile_source_query(query, source_id)
    final = str(compiled.get("final_query") or "").strip()
    if not final:
        raise SourceAdapterError("compiled query is empty", category="QUERY")
    result = _base_result(source_id, query)
    transports: list[dict[str, Any]] = []
    union_obs: list[str] = []
    for cfg in sites[:20]:
        base = str(cfg.get("base_url") or "").rstrip("/")
        _assert_public_http_url(base)
        obs = [str(x).upper() for x in (cfg.get("observation_families") or []) if str(x).strip()]
        union_obs.extend(obs)
        search_url = f"{base}/search.json?{urlencode({'q': final})}"
        try:
            data, meta = _request_public_json(search_url, headers={"Accept": "application/json"}, max_bytes=1_500_000)
            transports.append({"base_url": base, "search": meta})
        except SourceAdapterError as exc:
            transports.append({"base_url": base, "error": str(exc), "status_code": exc.status_code})
            continue
        topics = {str(x.get("id")): x for x in ((data or {}).get("topics") or []) if isinstance(x, Mapping) and x.get("id") is not None} if isinstance(data, Mapping) else {}
        posts = ((data or {}).get("posts") or []) if isinstance(data, Mapping) else []
        topic_ids: list[str] = []
        for post in posts[:20]:
            if not isinstance(post, Mapping):
                continue
            tid = str(post.get("topic_id") or "")
            if tid and tid not in topic_ids:
                topic_ids.append(tid)
            topic = topics.get(tid, {})
            title = topic.get("title") or post.get("name") or "Discourse discussion"
            url = f"{base}/t/{quote(str(topic.get('slug') or 'topic'), safe='')}/{quote(tid, safe='')}" if tid else base
            result["traces"].append(_trace(
                source=source_id, kind="DISCUSSION", content_unit="POST",
                title=title, excerpt=post.get("blurb") or post.get("cooked") or "", url=url,
                author=post.get("username"), created_at=post.get("created_at"),
                metadata={"base_url": base, "topic_id": tid, "post_id": post.get("id")}, observation_families=obs or ["DOMAIN_FORUMS"],
            ))
        # Expand a small number of public topics so replies become first-class observations.
        for tid in topic_ids[:5]:
            topic = topics.get(tid, {})
            slug = str(topic.get("slug") or "topic")
            topic_url = f"{base}/t/{quote(slug, safe='')}/{quote(tid, safe='')}.json"
            try:
                tdata, tmeta = _request_public_json(topic_url, headers={"Accept": "application/json"}, max_bytes=1_500_000)
                transports.append({"base_url": base, "topic_id": tid, "topic": tmeta})
            except SourceAdapterError as exc:
                transports.append({"base_url": base, "topic_id": tid, "error": str(exc), "status_code": exc.status_code})
                continue
            stream = (tdata or {}).get("post_stream") if isinstance(tdata, Mapping) else {}
            tposts = ((stream or {}).get("posts") or []) if isinstance(stream, Mapping) else []
            for idx, post in enumerate(tposts[:12]):
                if not isinstance(post, Mapping):
                    continue
                result["traces"].append(_trace(
                    source=source_id, kind="DISCUSSION", content_unit="TOPIC" if idx == 0 else "POST",
                    title=(tdata or {}).get("title") or topic.get("title") or "Discourse topic",
                    excerpt=post.get("cooked") or post.get("raw") or "",
                    url=f"{base}/t/{quote(slug, safe='')}/{quote(tid, safe='')}/{post.get('post_number') or idx+1}",
                    author=post.get("username"), created_at=post.get("created_at"),
                    metadata={"base_url": base, "topic_id": tid, "post_id": post.get("id"), "post_number": post.get("post_number")}, observation_families=obs or ["DOMAIN_FORUMS"],
                ))
    result["observation_source_families"] = list(dict.fromkeys(union_obs or ["DOMAIN_FORUMS"]))
    result["transport"] = {"sites": transports}
    return _finalize_result(result)


def _mastodon_tags(query: str, configured: list[str] | None = None) -> list[str]:
    tags: list[str] = []
    for value in (configured or []):
        clean = re.sub(r"[^A-Za-z0-9_\-\u4e00-\u9fff]", "", str(value).lstrip("#"))
        if 2 <= len(clean) <= 48:
            tags.append(clean)
    if not tags:
        for term in semantic_terms(query, include_lens_aliases=False):
            clean = re.sub(r"[^A-Za-z0-9_\-\u4e00-\u9fff]", "", str(term))
            if 3 <= len(clean) <= 32 and clean.lower() not in {"market", "product", "tool", "system", "user", "users"}:
                tags.append(clean)
            if len(tags) >= 3:
                break
    return list(dict.fromkeys(tags))[:3]


def search_mastodon(query: str) -> dict[str, Any]:
    source_id = "MASTODON_SEARCH"
    configs = mastodon_instance_configs()
    if not configs:
        raise SourceAdapterError("SIGNALFORGE_MASTODON_INSTANCES not configured", category="CONFIG")
    result = _base_result(source_id, query)
    result["discovery_scope"] = "HASHTAG_TIMELINE_ONLY"
    result["absence_adequacy"] = "PARTIAL"
    transports: list[dict[str, Any]] = []
    union_obs: list[str] = []
    for cfg in configs[:12]:
        base = str(cfg.get("base_url") or "").rstrip("/")
        _assert_public_http_url(base)
        obs = [str(x).upper() for x in (cfg.get("observation_families") or []) if str(x).strip()]
        union_obs.extend(obs)
        tags = _mastodon_tags(query, list(cfg.get("hashtags") or []))
        for tag in tags:
            url = f"{base}/api/v1/timelines/tag/{quote(tag, safe='')}?{urlencode({'limit': 20})}"
            try:
                data, meta = _request_public_json(url, headers={"Accept": "application/json"}, max_bytes=1_500_000)
                transports.append({"base_url": base, "hashtag": tag, **meta})
            except SourceAdapterError as exc:
                transports.append({"base_url": base, "hashtag": tag, "status_code": exc.status_code, "error": str(exc)})
                continue
            statuses = data if isinstance(data, list) else []
            for status in statuses[:20]:
                if not isinstance(status, Mapping):
                    continue
                sid = str(status.get("id") or "")
                account = status.get("account") if isinstance(status.get("account"), Mapping) else {}
                group = f"mastodon:{urlparse(base).netloc.lower()}:{sid or status.get('uri') or status.get('url')}"
                result["traces"].append(_trace(
                    source=source_id, kind="DISCUSSION", content_unit="REPLY" if status.get("in_reply_to_id") else "STATUS",
                    title=f"Mastodon status by @{account.get('acct') or account.get('username') or 'user'}",
                    excerpt=_clean(status.get("content") or ""), url=status.get("url") or status.get("uri"),
                    author=account.get("acct") or account.get("username"), created_at=status.get("created_at"),
                    metadata={"instance": base, "status_id": sid, "hashtag": tag, "replies_count": status.get("replies_count"), "language": status.get("language"), "independence_group_key": group},
                    observation_families=obs or _target_observation_families(source_id, query),
                ))
                if sid and int(status.get("replies_count") or 0) > 0 and len([x for x in transports if x.get("context_status_id")]) < 6:
                    try:
                        cdata, cmeta = _request_public_json(f"{base}/api/v1/statuses/{quote(sid, safe='')}/context", headers={"Accept": "application/json"}, max_bytes=1_500_000)
                        transports.append({"base_url": base, "context_status_id": sid, **cmeta})
                    except SourceAdapterError as exc:
                        transports.append({"base_url": base, "context_status_id": sid, "status_code": exc.status_code, "error": str(exc)})
                        continue
                    descendants = (cdata or {}).get("descendants") if isinstance(cdata, Mapping) else []
                    for child in (descendants or [])[:20]:
                        if not isinstance(child, Mapping):
                            continue
                        ca = child.get("account") if isinstance(child.get("account"), Mapping) else {}
                        result["traces"].append(_trace(
                            source=source_id, kind="DISCUSSION", content_unit="REPLY",
                            title=f"Mastodon reply by @{ca.get('acct') or ca.get('username') or 'user'}",
                            excerpt=_clean(child.get("content") or ""), url=child.get("url") or child.get("uri"),
                            author=ca.get("acct") or ca.get("username"), created_at=child.get("created_at"),
                            metadata={"instance": base, "status_id": child.get("id"), "parent_status_id": sid, "hashtag": tag, "independence_group_key": group},
                            observation_families=obs or _target_observation_families(source_id, query),
                        ))
    result["observation_source_families"] = list(dict.fromkeys(union_obs or _target_observation_families(source_id, query)))
    result["transport"] = {"instances": transports, "search_mode": "HASHTAG_TIMELINE_ONLY", "zero_results_not_adequate_for_market_absence": True}
    return _finalize_result(result)


def _lemmy_post_view(item: Mapping[str, Any]) -> tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]:
    post = item.get("post") if isinstance(item.get("post"), Mapping) else item
    creator = item.get("creator") if isinstance(item.get("creator"), Mapping) else {}
    community = item.get("community") if isinstance(item.get("community"), Mapping) else {}
    return post, creator, community


def _lemmy_comment_view(item: Mapping[str, Any]) -> tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]:
    comment = item.get("comment") if isinstance(item.get("comment"), Mapping) else item
    creator = item.get("creator") if isinstance(item.get("creator"), Mapping) else {}
    community = item.get("community") if isinstance(item.get("community"), Mapping) else {}
    return comment, creator, community


def search_lemmy(query: str) -> dict[str, Any]:
    source_id = "LEMMY_PUBLIC"
    configs = lemmy_instance_configs()
    if not configs:
        raise SourceAdapterError("SIGNALFORGE_LEMMY_INSTANCES not configured", category="CONFIG")
    compiled = compile_source_query(query, source_id)
    final = str(compiled.get("final_query") or "").strip()
    if not final:
        raise SourceAdapterError("compiled query is empty", category="QUERY")
    result = _base_result(source_id, query)
    transports: list[dict[str, Any]] = []
    union_obs: list[str] = []
    for cfg in configs[:12]:
        base = str(cfg.get("base_url") or "").rstrip("/")
        _assert_public_http_url(base)
        obs = [str(x).upper() for x in (cfg.get("observation_families") or []) if str(x).strip()]
        union_obs.extend(obs)
        search_url = f"{base}/api/v4/search?{urlencode({'search_term': final, 'type_': 'all', 'listing_type': 'all', 'limit': 20, 'show_nsfw': 'false'})}"
        try:
            data, meta = _request_public_json(search_url, headers={"Accept": "application/json"}, max_bytes=2_000_000)
            transports.append({"base_url": base, "search": meta})
        except SourceAdapterError as exc:
            transports.append({"base_url": base, "error": str(exc), "status_code": exc.status_code})
            continue
        post_items = []
        comment_items = []
        if isinstance(data, Mapping):
            post_items.extend(x for x in (data.get("posts") or []) if isinstance(x, Mapping))
            comment_items.extend(x for x in (data.get("comments") or []) if isinstance(x, Mapping))
            for item in (data.get("items") or []):
                if not isinstance(item, Mapping):
                    continue
                typ = str(item.get("type_") or item.get("type") or "").lower()
                if typ == "post": post_items.append(item.get("post") if isinstance(item.get("post"), Mapping) else item)
                elif typ == "comment": comment_items.append(item.get("comment") if isinstance(item.get("comment"), Mapping) else item)
        seen_post_ids: list[str] = []
        for item in post_items[:20]:
            post, creator, community = _lemmy_post_view(item)
            pid = str(post.get("id") or "")
            if pid and pid not in seen_post_ids: seen_post_ids.append(pid)
            group = f"lemmy:{urlparse(base).netloc.lower()}:post:{pid or post.get('ap_id') or post.get('url')}"
            result["traces"].append(_trace(
                source=source_id, kind="DISCUSSION", content_unit="POST", title=post.get("name") or "Lemmy post",
                excerpt=post.get("body") or "", url=post.get("ap_id") or post.get("url"), author=creator.get("name"), created_at=post.get("published_at") or post.get("published"),
                metadata={"instance": base, "post_id": pid, "community": community.get("name"), "independence_group_key": group}, observation_families=obs or _target_observation_families(source_id, query),
            ))
        for item in comment_items[:30]:
            comment, creator, community = _lemmy_comment_view(item)
            pid = str(comment.get("post_id") or "")
            cid = str(comment.get("id") or "")
            group = f"lemmy:{urlparse(base).netloc.lower()}:post:{pid or 'unknown'}"
            result["traces"].append(_trace(
                source=source_id, kind="DISCUSSION", content_unit="COMMENT", title="Lemmy comment", excerpt=comment.get("content") or "",
                url=comment.get("ap_id"), author=creator.get("name"), created_at=comment.get("published_at") or comment.get("published"),
                metadata={"instance": base, "post_id": pid, "comment_id": cid, "community": community.get("name"), "independence_group_key": group}, observation_families=obs or _target_observation_families(source_id, query),
            ))
        # Search responses can omit comments; deepen only the first few matched posts.
        for pid in seen_post_ids[:5]:
            try:
                cdata, cmeta = _request_public_json(f"{base}/api/v4/comment/list?{urlencode({'post_id': pid, 'limit': 20, 'sort': 'top', 'type_': 'all'})}", headers={"Accept": "application/json"}, max_bytes=1_500_000)
                transports.append({"base_url": base, "post_id": pid, "comments": cmeta})
            except SourceAdapterError as exc:
                transports.append({"base_url": base, "post_id": pid, "error": str(exc), "status_code": exc.status_code})
                continue
            rows = (cdata or {}).get("items") if isinstance(cdata, Mapping) else []
            for item in (rows or [])[:20]:
                if not isinstance(item, Mapping): continue
                comment, creator, community = _lemmy_comment_view(item)
                cid = str(comment.get("id") or "")
                group = f"lemmy:{urlparse(base).netloc.lower()}:post:{pid}"
                result["traces"].append(_trace(
                    source=source_id, kind="DISCUSSION", content_unit="COMMENT", title="Lemmy comment", excerpt=comment.get("content") or "",
                    url=comment.get("ap_id"), author=creator.get("name"), created_at=comment.get("published_at") or comment.get("published"),
                    metadata={"instance": base, "post_id": pid, "comment_id": cid, "community": community.get("name"), "independence_group_key": group}, observation_families=obs or _target_observation_families(source_id, query),
                ))
    result["observation_source_families"] = list(dict.fromkeys(union_obs or _target_observation_families(source_id, query)))
    result["transport"] = {"instances": transports, "public_read": True}
    return _finalize_result(result)


def search_stackexchange_network(query: str) -> dict[str, Any]:
    source_id = "STACK_EXCHANGE_NETWORK"
    sites = stackexchange_site_configs()
    if not sites:
        raise SourceAdapterError("SIGNALFORGE_STACKEXCHANGE_SITES not configured", category="CONFIG")
    compiled = compile_source_query(query, source_id)
    final = str(compiled.get("final_query") or "").strip()
    if not final:
        raise SourceAdapterError("compiled query is empty", category="QUERY")
    result = _base_result(source_id, query)
    transports: list[dict[str, Any]] = []
    union_obs: list[str] = []
    for cfg in sites[:20]:
        site = str(cfg.get("site") or "").strip()
        obs = [str(x).upper() for x in (cfg.get("observation_families") or []) if str(x).strip()]
        union_obs.extend(obs)
        params = urlencode({"site": site, "q": final, "pagesize": 12, "sort": "relevance", "order": "desc", "filter": "withbody"})
        try:
            data, meta = _request_json(f"https://api.stackexchange.com/2.3/search/advanced?{params}")
            transports.append({"site": site, "search": meta})
        except SourceAdapterError as exc:
            transports.append({"site": site, "error": str(exc), "status_code": exc.status_code})
            continue
        items = (data or {}).get("items") if isinstance(data, Mapping) else []
        for qrow in (items or [])[:8]:
            if not isinstance(qrow, Mapping): continue
            qid = str(qrow.get("question_id") or "")
            group = f"stackexchange:{site}:{qid}"
            result["traces"].append(_trace(
                source=source_id, kind="DISCUSSION", content_unit="QUESTION", title=_clean(qrow.get("title")), excerpt=_clean(qrow.get("body") or ""),
                url=qrow.get("link"), author=((qrow.get("owner") or {}).get("display_name") if isinstance(qrow.get("owner"), Mapping) else None),
                created_at=datetime.fromtimestamp(int(qrow.get("creation_date") or 0), tz=timezone.utc).isoformat() if qrow.get("creation_date") else None,
                metadata={"site": site, "question_id": qid, "score": qrow.get("score"), "answer_count": qrow.get("answer_count"), "independence_group_key": group}, observation_families=obs or ["DOMAIN_QA"],
            ))
            if not qid: continue
            endpoints = [
                ("ANSWER", f"https://api.stackexchange.com/2.3/questions/{quote(qid, safe='')}/answers?{urlencode({'site': site, 'pagesize': 30, 'sort': 'votes', 'order': 'desc', 'filter': 'withbody'})}"),
                ("COMMENT", f"https://api.stackexchange.com/2.3/questions/{quote(qid, safe='')}/comments?{urlencode({'site': site, 'pagesize': 40, 'sort': 'votes', 'order': 'desc', 'filter': 'withbody'})}"),
            ]
            for unit, url in endpoints:
                try:
                    child, cmeta = _request_json(url)
                    transports.append({"site": site, "question_id": qid, "unit": unit, **cmeta})
                except SourceAdapterError as exc:
                    transports.append({"site": site, "question_id": qid, "unit": unit, "error": str(exc), "status_code": exc.status_code})
                    continue
                for crow in ((child or {}).get("items") or [])[:40] if isinstance(child, Mapping) else []:
                    if not isinstance(crow, Mapping): continue
                    result["traces"].append(_trace(
                        source=source_id, kind="DISCUSSION", content_unit=unit, title=f"{unit.title()} on {_clean(qrow.get('title'))}", excerpt=_clean(crow.get("body") or ""),
                        url=crow.get("link") or qrow.get("link"), author=((crow.get("owner") or {}).get("display_name") if isinstance(crow.get("owner"), Mapping) else None),
                        created_at=datetime.fromtimestamp(int(crow.get("creation_date") or 0), tz=timezone.utc).isoformat() if crow.get("creation_date") else None,
                        metadata={"site": site, "question_id": qid, "answer_id": crow.get("answer_id"), "comment_id": crow.get("comment_id"), "score": crow.get("score"), "independence_group_key": group}, observation_families=obs or ["DOMAIN_QA"],
                    ))
    result["observation_source_families"] = list(dict.fromkeys(union_obs or ["DOMAIN_QA", "PROFESSIONAL_COMMUNITIES"]))
    result["transport"] = {"sites": transports, "public_read": True}
    return _finalize_result(result)


def search_ashby_jobs(query: str) -> dict[str, Any]:
    source_id = "ASHBY_PUBLIC_JOBS"
    boards = ashby_board_names()
    if not boards:
        raise SourceAdapterError("SIGNALFORGE_ASHBY_BOARDS not configured", category="CONFIG")
    result = _base_result(source_id, query)
    transports: list[dict[str, Any]] = []
    for board in boards[:50]:
        url = f"https://api.ashbyhq.com/posting-api/job-board/{quote(board, safe='')}?includeCompensation=true"
        try:
            data, meta = _request_json(url)
            transports.append({"board": board, **meta})
        except SourceAdapterError as exc:
            transports.append({"board": board, "error": str(exc), "status_code": exc.status_code})
            continue
        for job in ((data or {}).get("jobs") or [])[:200] if isinstance(data, Mapping) else []:
            if not isinstance(job, Mapping) or job.get("isListed") is False: continue
            text = _clean(f"{job.get('title') or ''} {job.get('descriptionPlain') or job.get('descriptionHtml') or ''} {job.get('department') or ''} {job.get('team') or ''}")
            if _query_overlap_score(query, text) < 1: continue
            compensation = job.get("compensation") if isinstance(job.get("compensation"), Mapping) else {}
            result["traces"].append(_trace(
                source=source_id, kind="JOB", content_unit="JOB_POST", title=job.get("title") or "Ashby job", excerpt=text,
                url=job.get("jobUrl") or job.get("applyUrl"), created_at=job.get("publishedAt"),
                metadata={"board": board, "location": job.get("location"), "department": job.get("department"), "team": job.get("team"), "employment_type": job.get("employmentType"), "compensation": compensation},
                observation_families=["CONSULTING_JOB_POSTS", "COMPANY_JOB_POSTS", "HIRING_SPEND_SIGNAL"],
            ))
    result["transport"] = {"boards": transports, "public_read": True, "include_compensation": True}
    return _finalize_result(result)


_ADAPTERS = {
    "BRAVE_WEB": search_brave,
    "GDELT_DOC": search_gdelt,
    "YOUTUBE_DATA_API": search_youtube,
    "THREADS_API": search_threads,
    "GREENHOUSE_PUBLIC_JOBS": search_greenhouse_jobs,
    "LEVER_PUBLIC_JOBS": search_lever_jobs,
    "RSS_ATOM": search_rss_feeds,
    "BLUESKY_PUBLIC_SEARCH": search_bluesky,
    "X_RECENT_SEARCH": search_x_recent,
    "DISCOURSE_PUBLIC": search_discourse,
    "GITHUB_DISCUSSIONS": search_github_discussions,
    "MASTODON_SEARCH": search_mastodon,
    "LEMMY_PUBLIC": search_lemmy,
    "STACK_EXCHANGE_NETWORK": search_stackexchange_network,
    "ASHBY_PUBLIC_JOBS": search_ashby_jobs,
}


def adapter_ids() -> list[str]:
    return list(_ADAPTERS)


def run_adapter(source_id: str, query: str) -> dict[str, Any]:
    if source_id not in _ADAPTERS:
        raise SourceAdapterError(f"no adapter implemented for {source_id}", category="NOT_IMPLEMENTED")
    return _ADAPTERS[source_id](query)
