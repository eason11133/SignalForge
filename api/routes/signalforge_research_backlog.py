from __future__ import annotations

import asyncio
import concurrent.futures
import ipaddress
import json
import html as html_lib
import os
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Mapping

from fastapi import APIRouter, HTTPException

router = APIRouter()
_REPO_ROOT = Path(__file__).resolve().parents[2]
_worker_task: asyncio.Task[Any] | None = None
_autopilot_task: asyncio.Task[Any] | None = None
_IDLE_POLL_SECONDS = 60
_CONTINUOUS_BATCH_SIZE = 500
_SESSION_JOB_CAP = 5000


async def _refresh_curated_backlog() -> dict[str, Any]:
    """Refresh only the explicit Founder/AI opportunity store.

    V1.5 deliberately does not import ProblemCandidate/Opportunity database rows. Those rows are
    discovery/evidence material, not Founder research targets.
    """
    from processors.signalforge_research_backlog import sync_backlog

    return sync_backlog(_REPO_ROOT)


@router.post("/research-backlog/sync")
async def research_backlog_sync(payload: dict[str, Any] | None = None):
    """Compatibility endpoint: refresh the explicit opportunity queue only.

    If callers include explicit ideas, add them. Automatic DB candidates are never imported.
    """
    from processors.signalforge_research_backlog import add_ideas, backlog_view

    _ensure_autopilot_supervisor()
    if _worker_running():
        current = backlog_view(_REPO_ROOT, limit=1)
        return {
            "status": "REFRESH_DEFERRED_WHILE_RESEARCH_RUNNING",
            "total": current.get("total", 0),
            "worker": current.get("worker", {}),
            "automation": current.get("automation", {}),
            "market_truth_writes": 0,
        }

    result = await _refresh_curated_backlog()
    body = payload or {}
    ideas = body.get("ideas") if isinstance(body.get("ideas"), list) else []
    if ideas:
        if len(ideas) > 1000:
            raise HTTPException(status_code=422, detail="ideas batch is bounded to 1000 items")
        custom = add_ideas(_REPO_ROOT, [row for row in ideas if isinstance(row, dict)])
        result = {**result, **custom}
    auto_start = await _ensure_worker_started(_CONTINUOUS_BATCH_SIZE, founder_resume=False)
    return {**result, "status": "CURATED_BACKLOG_REFRESHED", "auto_start": auto_start}


@router.get("/research-backlog")
async def research_backlog_list(q: str = "", status: str = "", limit: int = 1000):
    from processors.signalforge_research_backlog import backlog_view, load_store

    _ensure_autopilot_supervisor()
    if not _worker_running():
        # Safe only when no process-local worker exists: repair a stale RUNNING marker left by a prior API restart.
        load_store(_REPO_ROOT, repair_worker=True)
    return backlog_view(
        _REPO_ROOT,
        q=q,
        status=status,
        limit=max(1, min(int(limit or 1000), 2000)),
    )


@router.post("/research-backlog/ideas")
async def research_backlog_add_ideas(payload: dict[str, Any]):
    from processors.signalforge_research_backlog import add_ideas

    ideas = payload.get("ideas") if isinstance(payload.get("ideas"), list) else []
    if not ideas:
        raise HTTPException(status_code=422, detail="ideas must contain at least one item")
    if len(ideas) > 1000:
        raise HTTPException(status_code=422, detail="ideas batch is bounded to 1000 items")
    result = add_ideas(_REPO_ROOT, [row for row in ideas if isinstance(row, dict)])
    auto_start = await _ensure_worker_started(_CONTINUOUS_BATCH_SIZE, founder_resume=False)
    return {**result, "auto_start": auto_start}



def _traceable_http_url(value: Any) -> str:
    url = str(value or "").strip()
    if not url:
        return ""
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return ""
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc or not parsed.hostname:
        return ""
    host = parsed.hostname.lower().strip(".")
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        return ""
    try:
        literal = ipaddress.ip_address(host)
        if literal.is_private or literal.is_loopback or literal.is_link_local or literal.is_reserved or literal.is_multicast:
            return ""
    except ValueError:
        pass
    return url


def _public_dns_target(url: str) -> bool:
    try:
        host = urllib.parse.urlparse(url).hostname
        if not host:
            return False
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        addresses = {info[4][0] for info in infos if info and info[4]}
        if not addresses:
            return False
        for value in addresses:
            ip = ipaddress.ip_address(value)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                return False
        return True
    except Exception:
        return False


def _brief_evidence_urls(brief: Mapping[str, Any], limit: int = 12) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for lane in ("human_comments", "similar_products", "repo_solutions", "supporting_evidence", "counter_evidence"):
        values = brief.get(lane)
        if not isinstance(values, list):
            continue
        for value in values:
            if not isinstance(value, Mapping):
                continue
            url = _traceable_http_url(value.get("url"))
            if not url or url in seen:
                continue
            seen.add(url)
            rows.append({
                "url": url,
                "source": str(value.get("source") or "").strip(),
                "title": str(value.get("title") or "").strip()[:240],
                "excerpt": str(value.get("excerpt") or "").strip()[:2200],
                "lane": lane,
            })
            if len(rows) >= limit:
                return rows
    return rows



def _visible_text(raw: bytes, content_type: str) -> str:
    """Bounded best-effort page text for source verification; no browser/LLM dependency."""
    if not raw:
        return ""
    text = raw.decode("utf-8", errors="ignore")
    if "html" in str(content_type or "").lower() or "<html" in text[:2048].lower():
        text = re.sub(r"(?is)<(script|style|noscript|svg|template)[^>]*>.*?</\1>", " ", text)
        text = re.sub(r"(?s)<[^>]+>", " ", text)
        text = html_lib.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:120000]


def _verification_terms(value: str) -> set[str]:
    text = str(value or "").lower()
    latin = {
        token
        for token in re.findall(r"[a-z0-9][a-z0-9.+#/_-]{2,}", text)
        if token not in {"http", "https", "www", "com", "from", "with", "that", "this", "have", "your", "their", "about"}
    }
    chars = [ch for ch in text if "\u3400" <= ch <= "\u9fff"]
    cjk = {"".join(chars[i:i+2]) for i in range(max(0, len(chars)-1))}
    return latin | cjk


def _content_verification(evidence_text: str, source_text: str) -> dict[str, Any]:
    """Conservative grounding check: only explicit zero-overlap on substantial text becomes mismatch."""
    evidence_terms = _verification_terms(evidence_text)
    source_terms = _verification_terms(source_text)
    overlap = evidence_terms & source_terms
    denom = max(1, min(len(evidence_terms), 20))
    ratio = round(len(overlap) / denom, 4)
    if len(evidence_terms) < 4 or len(source_terms) < 12:
        status = "UNVERIFIED_TOO_LITTLE_TEXT"
    elif len(overlap) >= 3 or ratio >= 0.25:
        status = "MATCH"
    elif len(overlap) == 0 and len(evidence_terms) >= 8 and len(source_terms) >= 40:
        status = "MISMATCH"
    else:
        status = "UNCERTAIN"
    return {
        "status": status,
        "evidence_terms": len(evidence_terms),
        "source_terms": len(source_terms),
        "overlap_terms": sorted(overlap)[:20],
        "overlap_ratio": ratio,
    }


def _tavily_extract_urls(urls: list[str], credential: str) -> dict[str, dict[str, Any]]:
    """Two-step retrieve -> curate -> extract, following Tavily's recommended research pattern."""
    cleaned = [url for url in urls if _traceable_http_url(url)][:5]
    if not cleaned or not credential:
        return {}
    body = json.dumps({"urls": cleaned, "include_images": False, "extract_depth": "basic"}).encode("utf-8")
    req = urllib.request.Request(
        "https://api.tavily.com/extract",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {credential}",
            "Content-Type": "application/json",
            "User-Agent": "SignalForge/1.6 SourceGrounding",
        },
    )
    started = time.monotonic()
    out: dict[str, dict[str, Any]] = {}
    try:
        with urllib.request.urlopen(req, timeout=10.0) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
        for row in payload.get("results") or [] if isinstance(payload, Mapping) else []:
            if not isinstance(row, Mapping):
                continue
            url = _traceable_http_url(row.get("url"))
            if not url:
                continue
            raw_content = str(row.get("raw_content") or "")
            out[url] = {
                "ok": bool(raw_content.strip()),
                "mode": "TAVILY_EXTRACT_BASIC",
                "chars": len(raw_content),
                "text": raw_content[:120000],
                "ms": int((time.monotonic() - started) * 1000),
            }
        for row in payload.get("failed_results") or [] if isinstance(payload, Mapping) else []:
            if not isinstance(row, Mapping):
                continue
            url = _traceable_http_url(row.get("url"))
            if url and url not in out:
                out[url] = {
                    "ok": False,
                    "mode": "TAVILY_EXTRACT_BASIC",
                    "chars": 0,
                    "text": "",
                    "error": str(row.get("error") or "EXTRACT_FAILED")[:220],
                    "ms": int((time.monotonic() - started) * 1000),
                }
        return out
    except Exception as exc:
        return {
            url: {
                "ok": False,
                "mode": "TAVILY_EXTRACT_BASIC",
                "chars": 0,
                "text": "",
                "error": f"{type(exc).__name__}: {str(exc)[:180]}",
                "ms": int((time.monotonic() - started) * 1000),
            }
            for url in cleaned
        }

def _open_original_page(row: Mapping[str, str]) -> dict[str, Any]:
    url = _traceable_http_url(row.get("url"))
    base = {
        "url": url,
        "source": row.get("source") or "",
        "title": row.get("title") or "",
        "excerpt": row.get("excerpt") or "",
        "lane": row.get("lane") or "",
        "ok": False,
        "status": None,
        "final_url": None,
        "content_type": None,
        "bytes_read": 0,
        "page_title": None,
        "error": None,
    }
    if not url:
        base["error"] = "INVALID_URL"
        return base
    if not _public_dns_target(url):
        base["error"] = "NON_PUBLIC_OR_UNRESOLVED_TARGET"
        return base
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (SignalForge Research Audit/1.6; +local-founder-research)",
            "Accept": "text/html,application/xhtml+xml,application/json,text/plain;q=0.8,*/*;q=0.5",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=4.5) as response:
            raw = response.read(65536)
            status = int(getattr(response, "status", 200) or 200)
            content_type = str(response.headers.get("Content-Type") or "")[:180]
            final_url = str(response.geturl() or url)
            page_title = ""
            decoded = raw.decode("utf-8", errors="ignore") if raw else ""
            if raw and ("html" in content_type.lower() or b"<html" in raw[:2048].lower()):
                match = re.search(r"<title[^>]*>(.*?)</title>", decoded, flags=re.I | re.S)
                if match:
                    page_title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", match.group(1))).strip()[:300]
            source_text = _visible_text(raw, content_type)
            evidence_text = f"{row.get('title') or ''} {row.get('excerpt') or ''}"
            verification = _content_verification(evidence_text, source_text) if source_text else {"status": "OPENED_NO_EXTRACTABLE_TEXT"}
            base.update({
                "ok": 200 <= status < 400,
                "status": status,
                "final_url": final_url,
                "content_type": content_type,
                "bytes_read": len(raw),
                "page_title": page_title or None,
                "source_text_chars": len(source_text),
                "content_verification": verification,
            })
            return base
    except urllib.error.HTTPError as exc:
        base["status"] = int(exc.code or 0) or None
        base["final_url"] = str(getattr(exc, "url", None) or url)
        base["error"] = f"HTTP_{exc.code}"
        return base
    except Exception as exc:
        base["error"] = f"{type(exc).__name__}: {str(exc)[:220]}"
        return base


