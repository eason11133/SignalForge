from __future__ import annotations

import json
import os
import sys
import types
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _stub_database():
    db_pkg = sys.modules.setdefault("database", types.ModuleType("database"))
    conn = types.ModuleType("database.connection")
    class Field:
        def in_(self,*_): return self
        def is_(self,*_): return self
    class Dummy:
        id=Field(); candidate_id=Field(); claim_id=Field(); evidence_id=Field(); case_id=Field()
    for name in ("ProblemCandidate","RadarCase","RadarClaim","RadarClaimEvidence","RadarEvidence"):
        setattr(conn,name,Dummy)
    conn.async_session=None
    sys.modules["database.connection"]=conn
    setattr(db_pkg,"connection",conn)

_stub_database()

from processors import signalforge_source_adapters as adapters
from processors.signalforge_source_expansion import plan_source_expansion, run_source_expansion
from processors.signalforge_source_registry import registry_snapshot, source_runtime_state
from processors.signalforge_founder_idea_loop import build_source_adequacy, merge_expansion_into_fresh, summarize_fresh_probe
from processors.signalforge_founder_query_contracts import source_fit_for_problem_class

results=[]
def check(name, cond, detail=None):
    ok=bool(cond); results.append((name,ok,detail)); print(("PASS" if ok else "FAIL"), name, "" if detail is None else "— "+str(detail)); return ok

@contextmanager
def env(**values):
    old={k:os.environ.get(k) for k in values}
    try:
        for k,v in values.items():
            if v is None: os.environ.pop(k,None)
            else: os.environ[k]=str(v)
        yield
    finally:
        for k,v in old.items():
            if v is None: os.environ.pop(k,None)
            else: os.environ[k]=v

# Registry / legal-security contract.
snap=registry_snapshot(); ids={x["source_id"] for x in snap["sources"]}
check("wave1 registry includes broad/social/video/jobs/feed sources", {"BRAVE_WEB","GDELT_DOC","YOUTUBE_DATA_API","THREADS_API","GREENHOUSE_PUBLIC_JOBS","LEVER_PUBLIC_JOBS","RSS_ATOM"}.issubset(ids), ids)
check("commercially restricted sources are registry-visible but disabled", all(source_runtime_state(x)["runtime_state"]=="RESTRICTED" for x in ["PRODUCT_HUNT_API","REDDIT_API","TIKTOK_RESEARCH"]))
check("registry never exposes credential values", all("credential_value" not in x and "token" not in {k.lower() for k in x.keys()} for x in snap["sources"]))
check("registry security boundary forbids browser/session credential shortcuts", "NO_BROWSER_COOKIES" in snap["security_boundary"] and "VPN_CREDENTIALS" in snap["security_boundary"])

# Brave adapter.
old_json=adapters._request_json
captured={}
def brave_json(url, *, headers=None, timeout=6.0):
    captured["url"]=url; captured["headers"]=dict(headers or {})
    return {"web":{"results":[{"title":"Product discovery agency pricing","description":"A consultancy sells market validation sprints and customer research.","url":"https://agency.example/services/discovery"}]}}, {"status_code":200}
with env(BRAVE_SEARCH_API_KEY="secret-brave-key"):
    adapters._request_json=brave_json
    try: b=adapters.search_brave("market evidence intelligence for AI agencies")
    finally: adapters._request_json=old_json
check("Brave uses server-side subscription header", captured.get("headers",{}).get("X-Subscription-Token")=="secret-brave-key")
check("Brave emits web-page trace with broad observation families", b["count"]==1 and b["traces"][0]["content_unit"]=="WEB_PAGE" and "AGENCY_SERVICE_PAGES" in b["traces"][0]["metadata"]["observation_source_families"], b)
check("Brave result does not echo secret", "secret-brave-key" not in json.dumps(b))

# GDELT adapter.
def gdelt_json(url, *, headers=None, timeout=6.0):
    return {"articles":[{"title":"Agencies adopt AI market research workflows","url":"https://news.example/a","seendate":"20260906T120000Z","domain":"news.example","language":"English","sourcecountry":"US"}]}, {"status_code":200}
