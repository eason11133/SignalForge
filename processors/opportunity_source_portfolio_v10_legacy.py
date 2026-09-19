from __future__ import annotations

import concurrent.futures
import hashlib
import html
import json
import os
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

ENGINE_VERSION = "signalforge-source-portfolio-v10-public-feed-expansion"
CACHE_PATH = Path(".radar_runtime/source_portfolio_v10.json")
CACHE_TTL_SECONDS = 12 * 3600
REQUEST_TIMEOUT = 10
MAX_NETWORK_REQUESTS = 42
MAX_DOCS = 1200
USER_AGENT = "SignalForge/10.0 (+opportunity-research; bounded-public-feeds)"

# These sources are deliberately public, read-only, and credential-free. Individual adapters fail soft.
STACK_SITES = ["workplace", "academia", "diy", "travel", "cooking", "money", "law", "parenting"]
REDDIT_FEEDS_BY_LANE = {
    "MICRO_FRICTION": ["books", "college", "productivity", "BuyItForLife", "HomeImprovement"],
    "BORING_OPS": ["smallbusiness", "Entrepreneur", "freelance", "Teachers"],
    "SECOND_ORDER_PAIN": ["productivity", "college", "Teachers", "freelance"],
    "PROVEN_MARKET_WEDGE": ["smallbusiness", "Entrepreneur", "BuyItForLife"],
    "DISTRIBUTION_MODEL_GAP": ["smallbusiness", "Entrepreneur", "freelance"],
    "TRANSITION_GAP": ["smallbusiness", "productivity", "Entrepreneur"],
}
APP_SEARCH_TERMS_BY_LANE = {
    "MICRO_FRICTION": ["book reading", "study notes", "travel planner", "home inventory"],
    "BORING_OPS": ["small business scheduling", "invoice contractor", "inventory small business", "expense receipt freelancer"],
    "PROVEN_MARKET_WEDGE": ["appointment booking salon", "restaurant order management", "property management landlord", "small business CRM"],
    "DISTRIBUTION_MODEL_GAP": ["field service scheduling", "small business CRM", "appointment booking", "inventory management"],
    "SECOND_ORDER_PAIN": ["AI notes", "AI meeting notes", "AI study assistant"],
    "TRANSITION_GAP": ["AI scheduling", "AI document automation", "AI receptionist", "AI research assistant"],
}

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _clean(v: Any) -> str:
    text = html.unescape(str(v or ""))
    text = _TAG_RE.sub(" ", text)
    return _WS_RE.sub(" ", text).strip()


def _pk(*parts: Any) -> str:
    return hashlib.sha1("|".join(str(x or "") for x in parts).encode("utf-8", "ignore")).hexdigest()[:20]