def _audit_original_pages(brief: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = _brief_evidence_urls(brief, limit=16)
    if not rows:
        return []
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(5, len(rows))) as pool:
        checks = list(pool.map(_open_original_page, rows))

    # Tavily explicitly recommends two-step search -> curate -> extract. Only the already-curated
    # Founder-evidence URLs are extracted, bounded to five URLs so V1 cost/latency stays predictable.
    provider, credential = _general_web_provider()
    tavily_rows = [row for row in rows if str(row.get("source") or "").upper() == "TAVILY_WEB_SEARCH"]
    extracted = _tavily_extract_urls([str(row.get("url") or "") for row in tavily_rows[:5]], credential or "") if provider == "TAVILY_WEB_SEARCH" else {}
    row_by_url = {str(row.get("url") or ""): row for row in rows}
    for check in checks:
        url = str(check.get("url") or "")
        ext = extracted.get(url)
        if not isinstance(ext, Mapping):
            continue
        check["provider_extract"] = {k: v for k, v in ext.items() if k != "text"}
        if bool(ext.get("ok")) and str(ext.get("text") or "").strip():
            source_row = row_by_url.get(url) or {}
            evidence_text = f"{source_row.get('title') or ''} {source_row.get('excerpt') or ''}"
            verification = _content_verification(evidence_text, str(ext.get("text") or ""))
            check["content_verification"] = {**verification, "mode": "TAVILY_EXTRACT_BASIC"}
            check["source_text_chars"] = int(ext.get("chars") or 0)
    return checks


def _source_attempts_from_brief(brief: Mapping[str, Any]) -> list[dict[str, Any]]:
    search = brief.get("search") if isinstance(brief.get("search"), Mapping) else {}
    successful = search.get("successful_sources") if isinstance(search.get("successful_sources"), list) else []
    failed = search.get("failed_sources") if isinstance(search.get("failed_sources"), list) else []
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in successful:
        name = str(source or "").strip()
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        rows.append({"source": name, "status": "SUCCESS"})
    for value in failed:
        if not isinstance(value, Mapping):
            continue
        name = str(value.get("source") or value.get("name") or value.get("provider") or "source").strip()
        reason = str(value.get("error") or value.get("reason") or value.get("status") or "").strip()
        rows.append({"source": name or "source", "status": "FAILED", "reason": reason[:300]})
    return rows[:24]


_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_CN_SEARCH_LEXICON: tuple[tuple[str, str], ...] = (
    # education / appointments
    ("排課", "scheduling"), ("預約", "booking appointment"), ("訂位", "reservation"),
    ("課程", "classes lessons"), ("才藝", "enrichment classes"), ("補習", "tutoring academy"),
    ("教練", "coach coaching"), ("工作室", "studio small business"), ("堂數", "class credits lesson package"),
    ("剩餘", "remaining balance credits"), ("出缺席", "attendance absence"), ("補課", "make-up class"),
    ("請假", "cancellation reschedule"), ("家長", "parents"), ("學生", "students"), ("老師", "teachers"),
    # finance / accounting / procurement
    ("對帳", "reconciliation reconcile"), ("核銷", "expense reimbursement expense report"),
    ("收據", "receipt receipts"), ("發票", "invoice invoices"), ("請款", "billing invoice collection"),
    ("付款", "payment payments"), ("退刷", "chargeback refund"), ("退款", "refund returns"),
    ("押金", "deposit security deposit"), ("里程碑", "milestone payment"), ("權利金", "royalty franchise fee"),
    ("信用額度", "credit limit accounts receivable"), ("逾期", "overdue receivables collections"),
    ("採購", "procurement purchasing"), ("報價", "quote quotation pricing"), ("供應商", "supplier vendor"),
    ("合約", "contract agreement"), ("續約", "renewal contract renewal"), ("訂閱", "subscription SaaS license"),
    ("閒置席次", "unused seats unused licenses"), ("分潤", "commission payout affiliate revenue share"),
    # construction / property / field service
    ("工地", "construction site jobsite"), ("工程", "construction project contractor"), ("追加", "change order variation extra work"),
    ("簽認", "approval signoff"), ("工班", "subcontractor crew"), ("日報", "daily report field report"),
    ("材料到貨", "material delivery receiving"), ("安裝量", "installed quantity quantity tracking"),
    ("缺失", "punch list defect snag"), ("修繕", "repair maintenance property"), ("漏水", "water leak building"),
    ("租戶", "tenant property management"), ("交屋", "handover turnover inspection"),
    # logistics / warehouse / e-commerce
    ("物流", "logistics shipping carrier"), ("貨損", "cargo damage freight claim"), ("承運商", "carrier freight"),
    ("倉庫", "warehouse"), ("月台", "dock appointment yard"), ("到車", "truck arrival"),
    ("出貨", "shipment shipping"), ("退貨", "returns reverse logistics"), ("棧板", "pallet returnable asset"),
    ("保冷箱", "cold box reusable container"), ("電商", "ecommerce online retail"), ("訂單", "orders order management"),
    ("庫存", "inventory stock"), ("可售數", "available to sell inventory"), ("預購", "preorder allocation demand"),
    # manufacturing / industrial
    ("工廠", "factory manufacturing"), ("機台", "machine equipment manufacturing"), ("停機", "machine downtime"),
    ("換線", "changeover setup"), ("參數", "machine settings parameters"), ("來料", "incoming material supplier quality"),
    ("品質缺陷", "quality defect nonconformance"), ("返工", "rework"), ("治具", "fixture tooling"),
    ("量具", "gauge metrology calibration"), ("校驗", "calibration due"), ("故障", "failure breakdown maintenance"),
    ("備品", "spare parts consumables"), ("零件", "parts spare parts"),
    # energy / facilities
    ("能源", "energy utility"), ("電費", "electricity bill utility"), ("尖峰需量", "peak demand demand charge"),
    ("水電", "utilities electricity water"), ("漏水定位", "water leak detection"), ("冷藏", "refrigeration cold storage"),
    ("空調", "HVAC air conditioning"), ("濾網", "HVAC filter maintenance"), ("盤管", "HVAC coil maintenance"),
    ("充電樁", "EV charger charging station"), ("發電機", "backup generator readiness"),
    # food / agriculture
    ("小農", "small farmer farm"), ("農產品", "agricultural produce wholesale"), ("採收", "harvest planning"),
    ("蔬果", "produce fruit vegetable"), ("餐廳", "restaurant foodservice"), ("備料", "food prep inventory"),
    ("廚餘", "food waste"), ("烘焙", "bakery production"), ("批次", "batch lot traceability"),
    ("代耕", "farm contractor machinery sharing"), ("花材", "floral perishables inventory"),
    # creator / marketing
    ("創作者", "creator influencer"), ("品牌合作", "brand sponsorship creator campaign"), ("審稿", "content approval revision"),
    ("授權素材", "licensed content usage rights"), ("聯盟", "affiliate marketing"), ("寄樣", "product seeding influencer"),
    ("直播帶貨", "live commerce social selling"), ("客服", "customer support"),
    # health / care
    ("診所", "clinic medical practice"), ("轉診", "referral patient referral"), ("檢查預約", "diagnostic appointment scheduling"),
    ("牙科", "dental clinic dental lab"), ("技工所", "dental laboratory"), ("居家照護", "home care caregiver"),
    ("看護", "caregiver care handoff"), ("處方", "prescription refill"), ("復健", "rehabilitation therapy"),
    ("照護器材", "medical equipment assistive device"), ("就診", "patient visit medical records"),
    # mobility / hospitality / local service
    ("車隊", "fleet operations"), ("事故", "vehicle accident damage"), ("保養", "maintenance service"),
    ("旅館", "hotel hospitality"), ("旅宿", "hotel lodging property management"), ("重複預訂", "double booking overbooking"),
    ("租車", "car rental vehicle inspection"), ("停車場", "parking access control"),
    ("美容", "salon beauty studio"), ("健身", "fitness gym"), ("寵物美容", "pet grooming"),
    ("到府清潔", "home cleaning service"), ("搬家公司", "moving company mover"), ("家電維修", "appliance repair service"),
    # software / AI
    ("錯誤", "errors bugs"), ("Bug", "bug issue"), ("回報", "report ticket"), ("重現", "reproduce reproduction steps"),
    ("第三方 API", "third party API integration"), ("模型", "model AI model"), ("規則", "rules instructions"),
    ("指令", "instructions prompt rules"), ("上下文", "context memory"), ("忘記", "forget memory"),
    ("開發環境", "developer environment setup"), ("Schema Drift", "schema drift data pipeline"),
    ("RPA", "RPA automation"), ("QA", "QA test cases regression"),
    # generic workflow words
    ("手動", "manual"), ("人工", "manual"), ("管理", "management"), ("記錄", "tracking records"),
    ("追蹤", "tracking"), ("通知", "notifications"), ("流程", "workflow process"), ("狀態", "status tracking"),
)


def _fallback_english_query(title: str, description: str, primary: str) -> str:
    text = f"{title} {description}".strip()
    terms: list[str] = []
    seen: set[str] = set()
    for token in re.findall(r"[A-Za-z][A-Za-z0-9.+#/_-]{1,}", text):
        low = token.lower()
        if low in {"the", "and", "for", "with", "from", "this", "that", "have", "will", "into", "about", "https"}:
            continue
        if low not in seen:
            seen.add(low)
            terms.append(token)
    for needle, expansion in _CN_SEARCH_LEXICON:
        if needle not in text:
            continue
        for token in expansion.split():
            low = token.lower()
            if low not in seen:
                seen.add(low)
                terms.append(token)
    query = " ".join(terms[:18]).strip()
    if len(query.split()) < 4:
        return ""
    if query.lower() == str(primary or "").strip().lower():
        return ""
    return query[:420]


def _brief_useful_count(brief: Mapping[str, Any]) -> int:
    summary = brief.get("summary") if isinstance(brief.get("summary"), Mapping) else {}
    try:
        return int(summary.get("useful_result_count") or 0)
    except Exception:
        return 0


def _tracking_direct_brief(source: Mapping[str, Any], *, family: str, query: str) -> dict[str, Any]:
    """Preserve general-web traces directly for the tracking collector.

    The old Founder-research brief builder is intentionally not allowed to be the only path from
    search results to the tracking library: it was designed to summarize/select evidence, while the
    tracking product should keep a high-recall pool of anything that is actually relevant.
    Relevance/grounding/dedupe still run later in the processor.
    """
    lane = {
        "public_discussions": "human_comments",
        "practitioner_communities": "human_comments",
        "vendor_support_communities": "human_comments",
        "domain_forums": "human_comments",
        "product_reviews": "human_comments",
        "app_marketplaces": "similar_products",
        "related_products": "similar_products",
        "manual_workarounds": "human_comments",
        "research_cases": "supporting_evidence",
        "academic_sources": "supporting_evidence",
        "b2b_operational_signals": "supporting_evidence",
        "job_procurement_signals": "supporting_evidence",
        "local_language": "supporting_evidence",
        "general_web": "supporting_evidence",
    }.get(family, "supporting_evidence")
    rows: list[dict[str, Any]] = []
    for raw in source.get("traces") or []:
        if not isinstance(raw, Mapping):
            continue
        row = dict(raw)
        row["tracking_family"] = family
        row["search_query"] = query
        if family == "related_products":
            row.setdefault("solution_type", "PRODUCT")
        elif family == "product_reviews":
            # Review pages are valuable human material but also strong product-discovery traces.
            row.setdefault("solution_type", "PRODUCT_REVIEW")
        rows.append(row)
    brief = {
        "human_comments": [],
        "similar_products": [],
        "repo_solutions": [],
        "supporting_evidence": [],
        "counter_evidence": [],
        "gaps": [],
    }
    brief[lane] = rows[:20]
    success = str(source.get("status") or "").upper() == "SUCCESS"
    brief["search"] = {
        "successful_sources": [str(source.get("source") or "GENERAL_WEB_SEARCH")] if success else [],
        "failed_sources": [] if success else [{"source": str(source.get("source") or "GENERAL_WEB_SEARCH"), "error": str(source.get("error") or "FAILED")}],
        "query_run_count": 1,
    }
    brief["summary"] = {
        "human_comment_count": len(brief["human_comments"]),
        "product_or_service_count": len(brief["similar_products"]),
        "repo_solution_count": 0,
        "supporting_evidence_count": len(brief["supporting_evidence"]),
        "counter_evidence_count": 0,
        "useful_result_count": len(rows[:20]),
    }
    return brief