with env(SIGNALFORGE_GDELT_ENABLED="1"):
    adapters._request_json=gdelt_json
    try: g=adapters.search_gdelt("AI agency market research")
    finally: adapters._request_json=old_json
check("GDELT emits link/metadata news trace", g["count"]==1 and g["traces"][0]["content_unit"]=="NEWS_ARTICLE_INDEX" and g["traces"][0]["excerpt"]=="", g)

# YouTube search + comments + replies.
def yt_json(url, *, headers=None, timeout=6.0):
    if "/search?" in url:
        return {"items":[{"id":{"videoId":"v1"},"snippet":{"title":"Agency market validation workflow","description":"How product studios validate client ideas","channelTitle":"StudioOps","channelId":"c1","publishedAt":"2026-09-01T00:00:00Z"}}]}, {"status_code":200}
    if "/commentThreads?" in url:
        return {"items":[{"snippet":{"topLevelComment":{"id":"cm1","snippet":{"textDisplay":"We still do client research manually and need evidence before proposals.","authorDisplayName":"AgencyOwner","publishedAt":"2026-09-02T00:00:00Z","likeCount":4}}},"replies":{"comments":[{"id":"r1","snippet":{"textDisplay":"Same here, discovery sprints take too long.","authorDisplayName":"StudioLead","publishedAt":"2026-09-03T00:00:00Z","parentId":"cm1"}}]}}]}, {"status_code":200}
    raise AssertionError(url)
with env(YOUTUBE_API_KEY="yt-key"):
    adapters._request_json=yt_json
    try: y=adapters.search_youtube("agency market validation")
    finally: adapters._request_json=old_json
units={x["content_unit"] for x in y["traces"]}
check("YouTube adapter reads video + top-level comment + reply", {"VIDEO","TOP_LEVEL_COMMENT","COMMENT_REPLY"}.issubset(units), units)
check("YouTube comments are source-level discussion observations", any(x["content_unit"]=="TOP_LEVEL_COMMENT" and "manual" in x["excerpt"].lower() for x in y["traces"]))

# Threads keyword search + replies.
def th_json(url, *, headers=None, timeout=6.0):
    if "keyword_search" in url:
        return {"data":[{"id":"t1","text":"Our agency still validates client ideas manually.","timestamp":"2026-09-01T00:00:00Z","permalink":"https://threads.net/t/t1","username":"founder","has_replies":True,"is_quote_post":False}]}, {"status_code":200}
    if "/t1/replies" in url:
        return {"data":[{"id":"tr1","text":"We pay for research tools but still verify everything ourselves.","timestamp":"2026-09-02T00:00:00Z","permalink":"https://threads.net/t/tr1","username":"studio","has_replies":False}]}, {"status_code":200}
    raise AssertionError(url)
with env(THREADS_ACCESS_TOKEN="threads-token"):
    adapters._request_json=th_json
    try: t=adapters.search_threads("agency market validation")
    finally: adapters._request_json=old_json
check("Threads adapter reads keyword posts and replies", {x["content_unit"] for x in t["traces"]}=={"POST","REPLY"}, t)
check("Threads auth secret is not returned", "threads-token" not in json.dumps(t))

# Greenhouse / Lever public job adapters.
def jobs_json(url, *, headers=None, timeout=6.0):
    if "greenhouse" in url:
        return {"jobs":[
            {"id":1,"title":"Product Strategy Researcher","content":"Lead customer research, product discovery and opportunity validation for client engagements.","absolute_url":"https://boards.example/job/1","updated_at":"2026-09-01","location":{"name":"Remote"}},
            {"id":2,"title":"Backend Engineer","content":"Build distributed systems.","absolute_url":"https://boards.example/job/2","updated_at":"2026-09-01","location":{"name":"Remote"}},
        ]}, {"status_code":200}
    if "lever.co" in url:
        return [
            {"id":"l1","text":"Market Research Strategist","descriptionPlain":"Run client discovery, market validation and strategy engagements.","hostedUrl":"https://jobs.lever.co/acme/l1","categories":{"team":"Strategy","location":"Remote","commitment":"Full-time"}},
            {"id":"l2","text":"Frontend Engineer","descriptionPlain":"React work","hostedUrl":"https://jobs.lever.co/acme/l2","categories":{"team":"Engineering"}},
        ], {"status_code":200}
    raise AssertionError(url)