def _http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json, application/atom+xml, application/xml, text/xml, */*"})
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as r:
        return r.read()


def _json_get(url: str) -> Any:
    return json.loads(_http_get(url).decode("utf-8", "replace"))


def _doc(source: str, table: str, pk: str, title: str, text: str, url: str = "", date: str = "", **meta: Any) -> dict[str, Any] | None:
    text = _clean(text)[:2600]
    title = _clean(title)[:500]
    if len(text) < 35:
        return None
    out = {"source": source, "table": table, "pk": str(pk), "title": title, "text": text, "url": str(url or ""), "date": str(date or "")}
    out.update(meta)
    return out


def _parse_stackexchange(payload: dict[str, Any], site: str) -> list[dict[str, Any]]:
    out = []
    for q in payload.get("items") or []:
        title = _clean(q.get("title"))
        body = _clean(q.get("body"))
        tags = ", ".join(q.get("tags") or [])
        text = f"{title}. {body}. Tags: {tags}"
        d = _doc("community_external", "stackexchange_questions", q.get("question_id") or _pk(site, title), title, text, q.get("link") or "", q.get("creation_date") or "", source_family="stackexchange", source_name=f"stackexchange:{site}")
        if d: out.append(d)
    return out


def _parse_reddit_atom(raw: bytes, subreddit: str) -> list[dict[str, Any]]:
    root = ET.fromstring(raw)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    out = []
    for e in root.findall("a:entry", ns):
        title = _clean(e.findtext("a:title", default="", namespaces=ns))
        content = _clean(e.findtext("a:content", default="", namespaces=ns))
        updated = _clean(e.findtext("a:updated", default="", namespaces=ns))
        eid = _clean(e.findtext("a:id", default="", namespaces=ns))
        link = ""
        for el in e.findall("a:link", ns):
            if el.attrib.get("href"):
                link = el.attrib["href"]; break
        d = _doc("community_external", "reddit_rss", eid or _pk(subreddit, title), title, f"{title}. {content}", link, updated, source_family="reddit_rss", source_name=f"reddit:r/{subreddit}")
        if d: out.append(d)
    return out


def _parse_app_search(payload: dict[str, Any], query: str) -> tuple[list[dict[str, Any]], list[tuple[str, str]]]:
    docs: list[dict[str, Any]] = []
    apps: list[tuple[str, str]] = []
    for app in payload.get("results") or []:
        appid = str(app.get("trackId") or "")
        name = _clean(app.get("trackName"))
        if not appid or not name: continue
        desc = _clean(app.get("description"))
        genre = _clean(app.get("primaryGenreName"))
        seller = _clean(app.get("sellerName"))
        price = app.get("price")
        formatted = _clean(app.get("formattedPrice"))
        paid = False
        try: paid = float(price or 0) > 0
        except Exception: paid = False
        pricing = f" Pricing {formatted or ('$'+str(price))}." if paid else ""
        text = f"App Store software {name}. Seller {seller}. Category {genre}.{pricing} Description: {desc}"
        d = _doc("market_supply_external", "app_store_apps", appid, name, text, app.get("trackViewUrl") or "", app.get("currentVersionReleaseDate") or "", source_family="app_store", source_name="apple_itunes_search", app_id=appid, paid_supply=paid, search_query=query)
        if d: docs.append(d)
        apps.append((appid, name))
    return docs, apps


def _parse_app_reviews(payload: dict[str, Any], appid: str, appname: str) -> list[dict[str, Any]]:
    feed = payload.get("feed") or {}
    entries = feed.get("entry") or []
    if isinstance(entries, dict): entries = [entries]
    out = []
    for e in entries:
        rating = ((e.get("im:rating") or {}).get("label") if isinstance(e.get("im:rating"), dict) else "")
        if not rating: continue
        title = _clean((e.get("title") or {}).get("label") if isinstance(e.get("title"), dict) else e.get("title"))
        content = _clean((e.get("content") or {}).get("label") if isinstance(e.get("content"), dict) else e.get("content"))
        rid = _clean((e.get("id") or {}).get("label") if isinstance(e.get("id"), dict) else e.get("id"))
        updated = _clean((e.get("updated") or {}).get("label") if isinstance(e.get("updated"), dict) else e.get("updated"))
        text = f"App {appname}. Rating {rating}/5. Review title: {title}. Review: {content}"
        d = _doc("product_review_external", "app_store_reviews", rid or _pk(appid, title, content), title or f"{appname} review", text, f"https://apps.apple.com/app/id{appid}", updated, source_family="app_store_reviews", source_name="apple_customer_reviews_rss", app_id=appid, rating=rating)
        if d: out.append(d)
    return out


def _load_previous_gaps() -> set[str]:
    p = Path(".radar_runtime/transition_gap_discovery.json")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        gaps = (((data.get("formation") or {}).get("source_gap_by_lane")) or {})
        out = {lane for lane, v in gaps.items() if str((v or {}).get("status")) != "AVAILABLE"}
        return out
    except Exception:
        return set(APP_SEARCH_TERMS_BY_LANE)


def _dedupe_docs(docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen=set(); out=[]
    for d in docs:
        k=(str(d.get("source")), str(d.get("pk")))
        if not k[1]: k=(str(d.get("source")), _pk(d.get("url"), d.get("title"), d.get("text")))
        if k in seen: continue
        seen.add(k); out.append(d)
        if len(out)>=MAX_DOCS: break
    return out


def _cache_fresh() -> bool:
    try: return CACHE_PATH.exists() and (time.time()-CACHE_PATH.stat().st_mtime)<CACHE_TTL_SECONDS
    except Exception: return False


def read_cache() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    try:
        data=json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        return list(data.get("docs") or []), dict(data.get("health") or {})
    except Exception:
        return [], {"status":"MISS"}


def refresh_source_portfolio(*, force: bool = False) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not force and _cache_fresh():
        docs, health = read_cache(); health=dict(health); health["cache"]="HIT"; return docs, health
    started=time.perf_counter(); gaps=_load_previous_gaps()
    if not gaps: gaps=set(APP_SEARCH_TERMS_BY_LANE)
    request_budget=MAX_NETWORK_REQUESTS
    tasks=[]
    health: dict[str, Any] = {"engine_version":ENGINE_VERSION,"cache":"REFRESH","gap_lanes":sorted(gaps),"adapters":{},"request_budget":request_budget}

    # Stack Exchange: broad cross-domain operational/user pain. One request per site.
    for site in STACK_SITES:
        if request_budget<=0: break
        url="https://api.stackexchange.com/2.3/questions?"+urllib.parse.urlencode({"site":site,"pagesize":35,"order":"desc","sort":"activity","filter":"withbody"})
        tasks.append(("stackexchange", site, url)); request_budget-=1

    # Reddit RSS: gap-directed communities, deduped.
    subs=[]
    for lane in gaps:
        subs.extend(REDDIT_FEEDS_BY_LANE.get(lane,[]))
    for sub in list(dict.fromkeys(subs))[:12]:
        if request_budget<=0: break
        tasks.append(("reddit_rss", sub, f"https://www.reddit.com/r/{sub}/new/.rss?limit=25")); request_budget-=1

    # App Store discovery: gap-directed searches. Search first; review calls are scheduled after search results return.
    queries=[]
    for lane in gaps:
        queries.extend(APP_SEARCH_TERMS_BY_LANE.get(lane,[]))
    queries=list(dict.fromkeys(queries))[:12]
    for q in queries:
        if request_budget<=0: break
        url="https://itunes.apple.com/search?"+urllib.parse.urlencode({"term":q,"entity":"software","limit":4,"country":"us"})
        tasks.append(("app_search", q, url)); request_budget-=1

    docs=[]; app_targets=[]; failures=[]; adapter_counts={}
    def fetch(task):
        kind,key,url=task
        t0=time.perf_counter()
        try:
            raw=_http_get(url)
            return kind,key,url,raw,None,time.perf_counter()-t0
        except Exception as e:
            return kind,key,url,b"",f"{type(e).__name__}: {e}",time.perf_counter()-t0

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        for kind,key,url,raw,err,elapsed in ex.map(fetch,tasks):
            adapter_counts.setdefault(kind,{"requests":0,"docs":0,"failures":0,"seconds":0.0})
            a=adapter_counts[kind]; a["requests"]+=1; a["seconds"]+=elapsed
            if err:
                a["failures"]+=1; failures.append({"adapter":kind,"key":key,"error":err}); continue
            try:
                if kind=="stackexchange": new=_parse_stackexchange(json.loads(raw.decode("utf-8","replace")),key)
                elif kind=="reddit_rss": new=_parse_reddit_atom(raw,key)
                else:
                    new, apps=_parse_app_search(json.loads(raw.decode("utf-8","replace")),key)
                    app_targets.extend(apps[:2])
                docs.extend(new); a["docs"]+=len(new)
            except Exception as e:
                a["failures"]+=1; failures.append({"adapter":kind,"key":key,"error":f"parse {type(e).__name__}: {e}"})

    # App review calls use remaining budget and top two apps per query, deduped.
    review_tasks=[]
    for appid,name in list(dict.fromkeys(app_targets)):
        if request_budget<=0: break
        review_tasks.append(("app_reviews", f"{appid}|{name}", f"https://itunes.apple.com/us/rss/customerreviews/page=1/id={appid}/sortby=mostrecent/json")); request_budget-=1
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        for kind,key,url,raw,err,elapsed in ex.map(fetch,review_tasks):
            adapter_counts.setdefault(kind,{"requests":0,"docs":0,"failures":0,"seconds":0.0})
            a=adapter_counts[kind]; a["requests"]+=1; a["seconds"]+=elapsed
            if err:
                a["failures"]+=1; failures.append({"adapter":kind,"key":key,"error":err}); continue
            try:
                appid,name=key.split("|",1); new=_parse_app_reviews(json.loads(raw.decode("utf-8","replace")),appid,name)
                docs.extend(new); a["docs"]+=len(new)
            except Exception as e:
                a["failures"]+=1; failures.append({"adapter":kind,"key":key,"error":f"parse {type(e).__name__}: {e}"})

    docs=_dedupe_docs(docs)
    source_counts={}
    for d in docs: source_counts[d["source"]]=source_counts.get(d["source"],0)+1
    family_counts={}
    for d in docs: family_counts[str(d.get("source_family") or d.get("source"))]=family_counts.get(str(d.get("source_family") or d.get("source")),0)+1
    successful=sum(1 for v in adapter_counts.values() if v.get("docs",0)>0)
    total_requests=sum(v.get("requests",0) for v in adapter_counts.values())
    status="PASS" if successful>=2 else ("PARTIAL" if successful>=1 else "DEGRADED")
    for v in adapter_counts.values(): v["seconds"]=round(v["seconds"],3)
    health.update({"status":status,"adapters":adapter_counts,"source_counts":source_counts,"family_counts":family_counts,"total_docs":len(docs),"requests_used":total_requests,"requests_remaining":request_budget,"failures":failures[:20],"elapsed_seconds":round(time.perf_counter()-started,3)})
    CACHE_PATH.parent.mkdir(parents=True,exist_ok=True)
    CACHE_PATH.write_text(json.dumps({"generated_at":time.time(),"engine_version":ENGINE_VERSION,"docs":docs,"health":health},ensure_ascii=False,indent=2,default=str),encoding="utf-8")
    return docs,health


def source_portfolio_static_acceptance() -> dict[str, bool]:
    stack={"items":[{"question_id":1,"title":"As a teacher I spend hours copying grades into spreadsheets","body":"<p>Teachers manually copy grades into spreadsheets every week and it is frustrating.</p>","tags":["workflow"],"link":"https://example.test/q1","creation_date":1}]}
    reddit=b'''<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><entry><id>x1</id><title>Book pages keep flipping outside</title><content type="html">As a reader I use a notebook to hold pages down every time I read outside and it is annoying.</content><updated>2026-08-01</updated><link href="https://example.test/r1"/></entry></feed>'''
    app={"results":[{"trackId":123,"trackName":"SalonBook","sellerName":"Example","primaryGenreName":"Business","price":4.99,"formattedPrice":"$4.99","description":"Appointment booking software for salons","trackViewUrl":"https://example.test/app","currentVersionReleaseDate":"2026-08-01"}]}
    reviews={"feed":{"entry":[{"im:rating":{"label":"2"},"title":{"label":"Too many steps"},"content":{"label":"As a salon owner I still use a spreadsheet because booking takes too many taps every day."},"id":{"label":"r1"},"updated":{"label":"2026-08-01"}}]}}
    s=_parse_stackexchange(stack,"workplace"); r=_parse_reddit_atom(reddit,"books"); a,targets=_parse_app_search(app,"appointment booking salon"); rv=_parse_app_reviews(reviews,"123","SalonBook")
    return {"stackexchange":len(s)==1 and s[0]["source"]=="community_external","reddit":len(r)==1 and "reader" in r[0]["text"].lower(),"app_supply":len(a)==1 and a[0].get("paid_supply") is True and "$4.99" in a[0]["text"],"app_reviews":len(rv)==1 and rv[0]["source"]=="product_review_external","request_cap":MAX_NETWORK_REQUESTS<=50}