def _tracking_prompt_metadata(description: str) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "mode": "DELTA_REFRESH", "seed": "", "preferred": [], "cycle": 0,
        "coverage": {}, "targets": {},
    }

    def parse_kv_csv(text: str) -> dict[str, int]:
        out: dict[str, int] = {}
        for part in str(text or "").split(","):
            if "=" not in part:
                continue
            key, value = part.split("=", 1)
            key = key.strip()
            try:
                out[key] = max(0, int(value.strip()))
            except Exception:
                continue
        return out

    for raw_line in str(description or "").splitlines():
        line = raw_line.strip()
        low = line.lower()
        if "source expansion mode:" in low:
            idx = low.index("source expansion mode:")
            tail = line[idx + len("source expansion mode:"):].strip()
            meta["mode"] = tail.split()[0].rstrip(".").upper() if tail else "DELTA_REFRESH"
        elif low.startswith("tracking search seed:"):
            meta["seed"] = line.split(":", 1)[1].strip()
        elif low.startswith("tracking preferred families:"):
            meta["preferred"] = [x.strip() for x in line.split(":", 1)[1].split(",") if x.strip()]
        elif low.startswith("tracking coverage stats:"):
            meta["coverage"] = parse_kv_csv(line.split(":", 1)[1])
        elif low.startswith("tracking coverage targets:"):
            meta["targets"] = parse_kv_csv(line.split(":", 1)[1])
        elif low.startswith("tracking cycle index:"):
            try:
                meta["cycle"] = int(line.split(":", 1)[1].strip())
            except Exception:
                meta["cycle"] = 0
    return meta