with env(SIGNALFORGE_GREENHOUSE_BOARDS="agencyone", SIGNALFORGE_LEVER_SITES="agencytwo"):
    adapters._request_json=jobs_json
    try:
        gh=adapters.search_greenhouse_jobs("product strategy customer research opportunity validation")
        lv=adapters.search_lever_jobs("market research client discovery validation strategy")
    finally: adapters._request_json=old_json
check("Greenhouse public jobs adapter filters to query-relevant jobs", gh["count"]==1 and gh["traces"][0]["content_unit"]=="JOB_POST", gh)
check("Lever public jobs adapter filters to query-relevant jobs", lv["count"]==1 and lv["traces"][0]["content_unit"]=="JOB_POST", lv)

# RSS/Atom configured feed parser + SSRF guard.
rss_xml=b'''<?xml version="1.0"?><rss><channel><item><title>Agency discovery sprint lessons</title><link>https://blog.example/post</link><description>Client validation research still takes too long and teams use manual spreadsheets.</description></item><item><title>Cooking notes</title><link>https://blog.example/food</link><description>Pasta.</description></item></channel></rss>'''
old_bytes=adapters._request_public_bytes; old_assert=adapters._assert_public_http_url
with env(SIGNALFORGE_PUBLIC_FEEDS_JSON=json.dumps([{"url":"https://blog.example/rss","observation_families":["FOUNDER_COMMUNITIES","AGENCY_COMMUNITIES"]}])):
    adapters._assert_public_http_url=lambda url: None
    adapters._request_public_bytes=lambda url, **kwargs:(rss_xml,{"status_code":200})
    try: rss=adapters.search_rss_feeds("agency discovery validation research")
    finally:
        adapters._request_public_bytes=old_bytes; adapters._assert_public_http_url=old_assert
check("RSS adapter keeps configured observation-family identity", rss["count"]==1 and "AGENCY_COMMUNITIES" in rss["observation_source_families"], rss)
for bad in ["http://127.0.0.1/feed", "http://169.254.169.254/latest/meta-data", "https://user:pass@example.com/rss"]:
    try:
        adapters._assert_public_http_url(bad); blocked=False
    except adapters.SourceAdapterError:
        blocked=True
    check(f"RSS SSRF/credential guard blocks {bad}", blocked)

# Planner uses only ready + relevant sources and never selects commercial-restricted APIs.
with env(BRAVE_SEARCH_API_KEY="k", YOUTUBE_API_KEY="k", THREADS_ACCESS_TOKEN="k", SIGNALFORGE_GREENHOUSE_BOARDS="a", SIGNALFORGE_LEVER_SITES="b", SIGNALFORGE_PUBLIC_FEEDS="https://example.com/rss", SIGNALFORGE_GDELT_ENABLED="1"):
    plan=plan_source_expansion("SignalForge Market Evidence Intelligence for AI Agencies doing opportunity validation")
selected=set(plan["selected_source_ids"])
check("agency expansion planner selects configured broad/community/jobs sources", {"BRAVE_WEB","YOUTUBE_DATA_API","THREADS_API","GREENHOUSE_PUBLIC_JOBS","LEVER_PUBLIC_JOBS","RSS_ATOM","GDELT_DOC"}.issubset(selected), selected)
check("planner never auto-selects Product Hunt/Reddit/TikTok restricted sources", not ({"PRODUCT_HUNT_API","REDDIT_API","TIKTOK_RESEARCH"} & selected), selected)

