from __future__ import annotations

from pathlib import Path
import sys
from urllib.parse import parse_qs, urlparse
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import processors.signalforge_founder_idea_loop as sf
import processors.signalforge_source_expansion as sx

IDEA = "AI coding agents 完成工作後，使用者很難快速確認它到底有沒有真的做對、做完"
BRIDGE = "AI coding agents completion verification"

checks: list[tuple[bool, str, object]] = []
def check(ok: bool, name: str, detail: object = "") -> None:
    checks.append((bool(ok), name, detail))
    print(("GREEN" if ok else "FAIL"), name, detail)

check(sf._hn_comment_recall_query(BRIDGE) == "ai code review", "HN recall uses market-language query", sf._hn_comment_recall_query(BRIDGE))

calls: list[str] = []
def fake_request_json(url: str, **kwargs):
    calls.append(url)
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    if parsed.path.endswith('/api/v1/search') and qs.get('tags') == ['comment']:
        # Captured real Golden-12 HN comment shape/content (2026-08-16).
        return {
            "hits": [{
                "objectID": "49317798",
                "story_id": "49317589",
                "story_title": "Is this the end of human code review?",
                "comment_text": "Think we're pretty close to the point where we'll no longer need to prompt AI to refactor or review the refactoring if it's done within tight constraints. But when functionality changes may be acceptable as part of it, it's less clear - in my experience AI isn't at a point yet where it can always be trusted to understand what the requirements are. That's where human review is still useful and in many cases, essential.",
                "author": "alertchecker",
                "created_at": "2026-08-16T07:46:26.000Z",
            }]
        }, {"status_code": 200, "elapsed_ms": 5}
    if parsed.path.endswith('/api/v1/search'):
        return {
            "hits": [{
                "objectID": "47217890",
                "story_id": "47217890",
                "title": "Show HN: AgentTeams – Traceable AI coding workflows",
                "story_text": "AI coding agents ship code quickly. AgentTeams adds completion reports and verification summaries.",
                "author": "rlarua",
                "created_at": "2026-03-02T13:45:50Z",
                "points": 2,
                "num_comments": 0,
            }]
        }, {"status_code": 200, "elapsed_ms": 5}
    if '/api/v1/items/' in parsed.path:
        sid = parsed.path.rsplit('/', 1)[-1]
        title = "Is this the end of human code review?" if sid == "49317589" else "Show HN: AgentTeams – Traceable AI coding workflows"
        return {"id": sid, "title": title, "children": []}, {"status_code": 200, "elapsed_ms": 5}
    raise AssertionError(url)

orig = sf._request_json
sf._request_json = fake_request_json
try:
    hn = sf._search_hn(BRIDGE)
finally:
    sf._request_json = orig

check(any('tags=comment' in u and 'query=ai+code+review' in u for u in calls), "HN executes explicit comment recall endpoint", calls)
check(str((hn.get('transport') or {}).get('comment_recall', {}).get('status')) == 'SUCCESS', "HN comment recall is visible in transport", (hn.get('transport') or {}).get('comment_recall'))
comments = [x for x in hn.get('traces', []) if str(x.get('content_unit')) == 'COMMENT']
posts = [x for x in hn.get('traces', []) if str(x.get('content_unit')) == 'POST']
check(any(x.get('url') == 'https://news.ycombinator.com/item?id=49317798' for x in comments), "captured real HN human-review comment is retrieved", comments)
check(any(x.get('url') == 'https://news.ycombinator.com/item?id=47217890' for x in posts), "AgentTeams root remains a post", posts)

RICH_RELEVANCE = sf._bridged_relevance_query(IDEA, BRIDGE)
check("review" in RICH_RELEVANCE.lower() and "requirements" in RICH_RELEVANCE.lower(), "relevance semantics preserve review/requirements", RICH_RELEVANCE)
check(BRIDGE == "AI coding agents completion verification", "retrieval bridge stays compact", BRIDGE)