def _tracking_local_subject(*parts: str, max_chars: int = 360) -> str:
    """Preserve CJK phrases while removing former research-workflow boilerplate."""
    text = " | ".join(str(part or "").strip() for part in parts if str(part or "").strip())
    for marker in (
        "這些都是待驗證假設", "SignalForge 應研究", "signalforge should research",
        "Imported backlog context", "UNVALIDATED", "do not treat as market truth",
    ):
        idx = text.lower().find(marker.lower())
        if idx >= 0:
            text = text[:idx]
    text = re.sub(r"(?:研究假設[:：]?|目前可能透過\s*待驗證[:：]?|待驗證[:：]?)", " ", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip(" |:-；;。")
    return text[:max_chars]


def _tracking_search_subject(*parts: str) -> str:
    """English/global subject used by most public-web families."""
    return _bounded_query(*parts, max_terms=22, max_chars=340)


def _tracking_profile_key(*parts: str) -> str:
    """Detect a small set of retrieval profiles from the full Founder tracking thesis.

    This does not judge market quality. It only prevents a long parent thesis from being reduced to
    a few generic leading tokens before retrieval. Profiles are allowed to change query wording and
    relevance binding, never market truth.
    """
    text = " ".join(str(part or "") for part in parts).lower()
    ai_anchor = any(x in text for x in (
        "chatgpt", "claude", "gemini", "llm", " ai ", "ai users", "ai assistant", "ai client",
    ))
    link_anchor = any(x in text for x in (
        "public link", "links", " link", "url", "webpage", "website", "youtube", "tiktok",
        "instagram", "reddit", "github issue", "hacker news", "pdf",
    ))
    access_anchor = any(x in text for x in (
        "can't access", "cannot access", "unable to access", "can't read", "cannot read",
        "read it", "read the", "context", "transcript", "copy-paste", "copy paste", "scraper",
        "browser extension", "mcp", "download", "upload",
    ))
    if ai_anchor and link_anchor and access_anchor:
        return "AI_PUBLIC_LINK_ACCESS"
    return "GENERIC"


def _tracking_ai_link_query_specs(*, mode: str, coverage: Mapping[str, Any] | None = None) -> list[tuple[str, str, str, int]]:
    """Queries for the public-link-to-AI access problem family.

    The parent idea is intentionally decomposed into actor/client × source × failure × workaround.
    This avoids the V2.5 failure where the first eight English tokens became the entire query
    (for example: 'AI users struggle to give public links their keep').
    """
    cov = dict(coverage or {})
    def low(key: str, threshold: int) -> bool:
        try:
            return int(cov.get(key) or 0) < threshold
        except Exception:
            return True

    specs: list[tuple[str, str, str, int]] = []
    def add(label: str, family: str, query: str, max_results: int = 20) -> None:
        q = re.sub(r"\s+", " ", query).strip()
        if q and q.lower() not in {x[2].lower() for x in specs}:
            specs.append((label, family, q, max(1, min(int(max_results), 20))))

    # Direct first-person failure language.
    add("AI_LINK_GENERAL_FAILURE", "general_web",
        '(ChatGPT OR Claude OR Gemini) ("can\'t access" OR "cannot access" OR "can\'t read" OR "unable to read") (link OR URL OR webpage OR website)')
    add("AI_LINK_REDDIT_FAILURE", "public_discussions",
        'site:reddit.com (ChatGPT OR Claude OR Gemini) ("can\'t access" OR "can\'t read" OR "cannot open" OR "doesn\'t read") (link OR URL OR webpage)')
    add("AI_LINK_REDDIT_WORKAROUND", "manual_workarounds",
        'site:reddit.com (ChatGPT OR Claude) (link OR URL OR webpage) ("copy paste" OR transcript OR upload OR scraper OR "browser extension" OR MCP OR workaround)')
    add("AI_LINK_HN_DISCUSSION", "practitioner_communities",
        'site:news.ycombinator.com (ChatGPT OR Claude OR LLM) (URL OR link OR webpage) (access OR read OR fetch OR browser OR context)')
    add("AI_LINK_SUPPORT_COMMUNITIES", "vendor_support_communities",
        '(site:community.openai.com OR site:help.openai.com OR site:support.anthropic.com) (link OR URL OR webpage) (access OR read OR browse OR unable OR limitation)')

    # Source-specific failures reveal whether this is one generic pain or several platform adapters.
    add("AI_LINK_VIDEO", "public_discussions",
        '(ChatGPT OR Claude) (YouTube OR TikTok OR Instagram) (link OR URL) ("can\'t access" OR "can\'t read" OR transcript OR captions OR summarize)')
    add("AI_LINK_SOCIAL", "public_discussions",
        '(ChatGPT OR Claude) (Reddit OR X OR Twitter OR Bluesky) (link OR thread OR post) ("can\'t access" OR "can\'t read" OR context OR summarize)')
    add("AI_LINK_DEV_DOC", "practitioner_communities",
        '(ChatGPT OR Claude) ("GitHub issue" OR "pull request" OR PDF OR webpage) (link OR URL) (read OR access OR context OR upload)')

    # Workarounds and product/supply traces.
    add("AI_LINK_WORKAROUNDS", "manual_workarounds",
        '(ChatGPT OR Claude OR Gemini) (link OR URL OR webpage) ("copy paste" OR transcript OR "download upload" OR scraper OR "browser extension" OR MCP)')
    add("AI_LINK_RELATED_PRODUCTS", "related_products",
        '("AI link reader" OR "read links with ChatGPT" OR "Claude read URL" OR "ChatGPT read webpage") (tool OR extension OR MCP OR service OR app OR pricing)')
    add("AI_LINK_EXTENSION_MARKET", "app_marketplaces",
        '(site:chromewebstore.google.com OR site:producthunt.com) (ChatGPT OR Claude OR AI) (webpage OR URL OR link) (reader OR summarize OR access OR browser)')
    add("AI_LINK_GITHUB_TOOLS", "related_products",
        'site:github.com (ChatGPT OR Claude OR LLM) (URL OR link OR webpage) (reader OR fetch OR scrape OR browser OR MCP)')
    add("AI_LINK_REVIEWS", "product_reviews",
        '(ChatGPT OR Claude OR AI) (link reader OR webpage reader OR browser extension OR MCP) (review OR complaint OR limitation OR alternative)')
    add("AI_LINK_ARTICLES_CASES", "research_cases",
        '(ChatGPT OR Claude OR generative AI) (web access OR URL access OR link access OR browsing) (limitation OR workaround OR retrieval OR context)')

    mode_u = str(mode or "DELTA_REFRESH").upper()
    if mode_u == "BROAD_FIRST_PASS":
        return specs[:24]
    if mode_u == "COVERAGE_REFILL":
        return specs[:20]
    # Recurring refresh: keep a healthy mix but do not spam every family on every cycle.
    selected = [specs[0]]
    if low("discussions", 40):
        selected += [x for x in specs if x[1] in {"public_discussions", "practitioner_communities", "vendor_support_communities", "manual_workarounds"}]
    if low("products", 20):
        selected += [x for x in specs if x[1] in {"related_products", "app_marketplaces", "product_reviews"}]
    if low("articles", 15):
        selected += [x for x in specs if x[1] == "research_cases"]
    out: list[tuple[str, str, str, int]] = []
    seen: set[str] = set()
    for row in selected:
        if row[0] in seen:
            continue
        seen.add(row[0]); out.append(row)
    return out[:16]


def _tracking_row_text(row: Mapping[str, Any]) -> str:
    return " ".join(str(row.get(k) or "") for k in ("title", "excerpt", "snippet", "description", "text", "url")).lower()


def _tracking_ai_link_row_relevant(row: Mapping[str, Any]) -> bool:
    """High-recall but thesis-bound gate for AI/public-link access material."""
    text = _tracking_row_text(row)
    ai = any(x in text for x in ("chatgpt", "openai", "claude", "anthropic", "gemini", "llm", "large language model", "ai assistant"))
    source = any(x in text for x in (" link", "url", "webpage", "website", "youtube", "tiktok", "instagram", "reddit", "twitter", " x.com", "bluesky", "github", "hacker news", " pdf", "thread", "post"))
    access = any(x in text for x in (
        "access", "read", "open", "browse", "fetch", "scrap", "extract", "summar", "context", "transcript",
        "caption", "copy paste", "copy-paste", "upload", "download", "extension", "mcp", "inaccessible", "blocked",
    ))
    return ai and source and access


def _tracking_apply_profile_relevance_gate(brief: Mapping[str, Any], *, title: str, description: str) -> dict[str, Any]:
    """Apply only profile-specific thesis binding; generic ideas keep the existing collector gate."""
    out = dict(brief or {})
    if _tracking_profile_key(title, description) != "AI_PUBLIC_LINK_ACCESS":
        return out
    lane_keys = ("human_comments", "similar_products", "repo_solutions", "supporting_evidence", "counter_evidence")
    for lane in lane_keys:
        rows = out.get(lane)
        if isinstance(rows, list):
            out[lane] = [dict(row) for row in rows if isinstance(row, Mapping) and _tracking_ai_link_row_relevant(row)]
    summary = dict(out.get("summary") or {}) if isinstance(out.get("summary"), Mapping) else {}
    human = len(out.get("human_comments") or [])
    products = len(out.get("similar_products") or [])
    repos = len(out.get("repo_solutions") or [])
    supporting = len(out.get("supporting_evidence") or [])
    counter = len(out.get("counter_evidence") or [])
    summary.update({
        "human_comment_count": human,
        "product_or_service_count": products,
        "repo_solution_count": repos,
        "supporting_evidence_count": supporting,
        "counter_evidence_count": counter,
        "useful_result_count": human + products + repos + supporting + counter,
    })
    out["summary"] = summary
    return out


def _tracking_short_human_subject(value: str, *, max_terms: int = 10, max_chars: int = 180) -> str:
    """Turn a search subject into wording closer to how practitioners actually post.

    Product/strategy labels such as Intelligence / Platform / Engine are useful for product search,
    but they hurt forum recall because people usually describe the task or failure instead.  This
    helper only changes retrieval wording; it does not infer market meaning.
    """
    drop = {
        "intelligence", "platform", "engine", "network", "cloud", "passport", "automation",
        "infrastructure", "optimizer", "optimization", "analytics", "solution", "solutions",
        "system", "systems", "software", "tool", "tools", "marketplace", "service", "services",
    }
    tokens: list[str] = []
    seen: set[str] = set()
    for token in re.findall(r"[A-Za-z0-9.+#/_-]+", str(value or "")):
        low = token.lower().strip("-_/.")
        if not low or low in drop or low in {"for", "and", "the", "with", "from", "into", "about", "using"}:
            continue
        if low in seen:
            continue
        seen.add(low)
        tokens.append(token)
        if len(tokens) >= max_terms:
            break
    return " ".join(tokens)[:max_chars].strip()


def _tracking_local_voice_parts(local_subject: str) -> tuple[str, str, str, str]:
    """Extract short local-language facets instead of sending one giant pipe-delimited query."""
    parts = [re.sub(r"\\s+", " ", x).strip() for x in str(local_subject or "").split("|") if x.strip()]
    title = parts[0] if parts else ""
    actor = parts[1] if len(parts) > 1 else ""
    task = parts[2] if len(parts) > 2 else title
    failure = parts[3] if len(parts) > 3 else task
    workaround = parts[6] if len(parts) > 6 else (parts[-1] if len(parts) > 4 else "")
    return actor[:100], task[:150], failure[:170], workaround[:150]


def _tracking_domain_forum_queries(subject_text: str, problem: str, workflow: str) -> list[tuple[str, str]]:
    """Return bounded public practitioner-community search packs for common opportunity domains.

    These are discovery surfaces, not market labels.  A result still has to pass the normal
    relevance gate before it enters the durable material library.
    """
    text = str(subject_text or "").lower()
    problem = _tracking_short_human_subject(problem, max_terms=8) or _tracking_short_human_subject(subject_text, max_terms=8)
    workflow = _tracking_short_human_subject(workflow, max_terms=8) or problem
    packs: list[tuple[str, str]] = []
    if any(x in text for x in ("factory", "manufactur", "machine", "cnc", "oee", "downtime", "industrial", "plc", "工廠", "機台", "製造", "停機")):
        packs.append(("MANUFACTURING", f'(site:reddit.com/r/manufacturing OR site:reddit.com/r/maintenance OR site:reddit.com/r/PLC OR site:reddit.com/r/CNC OR site:practicalmachinist.com OR site:plctalk.net OR site:control.com) {problem}'))
    if any(x in text for x in ("construction", "contractor", "subcontract", "change order", "工地", "工程", "營建", "裝修")):
        packs.append(("CONSTRUCTION", f'(site:reddit.com/r/ConstructionManagers OR site:reddit.com/r/Construction OR site:reddit.com/r/Contractor OR site:contractortalk.com) {problem}'))
    if any(x in text for x in ("warehouse", "freight", "logistics", "shipping", "3pl", "delivery", "物流", "倉庫", "承運")):
        packs.append(("LOGISTICS", f'(site:reddit.com/r/logistics OR site:reddit.com/r/supplychain OR site:reddit.com/r/freightbrokers OR site:thetruckersreport.com) {workflow}'))
    if any(x in text for x in ("ecommerce", "e-commerce", "shopify", "seller", "marketplace", "電商", "賣家", "退貨")):
        packs.append(("ECOMMERCE", f'(site:reddit.com/r/ecommerce OR site:reddit.com/r/shopify OR site:reddit.com/r/FulfillmentByAmazon OR site:community.shopify.com OR site:sellercentral.amazon.com/seller-forums) {problem}'))
    if any(x in text for x in ("teacher", "tutor", "student", "lesson", "course", "school", "老師", "學生", "課程", "家教", "補習")):
        packs.append(("EDUCATION", f'(site:reddit.com/r/Teachers OR site:reddit.com/r/tutors OR site:reddit.com/r/teaching OR site:teachers.net) {workflow}'))
    if any(x in text for x in ("hotel", "hospitality", "booking", "ota", "旅館", "旅宿", "飯店")):
        packs.append(("HOSPITALITY", f'(site:reddit.com/r/askhotels OR site:reddit.com/r/hotels OR site:hoteltechreport.com) {problem}'))
    if any(x in text for x in ("clinic", "dental", "care", "medical", "health", "診所", "照護", "牙科", "醫療")):
        packs.append(("HEALTH_OPERATIONS", f'(site:reddit.com/r/healthIT OR site:reddit.com/r/medicine OR site:reddit.com/r/dentistry OR site:reddit.com/r/nursing) {workflow}'))
    if any(x in text for x in ("creator", "influencer", "ugc", "affiliate", "youtube", "kol", "創作者", "品牌合作", "聯盟")):
        packs.append(("CREATOR", f'(site:reddit.com/r/NewTubers OR site:reddit.com/r/PartneredYoutube OR site:reddit.com/r/influencermarketing OR site:reddit.com/r/marketing) {problem}'))
    if any(x in text for x in ("farm", "agric", "aquaculture", "crop", "農", "水產", "養殖")):
        packs.append(("AGRICULTURE", f'(site:reddit.com/r/farming OR site:reddit.com/r/agriculture OR site:reddit.com/r/aquaculture OR site:newagtalk.com) {workflow}'))
    if any(x in text for x in ("saas", "api", "developer", "software", "bug", "agent", "llm", "工程師", "開發", "程式")):
        packs.append(("SOFTWARE", f'(site:news.ycombinator.com OR site:stackoverflow.com OR site:github.com/issues OR site:reddit.com/r/devops OR site:reddit.com/r/SaaS) {problem}'))
    if not packs:
        packs.append(("SMALL_BUSINESS", f'(site:reddit.com/r/smallbusiness OR site:reddit.com/r/Entrepreneur OR site:quora.com) {problem} {workflow}'))
    return packs[:3]


def _tracking_web_query_specs(
    subjects: list[str] | tuple[str, ...] | str,
    *,
    mode: str,
    local_subject: str = "",
    preferred_families: list[str] | tuple[str, ...] = (),
    cycle_index: int = 0,
    coverage: Mapping[str, Any] | None = None,
    targets: Mapping[str, Any] | None = None,
) -> list[tuple[str, str, str, int]]:
    """Build HumanVoice V2.5 high-recall tracking queries without market judgment.

    V2.5 fixes the main failure exposed by real handoffs: product pages were easy to retrieve while
    practitioner language was under-recalled.  Human-voice searches therefore use short task/pain
    phrases, several question/workaround phrasings, local-language facet queries, and bounded
    domain-specific public forums.  Every returned page still passes relevance + dedupe later.
    """
    if isinstance(subjects, str):
        raw_subjects = [subjects]
    else:
        raw_subjects = list(subjects or [])
    variants: list[str] = []
    for value in raw_subjects:
        value = str(value or "").strip()
        if value and value.lower() not in {x.lower() for x in variants}:
            variants.append(value)
    local_subject = str(local_subject or "").strip()
    if not variants and not local_subject:
        return []
    while len(variants) < 3:
        variants.append(variants[-1] if variants else local_subject)
    core, problem, workflow = variants[:3]
    human_core = _tracking_short_human_subject(core, max_terms=8) or core
    human_problem = _tracking_short_human_subject(problem, max_terms=9) or human_core
    human_workflow = _tracking_short_human_subject(workflow, max_terms=9) or human_problem
    local_actor, local_task, local_failure, local_workaround = _tracking_local_voice_parts(local_subject)

    cov = dict(coverage or {})
    if _tracking_profile_key(" ".join(variants), local_subject) == "AI_PUBLIC_LINK_ACCESS":
        return _tracking_ai_link_query_specs(mode=mode, coverage=cov)

    tgt = {"discussions": 40, "products": 20, "articles": 15, "technical": 6, "total": 90}
    for key, value in dict(targets or {}).items():
        try:
            tgt[key] = max(0, int(value or 0))
        except Exception:
            pass
    def missing(key: str) -> bool:
        try:
            return int(cov.get(key) or 0) < int(tgt.get(key) or 0)
        except Exception:
            return True

    specs: list[tuple[str, str, str, int]] = []
    def add(label: str, family: str, query: str, max_results: int = 20) -> None:
        query = re.sub(r"\\s+", " ", str(query or "")).strip()
        if not query:
            return
        norm = query.lower()
        if any(existing[2].lower() == norm for existing in specs):
            return
        specs.append((label, family, query, max(1, min(int(max_results or 20), 20))))

    def add_discussion_depth() -> None:
        # Reddit / forum queries intentionally sound like practitioner posts, not product names.
        add("TRACKING_REDDIT_PAIN_SHORT", "public_discussions",
            f'site:reddit.com {human_problem} ("anyone else" OR struggle OR frustrating OR issue OR problem OR help)')
        add("TRACKING_REDDIT_HOW_DO_YOU", "public_discussions",
            f'site:reddit.com {human_workflow} ("how do you" OR "what do you use" OR "how are you" OR recommendation)')
        add("TRACKING_REDDIT_WORKAROUND_SHORT", "public_discussions",
            f'site:reddit.com {human_problem} (Excel OR spreadsheet OR manual OR "Google Sheets" OR workaround OR paper)')
        add("TRACKING_REDDIT_ROLE_SHORT", "public_discussions",
            f'site:reddit.com {human_core} (manager OR owner OR operator OR team OR supervisor) (experience OR workflow OR problem)')
        add("TRACKING_PRACTITIONER_LANGUAGE", "practitioner_communities",
            f'{human_problem} ("we use" OR "we track" OR "our process" OR "still using" OR "at my" OR "in our")')
        add("TRACKING_PRACTITIONER_QA", "practitioner_communities",
            f'(site:quora.com OR site:stackexchange.com OR site:news.ycombinator.com) {human_problem} (experience OR workflow OR problem OR recommendation OR alternative)')
        add("TRACKING_PRACTITIONER_SOCIAL", "practitioner_communities",
            f'(site:youtube.com/watch OR site:linkedin.com/posts) {human_workflow} (experience OR workflow OR problem OR manual OR lessons)')
        add("TRACKING_VENDOR_SUPPORT", "vendor_support_communities",
            f'{human_problem} (inurl:support OR inurl:community OR inurl:forum OR inurl:discussions) (issue OR problem OR workaround OR limitation OR help)')
        add("TRACKING_FORUM_THREADS", "vendor_support_communities",
            f'{human_workflow} (intitle:forum OR intitle:community OR "community thread" OR "support forum") (manual OR issue OR workaround OR recommendation)')
        add("TRACKING_GENERIC_DISCUSSION_INDEX", "practitioner_communities",
            f'{human_problem} (forum OR community OR reddit OR discussion) (manual OR experience OR problem OR workaround)')
        for pack_name, pack_query in _tracking_domain_forum_queries(f"{core} {problem} {workflow} {local_subject}", human_problem, human_workflow):
            add(f"TRACKING_DOMAIN_FORUM_{pack_name}", "domain_forums", pack_query)
        if local_subject and _CJK_RE.search(local_subject):
            # Never repeat the full pipe-delimited seed: short local facets are much closer to how
            # people write posts and dramatically reduce query dilution.
            if local_failure:
                add("TRACKING_LOCAL_PAIN", "public_discussions",
                    f'{local_failure} (問題 OR 困擾 OR 抱怨 OR 經驗 OR 怎麼處理 OR 求助)')
            if local_task:
                add("TRACKING_LOCAL_WORKFLOW", "practitioner_communities",
                    f'{local_task} (怎麼做 OR 實務 OR 經驗 OR 流程 OR 工具 OR 推薦)')
            if local_workaround:
                add("TRACKING_LOCAL_WORKAROUND", "manual_workarounds",
                    f'{local_task} {local_workaround} (Excel OR 試算表 OR LINE OR 手動 OR 表單 OR workaround OR 替代)')
            if local_actor and local_task:
                add("TRACKING_LOCAL_ROLE", "domain_forums",
                    f'{local_actor} {local_task} (論壇 OR 社群 OR 討論 OR 經驗 OR 使用心得)')

    def add_review_depth() -> None:
        add("TRACKING_PRODUCT_REVIEWS_G2", "product_reviews",
            f'(site:g2.com OR site:capterra.com OR site:getapp.com) {human_problem} (review OR complaint OR pros OR cons OR missing OR limitation)')
        add("TRACKING_PRODUCT_REVIEWS_PRO", "product_reviews",
            f'(site:trustradius.com OR site:softwareadvice.com OR site:gartner.com/reviews) {human_problem} (review OR cons OR limitation OR alternative OR workaround)')
        add("TRACKING_PRODUCT_REVIEWS_OPEN", "product_reviews",
            f'(site:trustpilot.com OR site:producthunt.com OR site:sourceforge.net/software) {human_workflow} (review OR complaint OR alternative OR limitation OR missing)')
        add("TRACKING_REVIEW_USER_LANGUAGE", "product_reviews",
            f'{human_problem} ("pros and cons" OR "wish it" OR "missing feature" OR "we still" OR "workaround") review')

    def add_product_depth() -> None:
        add("TRACKING_RELATED_PRODUCTS_1", "related_products",
            f'{core} (software OR service OR platform OR tool OR vendor OR solution OR marketplace OR equipment) (pricing OR demo OR trial OR features)')
        add("TRACKING_RELATED_PRODUCTS_2", "related_products",
            f'{problem} (software OR app OR SaaS OR service OR system OR platform) (pricing OR alternatives OR reviews OR demo)')
        add("TRACKING_APP_MARKETPLACES_1", "app_marketplaces",
            f'(site:apps.shopify.com OR site:marketplace.atlassian.com OR site:appexchange.salesforce.com) {workflow} (app OR integration OR reviews OR pricing)')
        add("TRACKING_APP_MARKETPLACES_2", "app_marketplaces",
            f'(site:appsource.microsoft.com OR site:workspace.google.com/marketplace OR site:wordpress.org/plugins OR site:chromewebstore.google.com) {problem} (app OR plugin OR extension OR reviews)')
        if local_subject and _CJK_RE.search(local_subject):
            add("TRACKING_LOCAL_PRODUCTS", "related_products",
                f'{local_task or local_failure or local_subject[:120]} (軟體 OR 系統 OR 平台 OR 工具 OR 服務 OR 方案) (價格 OR 功能 OR 試用 OR 廠商)')

    def add_workaround_depth() -> None:
        add("TRACKING_MANUAL_WORKAROUNDS_1", "manual_workarounds",
            f'{human_workflow} (manual OR spreadsheet OR Excel OR email OR WhatsApp OR LINE OR "Google Sheets" OR workaround) (workflow OR tracking OR reconciliation OR template)')
        add("TRACKING_MANUAL_WORKAROUNDS_2", "manual_workarounds",
            f'{human_problem} (template OR spreadsheet OR checklist OR "Google Form" OR CSV OR copy paste OR manual process OR paper)')
        add("TRACKING_MANUAL_WORKAROUNDS_DISCUSSION", "manual_workarounds",
            f'{human_problem} ("still use Excel" OR "still using Excel" OR spreadsheet OR paper OR "manual entry" OR "double entry")')

    def add_article_depth() -> None:
        add("TRACKING_RESEARCH_CASES", "research_cases",
            f'{problem} (research OR study OR report OR survey OR "case study" OR "customer story" OR implementation OR industry report)')
        add("TRACKING_ACADEMIC", "academic_sources",
            f'(site:arxiv.org OR site:pubmed.ncbi.nlm.nih.gov OR site:ssrn.com OR site:researchgate.net) {problem}')
        add("TRACKING_B2B_OPERATIONAL_SIGNALS", "b2b_operational_signals",
            f'{workflow} (SOP OR operations OR implementation OR workflow OR consultant OR "best practice" OR checklist OR template)')
        add("TRACKING_JOB_PROCUREMENT_SIGNALS", "job_procurement_signals",
            f'{problem} (RFP OR tender OR procurement OR specification OR "job description" OR hiring OR requirements)')

    mode = str(mode or "DELTA_REFRESH").upper()
    if mode == "BROAD_FIRST_PASS":
        add("TRACKING_GENERAL_WEB", "general_web", core, 20)
        if local_subject and _CJK_RE.search(local_subject):
            add("TRACKING_LOCAL_LANGUAGE", "local_language", local_task or local_failure or local_subject[:150], 20)
        add_discussion_depth()
        add_review_depth()
        add_product_depth()
        add_workaround_depth()
        add_article_depth()
        return specs[:38]

    if mode == "COVERAGE_REFILL":
        add("TRACKING_GENERAL_WEB_REFILL", "general_web", problem, 20)
        if missing("discussions"):
            add_discussion_depth()
            add_review_depth()
            add_workaround_depth()
        if missing("products"):
            add_product_depth()
        if missing("articles") or missing("total"):
            add_article_depth()
        if missing("total"):
            add_workaround_depth()
        return specs[:30]

    # Recurring refresh: human voice remains a standing priority until the collector has depth.
    add("TRACKING_GENERAL_WEB", "general_web", core, 20)
    if missing("discussions"):
        add("TRACKING_REDDIT_REFRESH_PAIN", "public_discussions",
            f'site:reddit.com {human_problem} (problem OR experience OR workaround OR "how do you" OR help)', 20)
        add("TRACKING_REDDIT_REFRESH_WORKFLOW", "public_discussions",
            f'site:reddit.com {human_workflow} ("what do you use" OR manual OR Excel OR spreadsheet OR recommendation)', 20)
        add("TRACKING_REVIEW_REFRESH", "product_reviews",
            f'(site:g2.com OR site:capterra.com OR site:trustradius.com OR site:softwareadvice.com OR site:trustpilot.com) {human_problem} (review OR complaint OR limitation OR alternative)', 20)
        add("TRACKING_SUPPORT_REFRESH", "vendor_support_communities",
            f'{human_problem} (inurl:support OR inurl:community OR inurl:forum) (issue OR workaround OR limitation)', 20)
        for pack_name, pack_query in _tracking_domain_forum_queries(f"{core} {problem} {workflow} {local_subject}", human_problem, human_workflow)[:1]:
            add(f"TRACKING_DOMAIN_REFRESH_{pack_name}", "domain_forums", pack_query, 20)
    add("TRACKING_RELATED_PRODUCTS", "related_products",
        f'{core} (software OR service OR platform OR tool OR vendor OR solution) (pricing OR product OR features)', 20)

    family_query = {
        "public_discussions": f'site:reddit.com {human_problem} (workaround OR experience OR "what do you use" OR complaint)',
        "practitioner_communities": f'(site:quora.com OR site:stackexchange.com OR site:youtube.com/watch OR site:linkedin.com/posts) {human_problem} (experience OR workflow OR recommendation)',
        "vendor_support_communities": f'{human_problem} (inurl:support OR inurl:community OR inurl:forum OR inurl:discussions) (issue OR workaround OR limitation)',
        "domain_forums": _tracking_domain_forum_queries(f"{core} {problem} {workflow} {local_subject}", human_problem, human_workflow)[0][1],
        "product_reviews": f'(site:g2.com OR site:capterra.com OR site:trustradius.com OR site:softwareadvice.com OR site:trustpilot.com) {human_problem} (review OR complaint OR pros OR cons)',
        "app_marketplaces": f'(site:apps.shopify.com OR site:marketplace.atlassian.com OR site:appexchange.salesforce.com OR site:appsource.microsoft.com) {workflow} (app OR integration OR reviews)',
        "manual_workarounds": f'{human_workflow} (manual OR spreadsheet OR Excel OR email OR WhatsApp OR LINE OR "Google Sheets" OR workaround)',
        "research_cases": f'{problem} (research OR study OR report OR "case study" OR implementation)',
        "academic_sources": f'(site:arxiv.org OR site:pubmed.ncbi.nlm.nih.gov OR site:ssrn.com) {problem}',
        "b2b_operational_signals": f'{workflow} (SOP OR operations OR workflow OR consultant OR checklist)',
        "job_procurement_signals": f'{problem} (RFP OR tender OR procurement OR "job description" OR requirements)',
        "related_products": f'{core} (software OR service OR platform OR tool OR solution) (pricing OR features)',
    }
    for family in preferred_families:
        query = family_query.get(str(family or ""))
        if query:
            add(f"TRACKING_ADAPTIVE_{str(family).upper()}", str(family), query, 20)
        if len(specs) >= 13:
            break
    exploration = [
        "domain_forums", "vendor_support_communities", "practitioner_communities", "product_reviews",
        "app_marketplaces", "job_procurement_signals", "academic_sources", "research_cases",
        "manual_workarounds", "public_discussions",
    ]
    exp = exploration[int(cycle_index or 0) % len(exploration)]
    if exp in family_query:
        add(f"TRACKING_EXPLORATION_{exp.upper()}", exp, family_query[exp], 20)
    return specs[:16]

def _merge_research_briefs(briefs: list[Mapping[str, Any]]) -> dict[str, Any]:
    if not briefs:
        return {}
    out = dict(briefs[0])
    lane_keys = ("human_comments", "similar_products", "repo_solutions", "supporting_evidence", "counter_evidence")
    for lane in lane_keys:
        merged: list[dict[str, Any]] = []
        seen: set[str] = set()
        for brief in briefs:
            rows = brief.get(lane)
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, Mapping):
                    continue
                url = str(row.get("url") or "").strip().lower()
                key = url or f"{row.get('source')}|{row.get('title')}|{str(row.get('excerpt') or '')[:220]}".lower()
                if not key or key in seen:
                    continue
                seen.add(key)
                merged.append(dict(row))
        out[lane] = merged[:100]
    gaps: list[str] = []
    gap_seen: set[str] = set()
    for brief in briefs:
        for value in brief.get("gaps") or []:
            text = str(value or "").strip()
            if text and text.lower() not in gap_seen:
                gap_seen.add(text.lower())
                gaps.append(text)
    out["gaps"] = gaps[:24]

    successful: list[str] = []
    successful_seen: set[str] = set()
    failed: list[dict[str, Any]] = []
    failed_seen: set[str] = set()
    search_out = dict(out.get("search") or {}) if isinstance(out.get("search"), Mapping) else {}
    for brief in briefs:
        search = brief.get("search") if isinstance(brief.get("search"), Mapping) else {}
        for source in search.get("successful_sources") or []:
            name = str(source or "").strip()
            if name and name.lower() not in successful_seen:
                successful_seen.add(name.lower())
                successful.append(name)
        for row in search.get("failed_sources") or []:
            if not isinstance(row, Mapping):
                continue
            key = json.dumps(dict(row), sort_keys=True, ensure_ascii=False, default=str)
            if key in failed_seen:
                continue
            failed_seen.add(key)
            failed.append(dict(row))
    search_out["successful_sources"] = successful
    search_out["failed_sources"] = failed[:24]
    search_out["query_run_count"] = len(briefs)
    out["search"] = search_out

    summary = dict(out.get("summary") or {}) if isinstance(out.get("summary"), Mapping) else {}
    human = len(out.get("human_comments") or [])
    products = len(out.get("similar_products") or [])
    repos = len(out.get("repo_solutions") or [])
    supporting = len(out.get("supporting_evidence") or [])
    counter = len(out.get("counter_evidence") or [])
    summary.update({
        "human_comment_count": human,
        "product_or_service_count": products,
        "repo_solution_count": repos,
        "supporting_evidence_count": supporting,
        "counter_evidence_count": counter,
        "useful_result_count": human + products + repos + supporting + counter,
    })
    out["summary"] = summary
    return out