# Observation-family coverage, not platform name, changes source-fit adequacy.
agency="SignalForge Market Evidence Intelligence for AI Agencies doing opportunity validation"
base={
    "founder_query":agency,"coverage":"COMPLETE_FOR_CONFIGURED_SOURCES","language_coverage":"SUPPORTED_BY_CURRENT_QUERY_BRIDGE",
    "source_health":[
        {"source":"BRAVE_WEB","source_family":"BRAVE_WEB","observation_source_families":["AGENCY_SERVICE_PAGES","RESEARCH_TOOL_REVIEWS"],"status":"SUCCESS","count":2},
        {"source":"THREADS_API","source_family":"THREADS","observation_source_families":["FOUNDER_COMMUNITIES","AGENCY_COMMUNITIES"],"status":"SUCCESS","count":2},
    ],
}
# A broad web API alone must NOT satisfy both agency observation dimensions.
brave_only={
    "founder_query":agency,"coverage":"COMPLETE_FOR_CONFIGURED_SOURCES","language_coverage":"SUPPORTED_BY_CURRENT_QUERY_BRIDGE",
    "source_health":[
        {"source":"BRAVE_WEB","source_family":"BRAVE_WEB","observation_source_families":["AGENCY_SERVICE_PAGES","RESEARCH_TOOL_REVIEWS"],"status":"SUCCESS","count":2},
    ],
}
sf_brave=source_fit_for_problem_class(agency, configured_source_families=["BRAVE_WEB"])
adeq_brave=build_source_adequacy(fresh_summary=brave_only, source_fit=sf_brave)
check("Brave alone cannot make agency source-fit sufficient", adeq_brave["source_fit_sufficient"] is False and "BUYER_VOICE" in adeq_brave["missing_observation_dimensions"], adeq_brave)

sf=source_fit_for_problem_class(agency, configured_source_families=["BRAVE_WEB","THREADS"])
adeq=build_source_adequacy(fresh_summary=base, source_fit=sf)
check("Brave plus buyer-voice source can make agency source-fit sufficient", adeq["source_fit_sufficient"] is True and "AGENCY_SERVICE_PAGES" in adeq["configured_source_families"] and adeq.get("observation_dimensions_complete") is True, adeq)

# Expansion trace merge passes through existing relevance/role gate and remains unvalidated.
legacy={"engine_version":"fixture","status":"PASS","founder_query":agency,"queries":[agency],"search_query_used":agency,"language_coverage":"SUPPORTED_BY_CURRENT_QUERY_BRIDGE","sources":[],"traces":[],"truth_boundary":"fixture"}
exp={"status":"PASS","plan":{},"elapsed_ms":1,"sources":[{"source":"THREADS_API","source_family":"THREADS","observation_source_families":["FOUNDER_COMMUNITIES","AGENCY_COMMUNITIES"],"status":"SUCCESS","count":1,"traces":[{"source":"THREADS_API","kind":"DISCUSSION","content_unit":"POST","title":"AI agency founder market validation","excerpt":"Our agency manually researches client opportunities and discovery takes too long.","url":"https://threads.net/t/1","metadata":{"observation_source_families":["AGENCY_COMMUNITIES"]},"truth_status":"UNVALIDATED_SEARCH_TRACE"}]}]}
merged=merge_expansion_into_fresh(legacy,exp); summary=summarize_fresh_probe(merged)
check("expanded social trace still passes thesis-relevance before counting", summary["relevant_trace_count"]==1 and summary["problem_discussions"]==1, summary)
check("expanded trace keeps UNVALIDATED truth boundary", all(x.get("truth_status")=="UNVALIDATED_SEARCH_TRACE" for x in merged["traces"]))

route=(ROOT/"api/routes/signalforge.py").read_text(encoding="utf-8")
check("source registry and bounded source-probe API endpoints exist", "@router.get('/sources/registry')" in route and "@router.post('/sources/probe')" in route)
check("paid source-probe endpoint is fail-closed behind server-side token", "SIGNALFORGE_SOURCE_PROBE_TOKEN" in route and "compare_digest" in route and "X-SignalForge-Source-Token" in route)
check("source expansion has zero direct Market Truth authority", "market_ground_truth" not in (ROOT/"processors/signalforge_source_expansion.py").read_text(encoding="utf-8") and "RadarClaim" not in (ROOT/"processors/signalforge_source_adapters.py").read_text(encoding="utf-8"))

passed=sum(1 for _,ok,_ in results if ok)
print("-"*100)
print(f"RESULT: {passed}/{len(results)} PASS")
if passed != len(results): raise SystemExit(1)
print("FINAL_STATUS: SIGNALFORGE_SOURCE_EXPANSION_WAVE1_ACCEPTANCE_PASS")