fresh = {
    "status": "PARTIAL",
    "founder_query": IDEA,
    "relevance_query": RICH_RELEVANCE,
    "queries": [IDEA, BRIDGE],
    "sources": [
        {"source": "HACKER_NEWS_ALGOLIA", "status": "SUCCESS", "count": len(hn.get('traces') or []), "traces": hn.get('traces') or []},
        {"source": "GDELT_DOC", "status": "FAILED", "count": 0, "error": "timeout", "traces": []},
        {"source": "BLUESKY_PUBLIC_SEARCH", "status": "FAILED", "count": 0, "error": "HTTP 403", "traces": []},
    ],
    "traces": hn.get('traces') or [],
    "language_coverage": "SUPPORTED_BY_CURRENT_QUERY_BRIDGE",
}
summary = sf.summarize_idea_research_probe(fresh)
brief = sf.build_founder_research_brief(title=IDEA, description="", fresh=fresh, fresh_summary=summary)
check(any(x.get('url') == 'https://news.ycombinator.com/item?id=49317798' for x in brief.get('human_comments', [])), "captured real comment reaches Founder human-comments section", brief.get('human_comments'))
check(any(x.get('url') == 'https://news.ycombinator.com/item?id=47217890' for x in brief.get('similar_products', [])), "AgentTeams root reaches solution section", brief.get('similar_products'))
status = sf._research_status(collection_status='PARTIAL', research_brief=brief)
check(status == 'RESEARCH_READY', "useful evidence is ready even when optional expansion sources fail", status)
check(any('部分資料來源' in str(x) for x in brief.get('gaps', [])), "optional source failures remain visible as a gap", brief.get('gaps'))

# HN root-story semantics: regular story/article != human comment; Ask HN root is human.
regular_story = {
    "source": "HACKER_NEWS_ALGOLIA", "kind": "DISCUSSION", "content_unit": "POST",
    "title": "Code Review Wasn't Built for the AI Era",
    "excerpt": "AI generated code creates a review bottleneck and acceptance criteria can be missed.",
    "metadata": {"content_unit": "POST", "story_id": "s1", "object_id": "s1"},
}
ask_story = {
    "source": "HACKER_NEWS_ALGOLIA", "kind": "DISCUSSION", "content_unit": "POST",
    "title": "Ask HN: How do you review AI-generated code?",
    "excerpt": "We receive large AI generated PRs and struggle to review them safely.",
    "metadata": {"content_unit": "POST", "story_id": "s2", "object_id": "s2"},
}
regular_rel = sf.classify_trace_relevance(hypothesis_text=RICH_RELEVANCE, trace=regular_story)
ask_rel = sf.classify_trace_relevance(hypothesis_text=RICH_RELEVANCE, trace=ask_story)
check(sf._evidence_lane(regular_story, regular_rel) == "PUBLISHED_OR_MARKET_ARTIFACT", "regular HN root is supporting material, not human comment", sf._evidence_lane(regular_story, regular_rel))
check(sf._evidence_lane(ask_story, ask_rel) == "HUMAN_CONVERSATION", "Ask HN root can remain human conversation", sf._evidence_lane(ask_story, ask_rel))

# Adjacent criticism is useful counter material without being promoted to core evidence.
counter_trace = {
    "source": "HACKER_NEWS_ALGOLIA", "kind": "DISCUSSION", "content_unit": "COMMENT",
    "title": "AI code review discussion",
    "excerpt": "The AI code review tool has poor results and is not worth the noise it causes developers.",
    "metadata": {"content_unit": "COMMENT"},
}
counter_rel = sf.classify_trace_relevance(hypothesis_text=RICH_RELEVANCE, trace=counter_trace)
counter_trace["thesis_relevance"] = counter_rel
check(str(counter_rel.get("grade")) in {"R1", "R2"} and not bool(counter_rel.get("countable")), "adjacent review-tool criticism stays non-core", counter_rel.get("grade"))
check(sf._looks_like_counter_evidence(counter_trace), "adjacent explicit criticism can enter counter-evidence lane", counter_trace.get("excerpt"))