def _research_lane_from_description(description: str) -> str:
    text = str(description or "").lower()
    if "research focus: how people solve this today" in text:
        return "CURRENT_SOLUTIONS"
    if "research focus: paid dissatisfaction" in text:
        return "PAID_DISSATISFACTION"
    if "research focus: buyer and payer reality" in text:
        return "BUYER_PAYER_WTP"
    if "research focus: try to falsify the opportunity" in text:
        return "COUNTEREVIDENCE"
    return "BASELINE"


def _base_problem_description(description: str) -> str:
    text = str(description or "")
    cut_points = []
    for marker in ("\n\nPreviously retrieved research anchors", "\n\nResearch focus:", "\n\nTracking mode:"):
        idx = text.find(marker)
        if idx >= 0:
            cut_points.append(idx)
    if cut_points:
        text = text[: min(cut_points)]
    return text.strip()


def _profile_hint_terms(title: str, description: str) -> str:
    """Return routing-only English hints; never evidence and never market truth."""
    text = f"{title} {description}".lower()
    course_tokens = (
        "排課", "堂數", "補課", "請假", "出缺席", "才藝", "家教", "課程", "教練", "學生", "家長",
        "class credits", "lesson package", "make-up class", "attendance", "tutoring", "enrichment classes",
    )
    operator_tokens = ("業者", "工作室", "老師", "business owner", "studio", "teacher", "coach")
    if any(x in text for x in course_tokens) and any(x in text for x in operator_tokens):
        return "small business service business class scheduling lesson credits attendance booking"
    restaurant_tokens = ("餐廳", "外送", "restaurant", "delivery platform")
    if any(x in text for x in restaurant_tokens):
        return "small business service business restaurant operations"
    industrial_tokens = ("工廠", "機台", "停機", "factory", "machine downtime", "manufacturing")
    if any(x in text for x in industrial_tokens):
        return "industrial manufacturing operator workflow"
    return ""


def _lane_focus_terms(lane: str) -> str:
    return {
        "BASELINE": "",
        "CURRENT_SOLUTIONS": "workaround alternative competitor software tool product manual workflow",
        "PAID_DISSATISFACTION": "paid subscription pricing complaint manual workaround switching rework",
        "BUYER_PAYER_WTP": "buyer payer pricing cost budget purchase subscription switching",
        "COUNTEREVIDENCE": "already solved built in native feature mature alternative no longer problem",
    }.get(str(lane or "").upper(), "")


def _bounded_query(*parts: str, max_terms: int = 26, max_chars: int = 420) -> str:
    tokens: list[str] = []
    seen: set[str] = set()
    for part in parts:
        for token in re.findall(r"[A-Za-z0-9.+#/_-]+", str(part or "")):
            low = token.lower()
            if not low or low in seen:
                continue
            seen.add(low)
            tokens.append(token)
            if len(tokens) >= max_terms:
                break
        if len(tokens) >= max_terms:
            break
    return " ".join(tokens)[:max_chars].strip()


def _query_run_source_count(run: Mapping[str, Any]) -> int:
    successful = run.get("successful_sources") if isinstance(run.get("successful_sources"), list) else []
    failed = run.get("failed_sources") if isinstance(run.get("failed_sources"), list) else []
    return len(successful) + len(failed)


def _runtime_env_value(name: str) -> str:
    """Read live credentials even when Uvicorn was started before Windows User env changed.

    PowerShell's SetEnvironmentVariable(..., "User") updates HKCU, but an already-running parent
    process does not inherit the new value. Reading HKCU on demand makes the provider self-heal
    without storing secrets in the repo or requiring the Founder to understand process inheritance.
    """
    value = str(os.environ.get(name) or "").strip()
    if value:
        return value
    if os.name != "nt":
        return ""
    try:
        import winreg  # type: ignore
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as key:
            raw, _ = winreg.QueryValueEx(key, name)
        return str(raw or "").strip()
    except Exception:
        return ""


def _general_web_provider() -> tuple[str | None, str | None]:
    """Resolve a mature general-web retrieval provider without changing Founder workflow.

    Serper is preferred for HOTFIX6 because the Founder can use its Google Search API without
    adding a payment method. Tavily and Brave remain swappable fallbacks. Missing credentials are
    represented explicitly in Research Trace; specialist-only silence never becomes market absence.
    """
    preference = (_runtime_env_value("SIGNALFORGE_WEB_SEARCH_PROVIDER") or "auto").lower()
    serper = _runtime_env_value("SERPER_API_KEY")
    tavily = _runtime_env_value("TAVILY_API_KEY")
    brave = _runtime_env_value("BRAVE_SEARCH_API_KEY")
    if preference in {"auto", "serper"} and serper:
        return "SERPER_WEB_SEARCH", serper
    if preference in {"auto", "tavily"} and tavily:
        return "TAVILY_WEB_SEARCH", tavily
    if preference in {"auto", "brave"} and brave:
        return "BRAVE_WEB_SEARCH", brave
    if preference == "serper":
        return None, "SERPER_API_KEY_NOT_CONFIGURED"
    if preference == "tavily":
        return None, "TAVILY_API_KEY_NOT_CONFIGURED"
    if preference == "brave":
        return None, "BRAVE_SEARCH_API_KEY_NOT_CONFIGURED"
    return None, "GENERAL_WEB_PROVIDER_NOT_CONFIGURED"


def _general_web_search(query: str, *, max_results: int = 10) -> dict[str, Any]:
    provider, credential = _general_web_provider()
    if provider is None:
        return {
            "source": "GENERAL_WEB_SEARCH",
            "status": "SKIPPED",
            "query": query,
            "count": 0,
            "traces": [],
            "transport": {"configured": False},
            "error": credential or "GENERAL_WEB_PROVIDER_NOT_CONFIGURED",
        }
    started = time.monotonic()
    try:
        if provider == "SERPER_WEB_SEARCH":
            body = json.dumps({
                "q": query,
                "num": max(1, min(int(max_results or 10), 20)),
            }).encode("utf-8")
            req = urllib.request.Request(
                "https://google.serper.dev/search",
                data=body,
                method="POST",
                headers={
                    "X-API-KEY": credential,
                    "Content-Type": "application/json",
                    "User-Agent": "SignalForge/2.5 TrackingHumanVoice",
                },
            )
            with urllib.request.urlopen(req, timeout=8.0) as response:
                payload = json.loads(response.read().decode("utf-8", errors="replace"))
            results = payload.get("organic") if isinstance(payload, Mapping) else []
            traces: list[dict[str, Any]] = []
            for row in results if isinstance(results, list) else []:
                if not isinstance(row, Mapping):
                    continue
                url = _traceable_http_url(row.get("link"))
                if not url:
                    continue
                traces.append({
                    "source": provider,
                    "title": str(row.get("title") or "").strip()[:300],
                    "excerpt": str(row.get("snippet") or "").strip()[:2200],
                    "url": url,
                    "search_position": row.get("position"),
                    "truth_status": "UNVALIDATED_SEARCH_TRACE",
                })
            return {
                "source": provider,
                "status": "SUCCESS",
                "query": query,
                "count": len(traces),
                "traces": traces,
                "transport": {"http_status": 200, "ms": int((time.monotonic() - started) * 1000)},
                "error": None,
            }

        if provider == "TAVILY_WEB_SEARCH":
            body = json.dumps({
                "query": query,
                "search_depth": "basic",
                "max_results": max(1, min(int(max_results or 10), 15)),
                "topic": "general",
                "include_answer": False,
                "include_raw_content": False,
                "include_images": False,
                "auto_parameters": False,
            }).encode("utf-8")
            req = urllib.request.Request(
                "https://api.tavily.com/search",
                data=body,
                method="POST",
                headers={
                    "Authorization": f"Bearer {credential}",
                    "Content-Type": "application/json",
                    "User-Agent": "SignalForge/2.5 TrackingHumanVoice",
                },
            )
            with urllib.request.urlopen(req, timeout=8.0) as response:
                payload = json.loads(response.read().decode("utf-8", errors="replace"))
            results = payload.get("results") if isinstance(payload, Mapping) else []
            traces: list[dict[str, Any]] = []
            for row in results if isinstance(results, list) else []:
                if not isinstance(row, Mapping):
                    continue
                url = _traceable_http_url(row.get("url"))
                if not url:
                    continue
                traces.append({
                    "source": provider,
                    "title": str(row.get("title") or "").strip()[:300],
                    "excerpt": str(row.get("content") or "").strip()[:2200],
                    "url": url,
                    "search_score": row.get("score"),
                    "truth_status": "UNVALIDATED_SEARCH_TRACE",
                })
            return {
                "source": provider,
                "status": "SUCCESS",
                "query": query,
                "count": len(traces),
                "traces": traces,
                "transport": {"http_status": 200, "ms": int((time.monotonic() - started) * 1000)},
                "error": None,
            }

        encoded = urllib.parse.urlencode({"q": query, "count": max(1, min(int(max_results or 10), 20)), "safesearch": "moderate"})
        req = urllib.request.Request(
            f"https://api.search.brave.com/res/v1/web/search?{encoded}",
            headers={
                "Accept": "application/json",
                "X-Subscription-Token": credential,
                "User-Agent": "SignalForge/2.5 TrackingHumanVoice",
            },
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=8.0) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
        web = payload.get("web") if isinstance(payload, Mapping) and isinstance(payload.get("web"), Mapping) else {}
        results = web.get("results") if isinstance(web, Mapping) else []
        traces = []
        for row in results if isinstance(results, list) else []:
            if not isinstance(row, Mapping):
                continue
            url = _traceable_http_url(row.get("url"))
            if not url:
                continue
            traces.append({
                "source": provider,
                "title": str(row.get("title") or "").strip()[:300],
                "excerpt": str(row.get("description") or "").strip()[:2200],
                "url": url,
                "truth_status": "UNVALIDATED_SEARCH_TRACE",
            })
        return {
            "source": provider,
            "status": "SUCCESS",
            "query": query,
            "count": len(traces),
            "traces": traces,
            "transport": {"http_status": 200, "ms": int((time.monotonic() - started) * 1000)},
            "error": None,
        }
    except urllib.error.HTTPError as exc:
        return {
            "source": provider,
            "status": "FAILED",
            "query": query,
            "count": 0,
            "traces": [],
            "transport": {"http_status": int(exc.code or 0), "ms": int((time.monotonic() - started) * 1000)},
            "error": f"HTTP_{exc.code}",
        }
    except Exception as exc:
        return {
            "source": provider,
            "status": "FAILED",
            "query": query,
            "count": 0,
            "traces": [],
            "transport": {"ms": int((time.monotonic() - started) * 1000)},
            "error": f"{type(exc).__name__}: {str(exc)[:220]}",
        }