related_comment = {
    "source": "HACKER_NEWS_ALGOLIA", "kind": "DISCUSSION", "content_unit": "COMMENT",
    "title": "How do you review AI-generated code?",
    "excerpt": "We were handed a very large AI-generated backend PR and do not know how to review it efficiently.",
    "author": "engineer", "url": "https://news.ycombinator.com/item?id=related1",
    "metadata": {"content_unit": "COMMENT"},
}
related_fresh = {
    "founder_query": IDEA, "relevance_query": RICH_RELEVANCE,
    "traces": [related_comment],
    "sources": [{"source": "HACKER_NEWS_ALGOLIA", "status": "SUCCESS", "count": 1, "traces": [related_comment]}],
}
related_summary = sf.summarize_idea_research_probe(related_fresh)
check(len(related_summary.get("founder_primary_conversations") or []) == 1, "R1 close human review burden remains useful Idea Research material", related_summary.get("trace_relevance"))
check((related_summary.get("founder_primary_conversations") or [{}])[0].get("research_match") == "RELATED", "R1 material is marked related, not exact", (related_summary.get("founder_primary_conversations") or [{}])[0].get("research_match"))

# A transport failure on query 1 is not retried for every normal research lens.
orig_run_expansion = sx.run_source_expansion
orig_registry = sx.SOURCE_REGISTRY
variant_calls = []
sx.SOURCE_REGISTRY = {
    "GDELT_DOC": SimpleNamespace(cost_policy="NO_METERED_COST_DECLARED"),
    "BLUESKY_PUBLIC_SEARCH": SimpleNamespace(cost_policy="NO_METERED_COST_DECLARED"),
    "BRAVE_WEB": SimpleNamespace(cost_policy="NO_METERED_COST_DECLARED"),
}
def fake_run_expansion(hypothesis_text, query, *, explicit_source_ids=None):
    variant_calls.append((query, None if explicit_source_ids is None else list(explicit_source_ids)))
    if explicit_source_ids is None:
        return {
            "plan": {"selected_source_ids": ["GDELT_DOC", "BLUESKY_PUBLIC_SEARCH", "BRAVE_WEB"]},
            "sources": [
                {"source": "GDELT_DOC", "status": "FAILED", "count": 0, "error": "timeout", "traces": []},
                {"source": "BLUESKY_PUBLIC_SEARCH", "status": "FAILED", "count": 0, "error": "HTTP 403", "traces": []},
                {"source": "BRAVE_WEB", "status": "SUCCESS", "count": 0, "traces": []},
            ],
            "traces": [], "status": "PARTIAL",
        }
    return {
        "plan": {"selected_source_ids": list(explicit_source_ids or [])},
        "sources": [{"source": sid, "status": "SUCCESS", "count": 0, "traces": []} for sid in (explicit_source_ids or [])],
        "traces": [], "status": "PASS",
    }
sx.run_source_expansion = fake_run_expansion
try:
    sx.run_source_expansion_queries("idea", ["q1", "q2", "q3"], max_queries=3)
finally:
    sx.run_source_expansion = orig_run_expansion
    sx.SOURCE_REGISTRY = orig_registry
check(len(variant_calls) == 3 and variant_calls[1][1] == ["BRAVE_WEB"] and variant_calls[2][1] == ["BRAVE_WEB"], "failed expansion sources are not retried for every query lens", variant_calls)

print('-' * 96)
passed = sum(1 for ok, _, _ in checks if ok)
print(f"IDEA_RESEARCH_FIX5_ACCEPTANCE: {passed}/{len(checks)} GREEN")
raise SystemExit(0 if passed == len(checks) else 1)