async def _research_deterministic_batch(title: str, description: str) -> dict[str, Any]:
    """Run bounded, auditable public-source research without per-item LLM query calls.

    Tracking Deep Discovery V2.3 preserves routing/grounding guarantees and widens collection:
      1) every research lane emits a lane-specific retrieval probe;
      2) non-developer ideas cannot silently produce SEARCH_FAILED with zero source attempts;
      3) the trace records every executed query and the sources that actually answered/failed.
    """
    import processors.signalforge_founder_idea_loop as idea_loop

    def _run() -> dict[str, Any]:
        run_started = time.monotonic()
        lane = _research_lane_from_description(description)
        tracking_meta = _tracking_prompt_metadata(description)
        base_description = _base_problem_description(description)
        if str(tracking_meta.get("seed") or "").strip():
            base_description = _tracking_local_subject(str(tracking_meta.get("seed") or ""))
        base_hypothesis = f"{title} {base_description}".strip()
        profile_hint = _profile_hint_terms(title, base_description)

        bridged = idea_loop._bridged_founder_query(base_hypothesis)
        base_relevance = idea_loop._bridged_relevance_query(base_hypothesis, bridged) or bridged or base_hypothesis
        fallback = _fallback_english_query(title, base_description, bridged or base_hypothesis)
        if profile_hint:
            fallback = _bounded_query(fallback, profile_hint)
        lane_terms = _lane_focus_terms(lane)
        base_retrieval = fallback if (fallback and _CJK_RE.search(base_hypothesis)) else (bridged or base_hypothesis)
        lane_retrieval = _bounded_query(base_retrieval, profile_hint, lane_terms) or base_retrieval
        semantic_hypothesis = " ".join(x for x in (base_relevance, profile_hint) if x).strip()

        query_specs: list[tuple[str, str, str]] = [(
            "PRIMARY" if lane == "BASELINE" else f"LANE_FOCUS_{lane}",
            lane_retrieval,
            base_relevance,
        )]
        briefs: list[Mapping[str, Any]] = []
        fresh_runs: list[Mapping[str, Any]] = []
        query_runs: list[dict[str, Any]] = []

        def _record_run(label: str, retrieval: str, relevance: str, fresh: Mapping[str, Any], brief: Mapping[str, Any], probe_ms: int, *, floor: bool = False) -> None:
            search_meta = brief.get("search") if isinstance(brief.get("search"), Mapping) else {}
            query_runs.append({
                "label": label,
                "research_lane": lane,
                "retrieval_query": retrieval,
                "relevance_query": relevance,
                "probe_ms": probe_ms,
                "collection_status": str(fresh.get("status") or ""),
                "useful_result_count": _brief_useful_count(brief),
                "successful_sources": list(search_meta.get("successful_sources") or []),
                "failed_sources": list(search_meta.get("failed_sources") or [])[:12],
                "public_floor": bool(floor),
            })

        def run_probe(label: str, retrieval: str, relevance: str) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
            probe_started = time.monotonic()
            fresh = idea_loop.run_founder_observation_probe(
                title,
                base_description,
                search_query_override=retrieval or None,
                relevance_query_override=relevance or retrieval or None,
                semantic_hypothesis_override=semantic_hypothesis or relevance or retrieval or None,
            )
            probe_ms = int((time.monotonic() - probe_started) * 1000)
            fresh_summary = idea_loop.summarize_idea_research_probe(fresh)
            brief = idea_loop.build_founder_research_brief(
                title=title,
                description=base_description,
                fresh=fresh,
                fresh_summary=fresh_summary,
            )
            _record_run(label, retrieval, relevance, fresh, brief, probe_ms)
            return fresh, brief

        def run_general_web(label: str, retrieval: str, relevance: str, *, family: str = "general_web", max_results: int = 12) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
            probe_started = time.monotonic()
            source = _general_web_search(retrieval, max_results=max_results)
            source_status = str(source.get("status") or "").upper()
            collection_status = "PASS" if source_status == "SUCCESS" else "FAILED"
            fresh: dict[str, Any] = {
                "engine_version": getattr(idea_loop, "ENGINE_VERSION", "FIX5"),
                "status": collection_status,
                "founder_query": base_hypothesis,
                "relevance_query": semantic_hypothesis or relevance,
                "queries": [retrieval],
                "search_query_used": retrieval,
                "base_source_policy": {
                    "source_profile": "MATURE_GENERAL_WEB_PROVIDER",
                    "base_sources": [str(source.get("source") or "GENERAL_WEB_SEARCH")],
                    "developer_heavy_sources_suppressed": False,
                    "absence_authority": source_status == "SUCCESS",
                    "market_truth_writes": 0,
                },
                "language_coverage": "SUPPORTED_BY_PROVIDER_AND_CURRENT_QUERY_BRIDGE",
                "sources": [source],
                "traces": [dict(row) for row in (source.get("traces") or []) if isinstance(row, Mapping)][:160],
                "truth_boundary": "GENERAL_WEB_RESULTS_ARE_DISCOVERY_TRACES;_THEY_MUST_STILL_PASS_EVIDENCE_TRUST_BEFORE_COUNTING",
            }
            fresh_summary = idea_loop.summarize_idea_research_probe(fresh)
            legacy_brief = idea_loop.build_founder_research_brief(
                title=title,
                description=base_description,
                fresh=fresh,
                fresh_summary=fresh_summary,
            )
            direct_brief = _tracking_direct_brief(source, family=family, query=retrieval)
            brief = _merge_research_briefs([legacy_brief, direct_brief])
            probe_ms = int((time.monotonic() - probe_started) * 1000)
            _record_run(label, retrieval, relevance, fresh, brief, probe_ms)
            query_runs[-1]["tracking_family"] = family
            query_runs[-1]["raw_result_count"] = int(source.get("count") or 0)
            return fresh, brief

        def run_public_floor(label: str, retrieval: str, relevance: str) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
            """Use stable public APIs when source-profile routing produced no successful source.

            This is intentionally a discovery floor, not absence authority. It guarantees that
            'searched' means an actual network source was attempted. HN can surface operator/founder
            discussion; GitHub repositories can surface existing software alternatives. Relevance
            gates still decide whether any returned trace counts as evidence.
            """
            probe_started = time.monotonic()
            searchers = [idea_loop._search_hn, idea_loop._search_github_repositories]
            sources = [idea_loop._run_searcher(searcher, retrieval) for searcher in searchers]
            traces: list[dict[str, Any]] = []
            seen: set[tuple[str, str]] = set()
            for source in sources:
                for trace in source.get("traces") or []:
                    if not isinstance(trace, Mapping):
                        continue
                    key = (str(trace.get("url") or ""), str(trace.get("title") or "").lower())
                    if key in seen:
                        continue
                    seen.add(key)
                    traces.append(dict(trace))
            success = [x for x in sources if x.get("status") == "SUCCESS"]
            failed = [x for x in sources if x.get("status") != "SUCCESS"]
            collection_status = "PASS" if success and not failed else ("PARTIAL" if success else "FAILED")
            fresh: dict[str, Any] = {
                "engine_version": getattr(idea_loop, "ENGINE_VERSION", "FIX5"),
                "status": collection_status,
                "founder_query": base_hypothesis,
                "relevance_query": semantic_hypothesis or relevance,
                "queries": [retrieval],
                "search_query_used": retrieval,
                "base_source_policy": {
                    "source_profile": "AUDITABLE_PUBLIC_DISCOVERY_FLOOR",
                    "base_sources": ["HACKER_NEWS_ALGOLIA", "GITHUB_REPOSITORIES"],
                    "general_web_provider": _general_web_provider()[0],
                    "general_web_configured": _general_web_provider()[0] is not None,
                    "developer_heavy_sources_suppressed": False,
                    "absence_authority": False,
                    "market_truth_writes": 0,
                },
                "language_coverage": "SUPPORTED_BY_CURRENT_QUERY_BRIDGE",
                "sources": sources,
                "traces": traces[:160],
                "truth_boundary": "PUBLIC_DISCOVERY_FLOOR_IS_DISCOVERY_ONLY;_ZERO_RESULTS_CANNOT_PROVE_MARKET_ABSENCE",
            }
            fresh_summary = idea_loop.summarize_idea_research_probe(fresh)
            brief = idea_loop.build_founder_research_brief(
                title=title,
                description=base_description,
                fresh=fresh,
                fresh_summary=fresh_summary,
            )
            probe_ms = int((time.monotonic() - probe_started) * 1000)
            _record_run(label, retrieval, relevance, fresh, brief, probe_ms, floor=True)
            return fresh, brief

        first_fresh, first_brief = run_probe(*query_specs[0])
        fresh_runs.append(first_fresh)
        briefs.append(first_brief)
        first_status = idea_loop._research_status(collection_status=str(first_fresh.get("status") or ""), research_brief=first_brief)

        # A second English-market pass is useful for CJK Founder ideas when the first pass is sparse.
        # The lane terms are preserved so BUYER/COUNTER/etc. cannot collapse back into BASELINE.
        if fallback and _CJK_RE.search(base_hypothesis) and (str(first_status).upper() == "SEARCH_FAILED" or _brief_useful_count(first_brief) < 2):
            fallback_retrieval = _bounded_query(fallback, profile_hint, lane_terms) or fallback
            if fallback_retrieval.lower() != lane_retrieval.lower():
                second_fresh, second_brief = run_probe("FALLBACK_ENGLISH_MARKET_TERMS", fallback_retrieval, base_relevance)
                fresh_runs.append(second_fresh)
                briefs.append(second_brief)

        # Tracking Coverage V2.2: use the structured tracking seed instead of the old imported
        # research instructions. Keep a local-language query for CJK ideas and a deterministic
        # English/global bridge for public communities, review sites and B2B traces.
        expansion_mode = str(tracking_meta.get("mode") or "DELTA_REFRESH").upper()
        broad_source_expansion = expansion_mode == "BROAD_FIRST_PASS"
        clean_seed = _tracking_local_subject(tracking_meta.get("seed") or title, base_description)
        seed_segments = [seg.strip() for seg in clean_seed.split("|") if seg.strip()]
        local_variants: list[str] = []
        if seed_segments:
            local_variants.append(" | ".join(seed_segments[:3]))
            if len(seed_segments) >= 4:
                local_variants.append(" | ".join(seed_segments[2:5]))
            if len(seed_segments) >= 6:
                local_variants.append(" | ".join(seed_segments[3:7]))
        if clean_seed and clean_seed not in local_variants:
            local_variants.insert(0, clean_seed)
        if not local_variants:
            local_variants = [title]

        global_variants: list[str] = []
        base_bridge_hint = bridged or fallback or base_hypothesis
        for local_variant in local_variants[:3]:
            bridge = _fallback_english_query(title, local_variant, base_bridge_hint)
            subject_variant = _tracking_search_subject(bridge, profile_hint)
            if not subject_variant:
                subject_variant = _tracking_search_subject(bridge or fallback or lane_retrieval or base_bridge_hint, profile_hint)
            if subject_variant and subject_variant.lower() not in {x.lower() for x in global_variants}:
                global_variants.append(subject_variant)
        if not global_variants:
            global_bridge = _fallback_english_query(title, clean_seed, base_bridge_hint)
            global_variants = [_tracking_search_subject(global_bridge or fallback or lane_retrieval or base_bridge_hint, profile_hint) or _tracking_search_subject(title) or clean_seed]

        fanout_specs = _tracking_web_query_specs(
            global_variants,
            mode=expansion_mode,
            local_subject=clean_seed,
            preferred_families=list(tracking_meta.get("preferred") or []),
            cycle_index=int(tracking_meta.get("cycle") or 0),
            coverage=tracking_meta.get("coverage") if isinstance(tracking_meta.get("coverage"), Mapping) else {},
            targets=tracking_meta.get("targets") if isinstance(tracking_meta.get("targets"), Mapping) else {},
        )
        for label, family, query, max_results in fanout_specs:
            web_fresh, web_brief = run_general_web(
                label,
                query,
                base_relevance,
                family=family,
                max_results=max_results,
            )
            fresh_runs.append(web_fresh)
            briefs.append(web_brief)

        # WideNet: HN/GitHub are direct public APIs and complement web-index coverage. Run one
        # bounded sweep while human/technical coverage is thin, even when Serper itself is healthy.
        cov = tracking_meta.get("coverage") if isinstance(tracking_meta.get("coverage"), Mapping) else {}
        if int(cov.get("discussions") or 0) < 20 or int(cov.get("technical") or 0) < 4:
            floor_query = _bounded_query(global_variants[0] if global_variants else (fallback or bridged or base_hypothesis), profile_hint)
            floor_fresh, floor_brief = run_public_floor("TRACKING_PUBLIC_API_SWEEP", floor_query, base_relevance)
            fresh_runs.append(floor_fresh)
            briefs.append(floor_brief)

        # Product invariant: a Founder-visible SEARCH_FAILED must never mean 'router attempted zero sources'.
        # If domain routing has no healthy source, execute a bounded public discovery floor.
        successful_before_floor = {
            str(source)
            for run in query_runs
            for source in (run.get("successful_sources") or [])
            if str(source).strip()
        }
        if len(successful_before_floor) < 2:
            floor_query = _bounded_query(fallback or bridged or base_hypothesis, profile_hint, lane_terms)
            floor_fresh, floor_brief = run_public_floor("PUBLIC_DISCOVERY_FLOOR", floor_query, base_relevance)
            fresh_runs.append(floor_fresh)
            briefs.append(floor_brief)

        brief = _merge_research_briefs(briefs)
        brief = _tracking_apply_profile_relevance_gate(brief, title=title, description=clean_seed or base_description)
        successful_all = list((brief.get("search") or {}).get("successful_sources") or []) if isinstance(brief.get("search"), Mapping) else []
        failed_all = list((brief.get("search") or {}).get("failed_sources") or []) if isinstance(brief.get("search"), Mapping) else []
        final_collection_status = "PASS" if successful_all and not failed_all else ("PARTIAL" if successful_all else "FAILED")
        status = idea_loop._research_status(collection_status=final_collection_status, research_brief=brief)

        page_check_started = time.monotonic()
        page_checks = _audit_original_pages(brief)
        page_check_ms = int((time.monotonic() - page_check_started) * 1000)
        source_attempts = _source_attempts_from_brief(brief)
        if not source_attempts:
            # This is a system invariant failure, not a market result. Preserve it explicitly.
            raise RuntimeError("research routing invariant failed: zero source attempts after public discovery floor")

        bridge = {
            "status": "DETERMINISTIC_BATCH_ROUTING_TRUST",
            "retrieval_query": lane_retrieval,
            "relevance_query": base_relevance,
            "api_calls": 0,
            "error": None,
        }
        return {
            "engine_version": getattr(idea_loop, "ENGINE_VERSION", "FIX5"),
            "mode": "IDEA_RESEARCH_BATCH_AUDITABLE_SOURCE_GROUNDING",
            "status": status,
            "idea": {"title": title, "description": base_description},
            "research_lane": lane,
            "research_brief": brief,
            "market_truth_writes": 0,
            "ai_api_calls": 0,
            "query_bridge": bridge,
            "original_page_checks": page_checks,
            "research_trace": {
                "mode": "DETERMINISTIC_PUBLIC_SOURCE_PLUS_ORIGINAL_PAGE_SOURCE_GROUNDING",
                "research_lane": lane,
                "retrieval_query": lane_retrieval,
                "relevance_query": base_relevance,
                "query_bridge_status": "DETERMINISTIC_BATCH_ROUTING_TRUST",
                "query_bridge_api_calls": 0,
                "source_attempts": source_attempts,
                "query_runs": query_runs,
                "original_page_audit_ms": page_check_ms,
                "total_ms": int((time.monotonic() - run_started) * 1000),
                "routing_invariant": "AT_LEAST_ONE_REAL_SOURCE_ATTEMPT",
                "general_web_provider": _general_web_provider()[0],
                "general_web_configured": _general_web_provider()[0] is not None,
                "coverage_contract": "TRACKING_REQUIRES_REAL_PUBLIC_SOURCE_ATTEMPTS;_NO_MARKET_DECISION",
                "tracking_mode": "RELATED_MATERIAL_DISCOVERY",
                "source_expansion_version": "TRACKING_HUMANVOICE_V2_5",
                "research_quality_version": "TRACKING_RESEARCH_QUALITY_V2_5_5",
                "source_expansion_mode": expansion_mode,
                "web_query_fanout": len(fanout_specs),
                "tracking_source_families": [family for _, family, _, _ in fanout_specs],
            },
            "truth_boundary": "TRACKING_DISCOVERY_ONLY;_NO_LLM_QUERY_BRIDGE;_NO_MARKET_JUDGMENT;_ZERO_SOURCE_ATTEMPT_FORBIDDEN",
        }

    return await asyncio.to_thread(_run)


async def _run_worker(batch_size: int) -> None:
    from processors.signalforge_research_backlog import run_continuous_session

    await run_continuous_session(
        _REPO_ROOT,
        research_fn=_research_deterministic_batch,
        batch_size=batch_size,
        session_job_cap=_SESSION_JOB_CAP,
    )


def _worker_running() -> bool:
    return _worker_task is not None and not _worker_task.done()


def _autopilot_running() -> bool:
    return _autopilot_task is not None and not _autopilot_task.done()


async def _autopilot_supervisor() -> None:
    """At most once a minute, resume pending Founder-opportunity research."""
    while True:
        await asyncio.sleep(_IDLE_POLL_SECONDS)
        try:
            if _worker_running():
                continue
            from processors.signalforge_research_backlog import auto_run_allowed, has_pending_work, load_store
            # Repair stale RUNNING/orphan RESEARCHING state before sync. Without this, a backend
            # restart can look like "no pending work" until someone opens the Dashboard.
            load_store(_REPO_ROOT, repair_worker=True)
            if auto_run_allowed(_REPO_ROOT) and has_pending_work(_REPO_ROOT):
                await _ensure_worker_started(_CONTINUOUS_BATCH_SIZE, founder_resume=False)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Idle polling is best-effort. Search/import failures must stay visible in backlog metadata,
            # never crash API routes or turn into market conclusions.
            continue


def _ensure_autopilot_supervisor() -> None:
    global _autopilot_task
    if _autopilot_running():
        return
    _autopilot_task = asyncio.create_task(_autopilot_supervisor())


@router.on_event("startup")
async def _research_backlog_startup_autopilot() -> None:
    """Resume unattended research when the API process starts, even if no Dashboard tab is open.

    Founder pause state remains authoritative. Startup failures are best-effort workflow errors and
    must never prevent the rest of SignalForge from starting.
    """
    _ensure_autopilot_supervisor()
    try:
        if not _worker_running():
            from processors.signalforge_research_backlog import load_store
            load_store(_REPO_ROOT, repair_worker=True)
            await _ensure_worker_started(_CONTINUOUS_BATCH_SIZE, founder_resume=False)
    except asyncio.CancelledError:
        raise
    except Exception:
        return


async def _ensure_worker_started(max_jobs: int, *, founder_resume: bool = False) -> dict[str, Any]:
    global _worker_task
    from processors.signalforge_research_backlog import (
        auto_run_allowed,
        backlog_view,
        has_pending_work,
        note_auto_start,
        resume_auto_run,
    )

    _ensure_autopilot_supervisor()
    if founder_resume:
        resume_auto_run(_REPO_ROOT)
    if _worker_running():
        return {"status": "ALREADY_RUNNING", "worker": backlog_view(_REPO_ROOT, limit=1).get("worker", {})}
    # A manual resume should be sufficient after an API restart; do not require a prior GET
    # request to repair persistent stale worker markers.
    from processors.signalforge_research_backlog import load_store
    load_store(_REPO_ROOT, repair_worker=True)
    if not auto_run_allowed(_REPO_ROOT):
        current = backlog_view(_REPO_ROOT, limit=1)
        automation = current.get("automation") if isinstance(current.get("automation"), dict) else {}
        if bool(automation.get("paused_by_founder", False)):
            status = "PAUSED_BY_FOUNDER"
        elif automation.get("source_circuit_retry_after"):
            status = "SOURCE_CIRCUIT_COOLDOWN"
        else:
            status = "AUTO_RUN_BLOCKED"
        return {"status": status, "worker": current.get("worker", {}), "automation": automation}
    if not has_pending_work(_REPO_ROOT):
        return {"status": "NO_PENDING_WORK", "worker": backlog_view(_REPO_ROOT, limit=1).get("worker", {})}
    batch_size = max(1, min(int(max_jobs or _CONTINUOUS_BATCH_SIZE), 1000))
    note_auto_start(_REPO_ROOT)
    _worker_task = asyncio.create_task(_run_worker(batch_size))
    return {
        "status": "STARTED",
        "batch_size": batch_size,
        "session_job_cap": _SESSION_JOB_CAP,
        "continuous": True,
        "market_truth_writes": 0,
    }


@router.post("/research-backlog/start", status_code=202)
async def research_backlog_start(payload: dict[str, Any] | None = None):
    """Resume autopilot and start a bounded background queue."""
    body = payload or {}
    max_jobs = max(1, min(int(body.get("max_jobs") or _CONTINUOUS_BATCH_SIZE), 1000))
    result = await _ensure_worker_started(max_jobs, founder_resume=True)
    return {**result, "truth_boundary": "BACKGROUND_TRACKING_QUEUE_COLLECTS_RELATED_MATERIAL_ONLY;_NO_MARKET_JUDGMENT"}


@router.post("/research-backlog/stop", status_code=202)
async def research_backlog_stop():
    from processors.signalforge_research_backlog import request_stop

    return request_stop(_REPO_ROOT)


@router.post("/research-backlog/{item_id}/refresh", status_code=202)
async def research_backlog_refresh_item(item_id: str):
    from processors.signalforge_research_backlog import request_tracking_refresh

    result = request_tracking_refresh(_REPO_ROOT, item_id)
    if result.get("status") == "NOT_FOUND":
        raise HTTPException(status_code=404, detail=f"research backlog item {item_id!r} not found")
    auto_start = await _ensure_worker_started(_CONTINUOUS_BATCH_SIZE, founder_resume=False)
    return {**result, "auto_start": auto_start}


@router.post("/research-backlog/{item_id}/run")
async def research_backlog_run_item(item_id: str):
    """Run one direction now without changing the global auto-tracking pause state."""
    from processors.signalforge_research_backlog import run_single_item

    result = await run_single_item(_REPO_ROOT, item_id, research_fn=_research_deterministic_batch)
    if result.get("status") == "NOT_FOUND":
        raise HTTPException(status_code=404, detail=f"research backlog item {item_id!r} not found")
    return result


@router.post("/research-backlog/{item_id}/handoff-copied")
async def research_backlog_handoff_copied(item_id: str, payload: dict[str, Any] | None = None):
    """Acknowledge only after the UI successfully copied the exact handoff text."""
    from processors.signalforge_research_backlog import acknowledge_handoff

    body = payload or {}
    expected_hash = str(body.get("handoff_hash") or "").strip() or None
    result = acknowledge_handoff(_REPO_ROOT, item_id, expected_hash=expected_hash)
    if result.get("status") == "NOT_FOUND":
        raise HTTPException(status_code=404, detail=f"research backlog item {item_id!r} not found")
    if result.get("status") == "HANDOFF_HASH_REQUIRED":
        raise HTTPException(status_code=422, detail="handoff_hash is required; acknowledgement must refer to the exact copied packet")
    if result.get("status") == "STALE_HANDOFF":
        raise HTTPException(status_code=409, detail="handoff changed before acknowledgement; copy the refreshed handoff instead")
    return result


@router.get("/research-backlog/{item_id}")
async def research_backlog_item(item_id: str):
    from processors.signalforge_research_backlog import backlog_detail

    result = backlog_detail(_REPO_ROOT, item_id)
    if result.get("status") == "NOT_FOUND":
        raise HTTPException(status_code=404, detail=f"research backlog item {item_id!r} not found")
    return result
